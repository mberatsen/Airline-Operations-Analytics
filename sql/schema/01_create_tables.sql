-- Star schema for airline operations analytics (design spec sections 5.2 and 5.3).
-- Runs against whatever database the connection is on: no CREATE DATABASE, no USE.
-- Every table: InnoDB, utf8mb4 / utf8mb4_0900_ai_ci.

-- Drop in dependency order: the fact table first, then dimensions that other tables reference.
DROP TABLE IF EXISTS fact_flights;
DROP TABLE IF EXISTS dim_route;
DROP TABLE IF EXISTS dim_aircraft;
DROP TABLE IF EXISTS dim_carrier_history;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_carrier;
DROP TABLE IF EXISTS dim_airport;
DROP TABLE IF EXISTS dim_time_block;
DROP TABLE IF EXISTS dim_cancellation;
DROP TABLE IF EXISTS dim_status;

CREATE TABLE dim_date (
    date_key       INT NOT NULL COMMENT 'YYYYMMDD',
    full_date      DATE NOT NULL,
    `year`         SMALLINT NOT NULL,
    `quarter`      TINYINT NOT NULL,
    quarter_label  CHAR(2) NOT NULL COMMENT 'Q1 to Q4',
    `month`        TINYINT NOT NULL,
    month_name     VARCHAR(9) NOT NULL,
    month_short    CHAR(3) NOT NULL,
    `year_month`   CHAR(7) NOT NULL COMMENT 'e.g. 2024-01',
    day_of_month   TINYINT NOT NULL,
    day_of_week    TINYINT NOT NULL COMMENT '1 = Monday, matching BTS',
    weekday_name   VARCHAR(9) NOT NULL,
    is_weekend     TINYINT(1) NOT NULL,
    iso_week       TINYINT NOT NULL,
    PRIMARY KEY (date_key),
    UNIQUE KEY uq_dim_date_full_date (full_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE dim_carrier (
    carrier_code  VARCHAR(3) NOT NULL,
    carrier_name  VARCHAR(150) NOT NULL,
    PRIMARY KEY (carrier_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE dim_carrier_history (
    carrier_code  VARCHAR(3) NOT NULL,
    carrier_name  VARCHAR(150) NOT NULL,
    start_year    SMALLINT NOT NULL,
    end_year      SMALLINT NULL,
    PRIMARY KEY (carrier_code, start_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Reference only, no foreign key';

CREATE TABLE dim_airport (
    airport_code  CHAR(3) NOT NULL,
    airport_name  VARCHAR(150) NOT NULL,
    city          VARCHAR(100) NOT NULL,
    state_code    CHAR(2) NOT NULL,
    state_name    VARCHAR(60) NOT NULL,
    timezone      VARCHAR(40) NOT NULL COMMENT 'IANA zone name, e.g. America/Chicago',
    PRIMARY KEY (airport_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE dim_route (
    route_id        INT UNSIGNED NOT NULL,
    origin_code     CHAR(3) NOT NULL,
    dest_code       CHAR(3) NOT NULL,
    route_label     VARCHAR(7) NOT NULL COMMENT 'e.g. ATL-LAX',
    distance_miles  SMALLINT UNSIGNED NOT NULL COMMENT 'latest distance recorded',
    distance_group  TINYINT UNSIGNED NOT NULL COMMENT '250-mile band number 1-11 (L_DISTANCE_GROUP_250 code)',
    distance_group_label  VARCHAR(40) NOT NULL COMMENT 'Band label from L_DISTANCE_GROUP_250',
    PRIMARY KEY (route_id),
    UNIQUE KEY uq_dim_route_pair (origin_code, dest_code),
    CONSTRAINT fk_route_origin FOREIGN KEY (origin_code) REFERENCES dim_airport (airport_code),
    CONSTRAINT fk_route_dest FOREIGN KEY (dest_code) REFERENCES dim_airport (airport_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE dim_aircraft (
    aircraft_id           INT UNSIGNED NOT NULL,
    tail_number           VARCHAR(10) NOT NULL COMMENT 'normalized: uppercase, N prefix',
    primary_carrier_code  VARCHAR(3) NOT NULL COMMENT 'carrier with the most flights on this tail',
    first_flight_date     DATE NOT NULL,
    last_flight_date      DATE NOT NULL,
    flight_count          INT UNSIGNED NOT NULL,
    PRIMARY KEY (aircraft_id),
    UNIQUE KEY uq_dim_aircraft_tail (tail_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE dim_time_block (
    block_code   CHAR(9) NOT NULL COMMENT 'e.g. 0600-0659',
    block_label  VARCHAR(30) NOT NULL,
    start_hour   TINYINT NOT NULL,
    end_hour     TINYINT NOT NULL,
    day_part     VARCHAR(9) NOT NULL COMMENT 'Night 0-5, Morning 6-11, Afternoon 12-17, Evening 18-23',
    PRIMARY KEY (block_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE dim_cancellation (
    cancellation_code  CHAR(1) NOT NULL,
    reason             VARCHAR(60) NOT NULL,
    PRIMARY KEY (cancellation_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE dim_status (
    status_id    TINYINT UNSIGNED NOT NULL,
    status_name  VARCHAR(10) NOT NULL COMMENT 'On Time, Delayed, Cancelled, Diverted',
    sort_order   TINYINT NOT NULL,
    PRIMARY KEY (status_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE fact_flights (
    flight_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    date_key             INT NOT NULL COMMENT 'YYYYMMDD of the scheduled departure, local date',
    carrier_code         VARCHAR(3) NOT NULL COMMENT 'Reporting_Airline',
    flight_number        SMALLINT UNSIGNED NULL COMMENT '1 row is blank in the source data',
    origin_code          CHAR(3) NOT NULL,
    dest_code            CHAR(3) NOT NULL,
    route_id             INT UNSIGNED NOT NULL,
    aircraft_id          INT UNSIGNED NULL COMMENT 'NULL when the tail number is missing',
    dep_time_block       CHAR(9) NOT NULL COMMENT 'e.g. 0600-0659',
    status_id            TINYINT UNSIGNED NOT NULL,
    cancellation_code    CHAR(1) NULL COMMENT 'NULL unless cancelled',
    is_cancelled         TINYINT(1) NOT NULL,
    is_diverted          TINYINT(1) NOT NULL,
    crs_dep_time         SMALLINT NULL COMMENT 'scheduled departure, local hhmm as BTS reports it (2400 = midnight)',
    dep_time             SMALLINT NULL COMMENT 'actual departure, local hhmm as BTS reports it (2400 = midnight)',
    crs_arr_time         SMALLINT NULL COMMENT 'scheduled arrival, local hhmm at the destination (2400 = midnight)',
    arr_time             SMALLINT NULL COMMENT 'actual arrival, local hhmm at the destination (2400 = midnight)',
    dep_hour             TINYINT NOT NULL COMMENT 'scheduled local departure hour 0-23',
    arr_hour             TINYINT NOT NULL COMMENT 'scheduled local arrival hour 0-23',
    sched_dep_utc        DATETIME NOT NULL COMMENT 'UTC, see design spec 6.1',
    sched_arr_utc        DATETIME NOT NULL COMMENT 'UTC, sched_dep_utc + scheduled elapsed minutes',
    actual_dep_utc       DATETIME NULL COMMENT 'NULL when dep_delay is NULL',
    actual_arr_utc       DATETIME NULL COMMENT 'NULL when arr_delay is NULL (cancelled or diverted)',
    dep_delay            SMALLINT NULL COMMENT 'minutes, negative means early. NULL when the flight never left the gate',
    arr_delay            SMALLINT NULL COMMENT 'minutes, negative means early. NULL for cancelled or diverted, so AVG skips them',
    dep_del15            TINYINT NULL COMMENT '0 or 1. NULL when the flight never departed',
    arr_del15            TINYINT NULL COMMENT '0 or 1. NULL when cancelled or diverted',
    taxi_out             SMALLINT NULL COMMENT 'minutes',
    taxi_in              SMALLINT NULL COMMENT 'minutes',
    crs_elapsed_time     SMALLINT NULL COMMENT 'minutes',
    actual_elapsed_time  SMALLINT NULL COMMENT 'minutes',
    air_time             SMALLINT NULL COMMENT 'minutes',
    distance             SMALLINT UNSIGNED NOT NULL COMMENT 'miles, as recorded on this flight',
    carrier_delay        SMALLINT NULL COMMENT 'minutes. 0 = cause did not apply on a completed flight, NULL = cancelled or diverted',
    weather_delay        SMALLINT NULL COMMENT 'minutes. 0 = cause did not apply on a completed flight, NULL = cancelled or diverted',
    nas_delay            SMALLINT NULL COMMENT 'minutes. 0 = cause did not apply on a completed flight, NULL = cancelled or diverted',
    security_delay       SMALLINT NULL COMMENT 'minutes. 0 = cause did not apply on a completed flight, NULL = cancelled or diverted',
    late_aircraft_delay  SMALLINT NULL COMMENT 'minutes. 0 = cause did not apply on a completed flight, NULL = cancelled or diverted',
    PRIMARY KEY (flight_id),
    UNIQUE KEY uq_flight_natural (date_key, carrier_code, flight_number, origin_code, dest_code, crs_dep_time),
    KEY ix_fact_origin_date (origin_code, date_key),
    KEY ix_fact_dest_date (dest_code, date_key),
    KEY ix_fact_carrier_date (carrier_code, date_key),
    KEY ix_fact_route (route_id),
    KEY ix_fact_aircraft_dep (aircraft_id, sched_dep_utc),
    CONSTRAINT fk_fact_date FOREIGN KEY (date_key) REFERENCES dim_date (date_key),
    CONSTRAINT fk_fact_carrier FOREIGN KEY (carrier_code) REFERENCES dim_carrier (carrier_code),
    CONSTRAINT fk_fact_origin FOREIGN KEY (origin_code) REFERENCES dim_airport (airport_code),
    CONSTRAINT fk_fact_dest FOREIGN KEY (dest_code) REFERENCES dim_airport (airport_code),
    CONSTRAINT fk_fact_route FOREIGN KEY (route_id) REFERENCES dim_route (route_id),
    CONSTRAINT fk_fact_aircraft FOREIGN KEY (aircraft_id) REFERENCES dim_aircraft (aircraft_id),
    CONSTRAINT fk_fact_time_block FOREIGN KEY (dep_time_block) REFERENCES dim_time_block (block_code),
    CONSTRAINT fk_fact_cancellation FOREIGN KEY (cancellation_code) REFERENCES dim_cancellation (cancellation_code),
    CONSTRAINT fk_fact_status FOREIGN KEY (status_id) REFERENCES dim_status (status_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='One row per scheduled flight. Delay NULL rule: see arr_delay';
