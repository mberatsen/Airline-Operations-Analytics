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
