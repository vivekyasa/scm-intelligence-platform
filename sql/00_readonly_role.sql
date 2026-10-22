-- Run once in the Neon SQL Editor as the owner, before loading data.
-- Replace the password with your own long random one.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'planner_ro') THEN
        CREATE ROLE planner_ro WITH LOGIN PASSWORD 'change-me-to-a-long-random-password';
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO planner_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO planner_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO planner_ro;
ALTER ROLE planner_ro SET statement_timeout = '5s';
