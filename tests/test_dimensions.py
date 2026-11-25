import pandas as pd
import pytest

from dimensions import (
    STATUS_IDS,
    build_dim_aircraft,
    build_dim_airport,
    build_dim_cancellation,
    build_dim_carrier,
    build_dim_carrier_history,
    build_dim_date,
    build_dim_route,
    build_dim_status,
    build_dim_time_block,
)


def test_dim_date_range_and_fields():
    d = build_dim_date()
    assert len(d) == 1096 and d.date_key.iloc[0] == 20240101
    r = d.set_index("date_key").loc[20240106]          # a Saturday
    assert (r.day_of_week, r.weekday_name, r.is_weekend, r.year_month) == (6, "Saturday", 1, "2024-01")


def test_dim_date_columns_and_misc():
    d = build_dim_date()
    assert list(d.columns) == [
        "date_key", "full_date", "year", "quarter", "quarter_label", "month",
        "month_name", "month_short", "year_month", "day_of_month",
        "day_of_week", "weekday_name", "is_weekend", "iso_week",
    ]
    r = d.set_index("date_key").loc[20240101]          # a Monday
    assert (r.day_of_week, r.is_weekend, r.quarter_label, r.month_name,
            r.month_short, r.iso_week) == (1, 0, "Q1", "January", "Jan", 1)
    assert d.set_index("date_key").loc[20240107].is_weekend == 1


def test_dim_carrier_names_and_missing():
    c = build_dim_carrier(["AA", "OO"])
    assert list(c.columns) == ["carrier_code", "carrier_name"]
    assert len(c) == 2 and c.carrier_name.str.len().gt(0).all()
    with pytest.raises(ValueError, match="Missing from L_UNIQUE_CARRIERS: ZZZ"):
        build_dim_carrier(["AA", "ZZZ"])


def test_dim_airport_split_and_tz():
    a = build_dim_airport(["ORD"], {"ORD": "America/Chicago"}).iloc[0]
    assert (a.city, a.state_code, a.state_name, a.timezone) == ("Chicago", "IL", "Illinois", "America/Chicago")


def test_dim_airport_columns():
    a = build_dim_airport(["ORD"], {"ORD": "America/Chicago"})
    assert list(a.columns) == ["airport_code", "airport_name", "city",
                               "state_code", "state_name", "timezone"]


def test_dim_airport_missing_code_raises():
    with pytest.raises(ValueError, match="Missing from L_AIRPORT: Q99"):
        build_dim_airport(["ORD", "Q99"], {"ORD": "America/Chicago", "Q99": "UTC"})


def test_dim_airport_missing_timezone_raises():
    with pytest.raises(ValueError, match="Missing from timezone map: ORD"):
        build_dim_airport(["ORD"], {})


def test_dim_airport_foreign_has_empty_state():
    from lookups import parse_airport_description, read_lookup
    df = read_lookup("L_AIRPORT")
    foreign = [c for c, d in zip(df.Code, df.Description)
               if parse_airport_description(d)[1] == ""][0]
    a = build_dim_airport([foreign], {foreign: "UTC"}).iloc[0]
    assert a.state_code == "" and a.state_name == ""


def test_dim_route_latest_distance():
    f = pd.DataFrame({"Origin": ["AGS","AGS"], "Dest": ["PHL","PHL"], "Distance": [583.0, 584.0],
                      "FlightDate": pd.to_datetime(["2024-04-07","2026-04-05"])})
    r = build_dim_route(f).iloc[0]
    assert (r.route_label, r.distance_miles, r.distance_group) == ("AGS-PHL", 584, 3)
    assert r.distance_group_label == "500-749 Miles"


def test_dim_route_ids_order_and_tie():
    f = pd.DataFrame({"Origin": ["LAX", "ATL", "ATL"], "Dest": ["ATL", "LAX", "LAX"],
                      "Distance": [1946.0, 1946.0, 1947.0],
                      "FlightDate": pd.to_datetime(["2024-01-01"] * 3)})
    r = build_dim_route(f)
    assert list(r.columns) == ["route_id", "origin_code", "dest_code",
                               "route_label", "distance_miles", "distance_group",
                               "distance_group_label"]
    assert list(r.route_id) == [1, 2]
    assert list(r.route_label) == ["ATL-LAX", "LAX-ATL"]
    assert r.distance_miles.iloc[0] == 1947          # tie on date -> max distance
    assert r.distance_group.iloc[0] == 8


def test_dim_aircraft_primary_carrier():
    f = pd.DataFrame({"Tail_Number": ["N1","N1","N1"], "Reporting_Airline": ["OO","OO","AA"],
                      "FlightDate": pd.to_datetime(["2024-01-01","2024-02-01","2024-03-01"])})
    a = build_dim_aircraft(f).iloc[0]
    assert (a.primary_carrier_code, a.flight_count, str(a.first_flight_date)[:10]) == ("OO", 3, "2024-01-01")


def test_dim_aircraft_columns_ids_and_null_tail():
    f = pd.DataFrame({"Tail_Number": pd.array(["N2", None, "N1"], dtype="string"),
                      "Reporting_Airline": pd.Categorical(["AA", "AA", "DL"], categories=["AA", "DL", "XX"]),
                      "FlightDate": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])})
    a = build_dim_aircraft(f)
    assert list(a.columns) == ["aircraft_id", "tail_number", "primary_carrier_code",
                               "first_flight_date", "last_flight_date", "flight_count"]
    assert list(a.tail_number) == ["N1", "N2"] and list(a.aircraft_id) == [1, 2]


def test_dim_carrier_history_years():
    h = build_dim_carrier_history()
    assert h.duplicated(["carrier_code", "start_year"]).sum() == 0
    assert h.end_year.isna().any() and h.start_year.notna().all()


def test_time_block_day_part():
    t = build_dim_time_block().set_index("block_code")
    assert t.loc["0001-0559", "day_part"] == "Night" and t.loc["1800-1859", "day_part"] == "Evening"


def test_time_block_hours_and_columns():
    t = build_dim_time_block()
    assert list(t.columns) == ["block_code", "block_label", "start_hour", "end_hour", "day_part"]
    assert len(t) == 19
    t = t.set_index("block_code")
    assert (t.loc["0001-0559", "start_hour"], t.loc["0001-0559", "end_hour"]) == (0, 5)
    assert (t.loc["2300-2359", "start_hour"], t.loc["2300-2359", "end_hour"]) == (23, 23)
    assert t.loc["0600-0659", "day_part"] == "Morning" and t.loc["1200-1259", "day_part"] == "Afternoon"


def test_cancellation_and_status():
    c = build_dim_cancellation()
    assert list(c.columns) == ["cancellation_code", "reason"] and len(c) == 4
    s = build_dim_status()
    assert list(s.columns) == ["status_id", "status_name", "sort_order"]
    assert dict(zip(s.status_name, s.status_id)) == STATUS_IDS
