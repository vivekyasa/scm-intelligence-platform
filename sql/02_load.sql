-- Load the generated CSVs. Run from psql in the project root:
--     psql "$DATABASE_URL" -f sql/01_schema.sql
--     psql "$DATABASE_URL" -f sql/02_load.sql
--
-- \copy runs client side, so it reads files from YOUR machine, not the server.
-- This is why \copy works against Neon or Supabase and plain COPY does not.

\copy locations (location_code, location_name, region, location_type) FROM 'data/locations.csv' CSV HEADER

\copy items (item_id, item_number, description, product_family, abc_class, unit_cost, lead_time_days, safety_stock_qty, min_order_qty, planner_code) FROM 'data/items.csv' CSV HEADER

\copy demand_forecast (item_id, location_id, week_start, forecast_version, forecast_qty) FROM 'data/demand_forecast.csv' CSV HEADER

\copy actual_demand (item_id, location_id, week_start, actual_qty) FROM 'data/actual_demand.csv' CSV HEADER

\copy supply_plan (item_id, location_id, week_start, planned_receipt_qty, planned_order_qty, source_type) FROM 'data/supply_plan.csv' CSV HEADER

\copy inventory_position (item_id, location_id, week_start, opening_on_hand_qty, projected_available_qty) FROM 'data/inventory_position.csv' CSV HEADER

\copy plan_exceptions (item_id, location_id, week_start, exception_type, severity, quantity_impact, message) FROM 'data/plan_exceptions.csv' CSV HEADER

-- items.csv supplies explicit item_id values, so the SERIAL sequence is now
-- behind. Fix it or your first INSERT will collide.
SELECT setval('items_item_id_seq', (SELECT MAX(item_id) FROM items));
SELECT setval('locations_location_id_seq', (SELECT MAX(location_id) FROM locations));

-- Sanity check
SELECT 'items' AS table_name, COUNT(*) FROM items
UNION ALL SELECT 'demand_forecast', COUNT(*) FROM demand_forecast
UNION ALL SELECT 'actual_demand', COUNT(*) FROM actual_demand
UNION ALL SELECT 'supply_plan', COUNT(*) FROM supply_plan
UNION ALL SELECT 'inventory_position', COUNT(*) FROM inventory_position
UNION ALL SELECT 'plan_exceptions', COUNT(*) FROM plan_exceptions;
