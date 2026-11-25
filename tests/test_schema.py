from conftest import q
from db import apply_schema


def test_schema_creates_all_tables(test_db):
    tables = {r[0] for r in q(test_db, "SHOW FULL TABLES WHERE Table_type='BASE TABLE'")}
    assert tables == {"fact_flights", "dim_date", "dim_carrier", "dim_carrier_history",
                      "dim_airport", "dim_route", "dim_aircraft", "dim_time_block",
                      "dim_cancellation", "dim_status"}
    views = {r[0] for r in q(test_db, "SHOW FULL TABLES WHERE Table_type='VIEW'")}
    assert views == {"v_dim_origin_airport", "v_dim_dest_airport", "v_flights",
                     "v_ml_features"}


def test_schema_is_rerunnable(test_db):
    apply_schema(test_db)
    apply_schema(test_db)


def _seed(c):
    for sql in [
        "INSERT INTO dim_date (date_key,full_date,`year`,`quarter`,quarter_label,`month`,month_name,month_short,`year_month`,day_of_month,day_of_week,weekday_name,is_weekend,iso_week) VALUES (20240101,'2024-01-01',2024,1,'Q1',1,'January','Jan','2024-01',1,1,'Monday',0,1)",
        "INSERT INTO dim_carrier VALUES ('AA','American')",
        "INSERT INTO dim_airport VALUES ('ORD','O','Chicago','IL','Illinois','America/Chicago'),('LAX','L','LA','CA','California','America/Los_Angeles')",
        "INSERT INTO dim_route VALUES (1,'ORD','LAX','ORD-LAX',1744,7,'1500-1749 Miles')",
        "INSERT INTO dim_aircraft VALUES (1,'N1','AA','2024-01-01','2024-01-01',3)",
        "INSERT INTO dim_time_block VALUES ('0900-0959','x',9,9,'Morning')",
        "INSERT INTO dim_status VALUES (1,'On Time',1)",
    ]:
        with c.cursor() as cur:
            cur.execute(sql)
    # (flight_number, aircraft_id, arr_delay); all share one sched_dep_utc
    rows = [(1, 1, 10), (2, 1, 20), (3, None, 30), (4, None, 40)]
    for fn, ac, ad in rows:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO fact_flights (date_key,carrier_code,flight_number,origin_code,dest_code,"
                "route_id,aircraft_id,dep_time_block,status_id,is_cancelled,is_diverted,crs_dep_time,"
                "dep_hour,arr_hour,sched_dep_utc,sched_arr_utc,arr_delay,arr_del15,distance) VALUES "
                "(20240101,'AA',%s,'ORD','LAX',1,%s,'0900-0959',1,0,0,900,9,11,"
                "'2024-01-01 15:00:00','2024-01-01 19:00:00',%s,0,1744)", (fn, ac, ad))
    c.commit()


def test_ml_prev_leg_null_without_tail_and_tie_break(test_db):
    _seed(test_db)
    got = dict(q(test_db, "SELECT flight_id, prev_leg_arr_delay FROM v_ml_features"))
    ids = [r[0] for r in q(test_db, "SELECT flight_id FROM fact_flights ORDER BY flight_number")]
    assert got[ids[0]] is None      # first leg of the tail
    assert got[ids[1]] == 10        # tie on time broken by flight_id
    assert got[ids[2]] is None      # no tail: not borrowed from other flights
    assert got[ids[3]] is None


def test_ml_prev_leg_window_runs_before_completed_filter(test_db):
    """A completed, B cancelled, C completed (same aircraft): C's previous leg is B."""
    _seed(test_db)
    with test_db.cursor() as cur:
        cur.execute("DELETE FROM fact_flights")
        for fn, dep, cancelled, ad in [(10, "15:00:00", 0, 7), (11, "17:00:00", 1, None),
                                       (12, "19:00:00", 0, 3)]:
            cur.execute(
                "INSERT INTO fact_flights (date_key,carrier_code,flight_number,origin_code,dest_code,"
                "route_id,aircraft_id,dep_time_block,status_id,is_cancelled,is_diverted,crs_dep_time,"
                "dep_hour,arr_hour,sched_dep_utc,sched_arr_utc,arr_delay,arr_del15,distance) VALUES "
                "(20240101,'AA',%s,'ORD','LAX',1,1,'0900-0959',1,%s,0,900,9,11,"
                "%s,%s,%s,0,1744)",
                (fn, cancelled, "2024-01-01 " + dep, "2024-01-01 " + dep, ad))
    test_db.commit()
    ids = {r[0]: r[1] for r in q(test_db, "SELECT flight_number, flight_id FROM fact_flights")}
    got = dict(q(test_db, "SELECT flight_id, prev_leg_arr_delay FROM v_ml_features"))
    assert ids[11] not in got                 # cancelled leg is filtered out
    assert got[ids[10]] is None               # A: first leg of the tail
    assert got[ids[12]] is None               # C: previous leg is B, whose arr_delay is NULL
