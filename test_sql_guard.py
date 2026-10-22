import pytest

from sql_guard import UnsafeSQL, validate_sql


@pytest.mark.parametrize("sql", [
    "SELECT * FROM items LIMIT 5",
    "select item_number from items where abc_class = 'A' order by lead_time_days desc;",
    "WITH x AS (SELECT item_id FROM items) SELECT * FROM x",
    "SELECT item_id, SUM(forecast_qty) OVER (PARTITION BY item_id ORDER BY week_start) FROM demand_forecast",
    "SELECT EXTRACT(epoch FROM week_start) FROM inventory_position LIMIT 3",
    "SELECT date_trunc('month', week_start) AS m, COUNT(*) FROM plan_exceptions GROUP BY 1",
    "SELECT * FROM plan_exceptions WHERE message = 'drop; table -- not real'",
    "SELECT * FROM plan_exceptions WHERE exception_type = 'SHORTAGE' LIMIT 10;;",
])
def test_allows_normal_read_queries(sql):
    assert validate_sql(sql)


@pytest.mark.parametrize("sql", [
    "",
    "   ",
    "DROP TABLE items",
    "DELETE FROM items",
    "UPDATE items SET unit_cost = 0",
    "INSERT INTO items VALUES (1)",
    "SELECT 1; DROP TABLE items",
    "SELECT * FROM items -- sneaky",
    "SELECT /* hi */ * FROM items",
    "SELECT pg_sleep(10)",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT * INTO new_table FROM items",
    "WITH d AS (DELETE FROM items RETURNING *) SELECT * FROM d",
    "CREATE TABLE x (a int)",
    "GRANT ALL ON items TO public",
    "COPY items TO '/tmp/x'",
    "SET ROLE neondb_owner",
    "SELECT set_config('x', 'y', false)",
    "EXPLAIN SELECT * FROM items",
    "x" * 5000,
])
def test_blocks_everything_else(sql):
    with pytest.raises(UnsafeSQL):
        validate_sql(sql)


def test_trailing_semicolons_are_stripped():
    assert validate_sql("SELECT 1;;;") == "SELECT 1"
