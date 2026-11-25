-- Sanity checks for the airline_ops star schema.
-- Run: mysql -h127.0.0.1 -uroot airline_ops < sql/checks/sanity_checks.sql
-- The expected result is stated in the comment above each query.

-- Expected: 0 (every flight with a scheduled elapsed time arrives after it departs)
SELECT 'arrival_not_after_departure' AS check_name, COUNT(*) AS result
FROM fact_flights WHERE sched_arr_utc <= sched_dep_utc AND crs_elapsed_time > 0;

-- Expected: 20 (flights whose sched_arr_utc comes from the CRSArrTime fallback because
-- the scheduled elapsed time is missing or not positive).
-- One of them, YX 5625 MKE->LGA 2026-06-06, is zero-length in the source data: BTS's own
-- ArrDelay is measured from that schedule, so utc.py is correct to leave it as is.
SELECT 'crs_elapsed_missing_or_not_positive' AS check_name, COUNT(*) AS result
FROM fact_flights WHERE crs_elapsed_time IS NULL OR crs_elapsed_time <= 0;

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

-- Expected: 11588 (flights cancelled after pushback keep their departure time)
SELECT 'cancelled_with_departure' AS check_name, COUNT(*) AS result
FROM fact_flights WHERE is_cancelled = 1 AND actual_dep_utc IS NOT NULL;

-- Expected: 0 (completed flights always have a delay-cause value, 0 when not applicable)
SELECT 'completed_with_null_delay_cause' AS check_name, COUNT(*) AS result
FROM fact_flights WHERE is_cancelled = 0 AND is_diverted = 0 AND carrier_delay IS NULL;

-- Expected: 0 (cancelled or diverted flights have NULL delay causes)
SELECT 'cancelled_or_diverted_with_delay_cause' AS check_name, COUNT(*) AS result
FROM fact_flights WHERE (is_cancelled = 1 OR is_diverted = 1) AND carrier_delay IS NOT NULL;
