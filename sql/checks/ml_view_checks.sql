-- Optional checks on v_ml_features. Run separately from sanity_checks.sql.
-- These need innodb_buffer_pool_size of about 1 GB. On the default 128 MB they can run
-- for a very long time and wedge the server.
-- Run: mysql -h127.0.0.1 -uroot airline_ops < sql/checks/ml_view_checks.sql

-- Expected: 18453597 (18,809,411 flights - 303,116 cancelled - 52,698 diverted)
SELECT 'v_ml_features_rows' AS check_name, COUNT(*) AS result FROM v_ml_features;

-- Expected: 0 (flights without a tail number get no previous leg)
SELECT 'no_tail_but_prev_leg' AS check_name, COUNT(*) AS result
FROM v_ml_features m
JOIN fact_flights f ON f.flight_id = m.flight_id
WHERE f.aircraft_id IS NULL AND m.prev_leg_arr_delay IS NOT NULL;
