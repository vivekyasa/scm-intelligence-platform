-- Supply Chain Planning Intelligence Platform
-- Core planning schema. Plain Postgres, no extensions required yet.
-- pgvector tables come in week 3, in a separate file.

DROP TABLE IF EXISTS plan_exceptions CASCADE;
DROP TABLE IF EXISTS inventory_position CASCADE;
DROP TABLE IF EXISTS supply_plan CASCADE;
DROP TABLE IF EXISTS actual_demand CASCADE;
DROP TABLE IF EXISTS demand_forecast CASCADE;
DROP TABLE IF EXISTS items CASCADE;
DROP TABLE IF EXISTS locations CASCADE;


-- ---------------------------------------------------------------- master data

CREATE TABLE locations (
    location_id     SERIAL PRIMARY KEY,
    location_code   TEXT        NOT NULL UNIQUE,
    location_name   TEXT        NOT NULL,
    region          TEXT        NOT NULL,
    location_type   TEXT        NOT NULL   -- PLANT | DC | FORWARD_STOCK
);

CREATE TABLE items (
    item_id         SERIAL PRIMARY KEY,
    item_number     TEXT        NOT NULL UNIQUE,
    description     TEXT        NOT NULL,
    product_family  TEXT        NOT NULL,
    abc_class       CHAR(1)     NOT NULL,  -- A | B | C
    unit_cost       NUMERIC(12,2) NOT NULL,
    lead_time_days  INTEGER     NOT NULL,
    safety_stock_qty INTEGER    NOT NULL,
    min_order_qty   INTEGER     NOT NULL,
    planner_code    TEXT        NOT NULL
);

CREATE INDEX idx_items_family ON items (product_family);
CREATE INDEX idx_items_abc    ON items (abc_class);


-- ---------------------------------------------------------------- demand

-- What the plan said would happen. Versioned so you can compare
-- successive planning cycles, which is where the interesting SQL lives.
CREATE TABLE demand_forecast (
    item_id         INTEGER NOT NULL REFERENCES items(item_id),
    location_id     INTEGER NOT NULL REFERENCES locations(location_id),
    week_start      DATE    NOT NULL,
    forecast_version TEXT   NOT NULL,     -- e.g. 2026-W40
    forecast_qty    INTEGER NOT NULL,
    PRIMARY KEY (item_id, location_id, week_start, forecast_version)
);

CREATE INDEX idx_fcst_week ON demand_forecast (week_start);

-- What actually happened. Only populated for weeks in the past.
CREATE TABLE actual_demand (
    item_id         INTEGER NOT NULL REFERENCES items(item_id),
    location_id     INTEGER NOT NULL REFERENCES locations(location_id),
    week_start      DATE    NOT NULL,
    actual_qty      INTEGER NOT NULL,
    PRIMARY KEY (item_id, location_id, week_start)
);


-- ---------------------------------------------------------------- supply

CREATE TABLE supply_plan (
    item_id             INTEGER NOT NULL REFERENCES items(item_id),
    location_id         INTEGER NOT NULL REFERENCES locations(location_id),
    week_start          DATE    NOT NULL,
    planned_receipt_qty INTEGER NOT NULL,   -- arriving this week
    planned_order_qty   INTEGER NOT NULL,   -- released this week
    source_type         TEXT    NOT NULL,   -- BUY | MAKE | TRANSFER
    PRIMARY KEY (item_id, location_id, week_start)
);


-- ---------------------------------------------------------------- position

-- The projected picture: what the planner actually looks at.
CREATE TABLE inventory_position (
    item_id             INTEGER NOT NULL REFERENCES items(item_id),
    location_id         INTEGER NOT NULL REFERENCES locations(location_id),
    week_start          DATE    NOT NULL,
    opening_on_hand_qty INTEGER NOT NULL,
    projected_available_qty INTEGER NOT NULL,  -- can go negative: that is a shortage
    PRIMARY KEY (item_id, location_id, week_start)
);

CREATE INDEX idx_invpos_week ON inventory_position (week_start);


-- ---------------------------------------------------------------- exceptions

CREATE TABLE plan_exceptions (
    exception_id    SERIAL PRIMARY KEY,
    item_id         INTEGER NOT NULL REFERENCES items(item_id),
    location_id     INTEGER NOT NULL REFERENCES locations(location_id),
    week_start      DATE    NOT NULL,
    exception_type  TEXT    NOT NULL,   -- SHORTAGE | BELOW_SAFETY_STOCK |
                                        -- EXCESS | LATE_ORDER | NO_SUPPLY
    severity        TEXT    NOT NULL,   -- HIGH | MEDIUM | LOW
    quantity_impact INTEGER NOT NULL,
    message         TEXT    NOT NULL
);

CREATE INDEX idx_exc_type ON plan_exceptions (exception_type);
CREATE INDEX idx_exc_week ON plan_exceptions (week_start);
