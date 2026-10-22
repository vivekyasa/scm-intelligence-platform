"""
Synthetic planning data generator for the SCM Intelligence Platform.

Generates 52 weeks of demand, supply and inventory data across ~200 items
and 5 locations, then derives exceptions from the resulting position.

Everything here is invented. No real company data is used or referenced.

Usage:
    python generate_data.py                 # writes CSVs to ./data
    python generate_data.py --seed 7        # different dataset, reproducible
"""

import argparse
import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

# ----------------------------------------------------------------- config

N_ITEMS = 200
N_WEEKS = 52
HISTORY_WEEKS = 26          # weeks before "today" that have actuals
OUT_DIR = Path(__file__).parent / "data"

FAMILIES = [
    ("ATM-CORE", "Core ATM module"),
    ("ATM-CASH", "Cash handling assembly"),
    ("KIOSK", "Self-service kiosk part"),
    ("PRINTER", "Receipt printer component"),
    ("SECURITY", "Security and lock assembly"),
    ("SPARES", "Field service spare"),
]

LOCATIONS = [
    ("PLT-01", "Columbus Plant",      "NORTH_AMERICA", "PLANT"),
    ("DC-ATL", "Atlanta DC",          "NORTH_AMERICA", "DC"),
    ("DC-FRA", "Frankfurt DC",        "EMEA",          "DC"),
    ("DC-SIN", "Singapore DC",        "APAC",          "DC"),
    ("FS-DAL", "Dallas Forward Stock","NORTH_AMERICA", "FORWARD_STOCK"),
]

PLANNERS = ["PLN-A", "PLN-B", "PLN-C", "PLN-D"]


# ----------------------------------------------------------------- helpers

def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def build_items(rng):
    """ABC classes drive safety stock, lead time and cost, as they would in reality."""
    items = []
    for i in range(1, N_ITEMS + 1):
        family, family_desc = rng.choice(FAMILIES)
        # Skewed so A items are the minority, like a real catalogue
        abc = rng.choices(["A", "B", "C"], weights=[0.2, 0.3, 0.5])[0]

        if abc == "A":
            unit_cost = round(rng.uniform(400, 2500), 2)
            lead_time = rng.choice([21, 28, 35, 45])
            base_demand = rng.randint(60, 220)
        elif abc == "B":
            unit_cost = round(rng.uniform(80, 400), 2)
            lead_time = rng.choice([14, 21, 28])
            base_demand = rng.randint(25, 90)
        else:
            unit_cost = round(rng.uniform(5, 80), 2)
            lead_time = rng.choice([7, 10, 14])
            base_demand = rng.randint(5, 40)

        # Safety stock sized roughly off lead time demand, with class policy on top
        weeks_cover = {"A": 2.5, "B": 2.0, "C": 1.5}[abc]
        safety_stock = int(base_demand * (lead_time / 7) / 4 * weeks_cover)

        items.append({
            "item_id": i,
            "item_number": f"SKU-{1000 + i}",
            "description": f"{family_desc} {rng.randint(100, 999)}",
            "product_family": family,
            "abc_class": abc,
            "unit_cost": unit_cost,
            "lead_time_days": lead_time,
            "safety_stock_qty": safety_stock,
            "min_order_qty": rng.choice([10, 25, 50, 100]),
            "planner_code": rng.choice(PLANNERS),
            # generation-only attributes, not written to the items table
            "_base_demand": base_demand,
            "_seasonal_amp": rng.uniform(0.05, 0.35),
            "_seasonal_phase": rng.uniform(0, 2 * math.pi),
            "_trend": rng.uniform(-0.004, 0.008),
            "_noise": rng.uniform(0.08, 0.30),
            # systematic forecast bias: some items are chronically over-forecast
            "_fcst_bias": rng.gauss(0.0, 0.10),
            # supply reliability: how often planned receipts actually cover need
            "_supply_reliability": rng.uniform(0.75, 1.0),
        })
    return items


def demand_for(item, week_idx, rng):
    """Seasonality plus trend plus noise. Never negative."""
    seasonal = 1 + item["_seasonal_amp"] * math.sin(
        2 * math.pi * week_idx / 52 + item["_seasonal_phase"]
    )
    trend = 1 + item["_trend"] * week_idx
    noise = rng.gauss(1.0, item["_noise"])
    qty = item["_base_demand"] * seasonal * trend * noise
    return max(0, int(round(qty)))


# ----------------------------------------------------------------- generate

def generate(seed: int):
    rng = random.Random(seed)

    today = monday_of(date.today())
    start_week = today - timedelta(weeks=HISTORY_WEEKS)
    weeks = [start_week + timedelta(weeks=w) for w in range(N_WEEKS)]
    current_version = f"{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}"

    items = build_items(rng)

    forecast_rows, actual_rows = [], []
    supply_rows, position_rows, exception_rows = [], [], []

    for item in items:
        for loc_idx, (loc_code, *_rest) in enumerate(LOCATIONS, start=1):
            # Not every item is stocked everywhere
            if rng.random() < 0.45:
                continue

            # Location scales demand: a plant sees more than forward stock
            loc_scale = {1: 1.0, 2: 0.7, 3: 0.55, 4: 0.4, 5: 0.25}[loc_idx]

            on_hand = int(item["safety_stock_qty"] * rng.uniform(0.8, 2.2) * loc_scale)

            for w_idx, week in enumerate(weeks):
                true_demand = int(demand_for(item, w_idx, rng) * loc_scale)
                is_history = week < today

                # Forecast is the truth plus systematic bias plus error.
                # Error grows the further out you forecast, as it does in life.
                horizon = max(0, (week - today).days / 7)
                err_sd = 0.10 + 0.012 * horizon
                fcst = true_demand * (1 + item["_fcst_bias"]) * rng.gauss(1.0, err_sd)
                fcst_qty = max(0, int(round(fcst)))

                forecast_rows.append({
                    "item_id": item["item_id"],
                    "location_id": loc_idx,
                    "week_start": week.isoformat(),
                    "forecast_version": current_version,
                    "forecast_qty": fcst_qty,
                })

                if is_history:
                    actual_rows.append({
                        "item_id": item["item_id"],
                        "location_id": loc_idx,
                        "week_start": week.isoformat(),
                        "actual_qty": true_demand,
                    })

                consumed = true_demand if is_history else fcst_qty

                # Supply: aims to cover demand and rebuild to safety stock,
                # but only succeeds as often as the item's reliability allows.
                target = item["safety_stock_qty"] * loc_scale
                gap = consumed + target - on_hand
                if gap > 0 and rng.random() < item["_supply_reliability"]:
                    receipt = max(item["min_order_qty"],
                                  int(gap * rng.uniform(0.85, 1.25)))
                else:
                    receipt = 0

                source = "MAKE" if loc_idx == 1 else rng.choice(["BUY", "TRANSFER"])
                supply_rows.append({
                    "item_id": item["item_id"],
                    "location_id": loc_idx,
                    "week_start": week.isoformat(),
                    "planned_receipt_qty": receipt,
                    "planned_order_qty": receipt if rng.random() < 0.8 else 0,
                    "source_type": source,
                })

                opening = on_hand
                projected = opening + receipt - consumed

                position_rows.append({
                    "item_id": item["item_id"],
                    "location_id": loc_idx,
                    "week_start": week.isoformat(),
                    "opening_on_hand_qty": opening,
                    "projected_available_qty": projected,
                })

                # Exceptions are DERIVED from the position, not invented.
                # This matters: it means your SQL can reproduce them, which
                # is exactly the kind of cross-check an eval needs.
                ss = item["safety_stock_qty"] * loc_scale
                if projected < 0:
                    exception_rows.append({
                        "item_id": item["item_id"], "location_id": loc_idx,
                        "week_start": week.isoformat(),
                        "exception_type": "SHORTAGE",
                        "severity": "HIGH" if projected < -ss else "MEDIUM",
                        "quantity_impact": abs(projected),
                        "message": f"Projected shortage of {abs(projected)} units",
                    })
                elif projected < ss:
                    exception_rows.append({
                        "item_id": item["item_id"], "location_id": loc_idx,
                        "week_start": week.isoformat(),
                        "exception_type": "BELOW_SAFETY_STOCK",
                        "severity": "MEDIUM" if projected < ss * 0.5 else "LOW",
                        "quantity_impact": int(ss - projected),
                        "message": f"Projected below safety stock by {int(ss - projected)} units",
                    })
                elif ss > 0 and projected > ss * 6 and projected - ss * 6 > 50:
                    exception_rows.append({
                        "item_id": item["item_id"], "location_id": loc_idx,
                        "week_start": week.isoformat(),
                        "exception_type": "EXCESS",
                        "severity": "LOW",
                        "quantity_impact": int(projected - ss * 6),
                        "message": f"Projected excess of {int(projected - ss * 6)} units",
                    })

                if receipt == 0 and consumed > 0 and projected < 0:
                    exception_rows.append({
                        "item_id": item["item_id"], "location_id": loc_idx,
                        "week_start": week.isoformat(),
                        "exception_type": "NO_SUPPLY",
                        "severity": "HIGH",
                        "quantity_impact": consumed,
                        "message": "Demand with no planned supply",
                    })

                on_hand = max(0, projected)

    return items, forecast_rows, actual_rows, supply_rows, position_rows, exception_rows


# ----------------------------------------------------------------- output

def write_csv(path: Path, rows, fieldnames):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in fieldnames})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    items, fcst, actual, supply, position, exceptions = generate(args.seed)

    write_csv(OUT_DIR / "locations.csv",
              [{"location_code": c, "location_name": n, "region": r, "location_type": t}
               for c, n, r, t in LOCATIONS],
              ["location_code", "location_name", "region", "location_type"])

    write_csv(OUT_DIR / "items.csv", items,
              ["item_id", "item_number", "description", "product_family", "abc_class",
               "unit_cost", "lead_time_days", "safety_stock_qty", "min_order_qty",
               "planner_code"])

    write_csv(OUT_DIR / "demand_forecast.csv", fcst,
              ["item_id", "location_id", "week_start", "forecast_version", "forecast_qty"])

    write_csv(OUT_DIR / "actual_demand.csv", actual,
              ["item_id", "location_id", "week_start", "actual_qty"])

    write_csv(OUT_DIR / "supply_plan.csv", supply,
              ["item_id", "location_id", "week_start", "planned_receipt_qty",
               "planned_order_qty", "source_type"])

    write_csv(OUT_DIR / "inventory_position.csv", position,
              ["item_id", "location_id", "week_start", "opening_on_hand_qty",
               "projected_available_qty"])

    write_csv(OUT_DIR / "plan_exceptions.csv", exceptions,
              ["item_id", "location_id", "week_start", "exception_type", "severity",
               "quantity_impact", "message"])

    print(f"items                {len(items):>8,}")
    print(f"demand_forecast      {len(fcst):>8,}")
    print(f"actual_demand        {len(actual):>8,}")
    print(f"supply_plan          {len(supply):>8,}")
    print(f"inventory_position   {len(position):>8,}")
    print(f"plan_exceptions      {len(exceptions):>8,}")
    print(f"\nCSVs written to {OUT_DIR}")


if __name__ == "__main__":
    main()
