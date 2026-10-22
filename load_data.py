"""
Load the generated CSVs into Postgres.

Creates the schema and loads every table. Safe to re-run: it drops and
recreates the tables each time.

Setup:
    pip install psycopg2-binary
    set DATABASE_URL to your Neon connection string

Usage:
    python load_data.py
    python load_data.py --url "postgresql://..."     # or pass it directly
"""

import argparse
import csv
import os
import sys
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    sys.exit("psycopg2 is not installed. Run:  pip install psycopg2-binary")

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SCHEMA = ROOT / "sql" / "01_schema.sql"

# table name -> columns, in the order they must be inserted.
# Order of this list matters: parents before children, for foreign keys.
TABLES = [
    ("locations", ["location_code", "location_name", "region", "location_type"]),
    ("items", ["item_id", "item_number", "description", "product_family",
               "abc_class", "unit_cost", "lead_time_days", "safety_stock_qty",
               "min_order_qty", "planner_code"]),
    ("demand_forecast", ["item_id", "location_id", "week_start",
                         "forecast_version", "forecast_qty"]),
    ("actual_demand", ["item_id", "location_id", "week_start", "actual_qty"]),
    ("supply_plan", ["item_id", "location_id", "week_start",
                     "planned_receipt_qty", "planned_order_qty", "source_type"]),
    ("inventory_position", ["item_id", "location_id", "week_start",
                            "opening_on_hand_qty", "projected_available_qty"]),
    ("plan_exceptions", ["item_id", "location_id", "week_start", "exception_type",
                         "severity", "quantity_impact", "message"]),
]


def read_rows(table, columns):
    path = DATA / f"{table}.csv"
    if not path.exists():
        sys.exit(f"Missing {path}. Run generate_data.py first.")
    with path.open(newline="") as f:
        return [tuple(row[c] for c in columns) for row in csv.DictReader(f)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    if not args.url:
        sys.exit(
            "No connection string.\n"
            "  PowerShell:  $env:DATABASE_URL=\"postgresql://...\"\n"
            "  or:          py load_data.py --url \"postgresql://...\""
        )

    print("Connecting...")
    conn = psycopg2.connect(args.url)
    conn.autocommit = False

    with conn, conn.cursor() as cur:
        print("Creating schema...")
        cur.execute(SCHEMA.read_text())

        for table, columns in TABLES:
            rows = read_rows(table, columns)
            cols = ", ".join(columns)
            # execute_values batches the insert into a few round trips
            # instead of one per row, which matters over a network.
            execute_values(
                cur,
                f"INSERT INTO {table} ({cols}) VALUES %s",
                rows,
                page_size=1000,
            )
            print(f"  {table:<22} {len(rows):>8,} rows")

        # items.csv carries explicit ids, so the SERIAL sequences are behind.
        # Without this, the first INSERT you write by hand collides.
        cur.execute("SELECT setval('items_item_id_seq', (SELECT MAX(item_id) FROM items))")
        cur.execute("SELECT setval('locations_location_id_seq', (SELECT MAX(location_id) FROM locations))")

    print("\nVerifying...")
    with conn, conn.cursor() as cur:
        for table, _ in TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"  {table:<22} {cur.fetchone()[0]:>8,}")

    conn.close()
    print("\nDone. Your database is loaded.")


if __name__ == "__main__":
    main()
