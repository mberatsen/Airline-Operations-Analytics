-- Sanity checks for the airline_ops star schema.
-- Run: mysql -h127.0.0.1 -uroot airline_ops < sql/checks/sanity_checks.sql
-- The expected result is stated in the comment above each query.

-- Expected: 0 (every flight arrives after it departs)
SELECT 'arrival_not_after_departure' AS check_name, COUNT(*) AS result
FROM fact_flights WHERE sched_arr_utc <= sched_dep_utc;

-- Expected: DL = 0.189, AA = 0.294 (January 2024 share of arrivals delayed 15+ min, matches the pandas result)
SELECT carrier_code, ROUND(AVG(arr_del15), 3) AS arr_delayed_share
FROM v_flights
WHERE `year_month` = '2024-01' AND carrier_code IN ('DL', 'AA')
GROUP BY carrier_code ORDER BY carrier_code;

-- Expected: 365
SELECT 'dim_airport' AS check_name, COUNT(*) AS result FROM dim_airport;
-- Expected: 7679
SELECT 'dim_route' AS check_name, COUNT(*) AS result FROM dim_route;
-- Expected: 15
SELECT 'dim_carrier' AS check_name, COUNT(*) AS result FROM dim_carrier;
-- Expected: 6789
SELECT 'dim_aircraft' AS check_name, COUNT(*) AS result FROM dim_aircraft;

-- WARNING: the two v_ml_features checks below need innodb_buffer_pool_size of about 1 GB.
-- On the default 128 MB they can run for a very long time and wedge the server.

-- Expected: 18453597 (18,809,411 flights - 303,116 cancelled - 52,698 diverted)
SELECT 'v_ml_features_rows' AS check_name, COUNT(*) AS result FROM v_ml_features;

-- Expected: 0 (flights without a tail number get no previous leg)
SELECT 'no_tail_but_prev_leg' AS check_name, COUNT(*) AS result
FROM v_ml_features m
JOIN fact_flights f ON f.flight_id = m.flight_id
WHERE f.aircraft_id IS NULL AND m.prev_leg_arr_delay IS NOT NULL;

-- Expected: 11588 (flights cancelled after pushback keep their departure time)
SELECT 'cancelled_with_departure' AS check_name, COUNT(*) AS result
FROM fact_flights WHERE is_cancelled = 1 AND actual_dep_utc IS NOT NULL;

-- Expected: 0 (completed flights always have a delay-cause value, 0 when not applicable)
SELECT 'completed_with_null_delay_cause' AS check_name, COUNT(*) AS result
FROM fact_flights WHERE is_cancelled = 0 AND is_diverted = 0 AND carrier_delay IS NULL;

-- Expected: 0 (cancelled or diverted flights have NULL delay causes)
SELECT 'cancelled_or_diverted_with_delay_cause' AS check_name, COUNT(*) AS result
FROM fact_flights WHERE (is_cancelled = 1 OR is_diverted = 1) AND carrier_delay IS NOT NULL;
