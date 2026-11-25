-- Views (design spec section 5.4). Safe to re-run.

CREATE OR REPLACE VIEW v_dim_origin_airport AS
SELECT airport_code AS origin_code,
       airport_name AS origin_airport_name,
       city         AS origin_city,
       state_code   AS origin_state_code,
       state_name   AS origin_state_name,
       timezone     AS origin_timezone
FROM dim_airport;

CREATE OR REPLACE VIEW v_dim_dest_airport AS
SELECT airport_code AS dest_code,
       airport_name AS dest_airport_name,
       city         AS dest_city,
       state_code   AS dest_state_code,
       state_name   AS dest_state_name,
       timezone     AS dest_timezone
FROM dim_airport;

-- Fact table joined to every dimension with readable names.
CREATE OR REPLACE VIEW v_flights AS
SELECT f.flight_id,
       d.full_date, d.`year`, d.`quarter`, d.`month`, d.month_name, d.`year_month`,
       d.day_of_week, d.weekday_name, d.is_weekend,
       f.carrier_code, c.carrier_name,
       f.flight_number,
       f.origin_code, o.airport_name AS origin_airport_name, o.city AS origin_city,
       o.state_code AS origin_state_code, o.timezone AS origin_timezone,
       f.dest_code, a.airport_name AS dest_airport_name, a.city AS dest_city,
       a.state_code AS dest_state_code, a.timezone AS dest_timezone,
       r.route_label, r.distance_group, r.distance_group_label,
       f.aircraft_id, ac.tail_number,
       f.dep_time_block, tb.day_part,
       s.status_name, s.sort_order AS status_sort_order,
       f.cancellation_code, cx.reason AS cancellation_reason,
       f.is_cancelled, f.is_diverted,
       f.crs_dep_time, f.dep_time, f.crs_arr_time, f.arr_time,
       f.dep_hour, f.arr_hour,
       f.sched_dep_utc, f.sched_arr_utc, f.actual_dep_utc, f.actual_arr_utc,
       f.dep_delay, f.arr_delay, f.dep_del15, f.arr_del15,
       f.taxi_out, f.taxi_in, f.crs_elapsed_time, f.actual_elapsed_time, f.air_time,
       f.distance,
       f.carrier_delay, f.weather_delay, f.nas_delay, f.security_delay, f.late_aircraft_delay
FROM fact_flights f
JOIN dim_date d ON d.date_key = f.date_key
JOIN dim_carrier c ON c.carrier_code = f.carrier_code
JOIN dim_airport o ON o.airport_code = f.origin_code
JOIN dim_airport a ON a.airport_code = f.dest_code
JOIN dim_route r ON r.route_id = f.route_id
JOIN dim_time_block tb ON tb.block_code = f.dep_time_block
JOIN dim_status s ON s.status_id = f.status_id
LEFT JOIN dim_aircraft ac ON ac.aircraft_id = f.aircraft_id
LEFT JOIN dim_cancellation cx ON cx.cancellation_code = f.cancellation_code;

-- One row per completed (not cancelled, not diverted) flight.
-- Features are known before departure; no actual times or dep_delay (no leakage).
-- prev_leg_arr_delay is the same aircraft's previous leg, computed over ALL flights
-- (the window runs before the completed-flight filter). NULL when the tail is unknown.
-- Ties on sched_dep_utc are broken by flight_id. Target: arr_del15.
CREATE OR REPLACE VIEW v_ml_features AS
SELECT x.flight_id,
       x.full_date, x.`year`, x.`month`, x.day_of_week, x.is_weekend,
       x.dep_hour, x.day_part,
       x.carrier_code, x.origin_code, x.dest_code, x.route_id, x.distance,
       x.prev_leg_arr_delay,
       x.arr_del15
FROM (
    SELECT f.flight_id,
           d.full_date, d.`year`, d.`month`, d.day_of_week, d.is_weekend,
           f.dep_hour, tb.day_part,
           f.carrier_code, f.origin_code, f.dest_code, f.route_id, f.distance,
           f.is_cancelled, f.is_diverted,
           CASE WHEN f.aircraft_id IS NULL THEN NULL
                ELSE LAG(f.arr_delay) OVER (PARTITION BY f.aircraft_id
                                            ORDER BY f.sched_dep_utc, f.flight_id)
           END AS prev_leg_arr_delay,
           f.arr_del15
    FROM fact_flights f
    JOIN dim_date d ON d.date_key = f.date_key
    JOIN dim_time_block tb ON tb.block_code = f.dep_time_block
) x
WHERE x.is_cancelled = 0 AND x.is_diverted = 0;
