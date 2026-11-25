import pandas as pd
import pytest

from conftest import q
from dimensions import build_dim_airport
from load_mysql import (insert_dim, load_dimensions, load_month, main,
                        to_fact_frame, verify, write_mysql_csv)
from lookups import parse_airport_description, read_lookup


def test_load_month_counts(test_db, tiny_month):
    rid, aid = load_dimensions(test_db, tiny_month.parent)
    assert load_month(test_db, tiny_month, rid, aid) == 6


def test_load_month_twice_no_duplicates(test_db, tiny_month):
    rid, aid = load_dimensions(test_db, tiny_month.parent)
    load_month(test_db, tiny_month, rid, aid)
    load_month(test_db, tiny_month, rid, aid)
    assert q(test_db, "SELECT COUNT(*) FROM fact_flights")[0][0] == 6


def test_nulls_load_as_null(test_db, tiny_month):
    rid, aid = load_dimensions(test_db, tiny_month.parent)
    load_month(test_db, tiny_month, rid, aid)
    rows = q(test_db, "SELECT arr_delay, carrier_delay, actual_arr_utc, aircraft_id "
                      "FROM fact_flights WHERE is_cancelled=1")
    assert rows and all(v is None for v in rows[0][:3])
    assert q(test_db, "SELECT COUNT(*) FROM fact_flights WHERE aircraft_id IS NULL")[0][0] == 1


def test_airport_name_roundtrip_accents(test_db):
    lk = read_lookup("L_AIRPORT")
    expected = lk[lk.Description.str.contains("[À-ÿ]")].iloc[0]
    insert_dim(test_db, "dim_airport",
               build_dim_airport([expected.Code], {expected.Code: "UTC"}))
    got = q(test_db, "SELECT airport_name FROM dim_airport WHERE airport_code=%s",
            expected.Code)[0][0]
    assert got == parse_airport_description(expected.Description)[2]


def test_cancelled_after_pushback_keeps_dep(test_db, tiny_month):
    rid, aid = load_dimensions(test_db, tiny_month.parent)
    load_month(test_db, tiny_month, rid, aid)
    row = q(test_db, "SELECT actual_dep_utc IS NOT NULL, dep_del15 "
                     "FROM fact_flights WHERE is_cancelled=1")[0]
    assert row[0] == 1 and row[1] == 0


def test_to_fact_frame_unknown_route_raises(tiny_month):
    df = pd.read_parquet(tiny_month)
    with pytest.raises(ValueError, match="ORD.*LAX"):
        to_fact_frame(df, {}, {})


def test_to_fact_frame_unknown_tail_raises(tiny_month):
    df = pd.read_parquet(tiny_month)
    routes = {(o, d): i for i, (o, d) in enumerate(zip(df.Origin, df.Dest), 1)}
    with pytest.raises(ValueError, match="N123AA"):
        to_fact_frame(df, routes, {})


def test_csv_null_unquoted(tmp_path):
    df = pd.DataFrame({"a": pd.array([1, None], dtype="Int64"),
                       "b": ["x", None],
                       "c": pd.to_datetime(["2024-01-01 05:06:07", None])})
    p = tmp_path / "t.csv"
    write_mysql_csv(df, p)
    assert p.read_bytes() == b"1,x,2024-01-01 05:06:07\n\\N,\\N,\\N\n"


def test_verify_and_main(tiny_month, tmp_path):
    import db
    report = tmp_path / "report.csv"
    pd.DataFrame({"File": ["bts_flights_2024_01.csv"], "Rows_Clean": [6],
                  "Cancelled": [1], "Diverted": [1], "Delayed_15": [1]}).to_csv(report, index=False)
    out = tmp_path / "ver.csv"
    try:
        main(["--database", "airline_ops_test", "--months", "2024_01",
              "--flights-dir", str(tiny_month.parent), "--report", str(report),
              "--output", str(out)])
    except Exception as exc:
        if "Can't connect" in str(exc):
            pytest.skip("MySQL not available")
        raise
    assert out.exists()
    conn = db.connect("airline_ops_test")
    try:
        bad = tmp_path / "bad.csv"
        pd.DataFrame({"File": ["bts_flights_2024_01.csv"], "Rows_Clean": [7],
                      "Cancelled": [1], "Diverted": [1], "Delayed_15": [1]}).to_csv(bad, index=False)
        with pytest.raises(AssertionError):
            verify(conn, bad)
    finally:
        conn.close()
