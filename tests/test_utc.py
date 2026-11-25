import pandas as pd
import pytest

from utc import add_utc_columns, check_arrivals

tz = {
    "ORD": "America/Chicago",
    "LAX": "America/Los_Angeles",
    "JFK": "America/New_York",
    "LGA": "America/New_York",
    "PHX": "America/Phoenix",
}


def row(origin, dest, date, crs_dep, elapsed, crs_arr, dep_delay=0, arr_delay=0):
    return pd.DataFrame({
        "Origin": [origin],
        "Dest": [dest],
        "FlightDate": pd.to_datetime([date]),
        "CRSDepTime": [crs_dep],
        "CRSElapsedTime": [elapsed],
        "CRSArrTime": [crs_arr],
        "DepDelay": [dep_delay],
        "ArrDelay": [arr_delay],
    })


def test_simple_winter():  # ORD 08:00 CST -> 14:00Z; +270 min -> 18:30Z
    out, _ = add_utc_columns(row("ORD", "LAX", "2024-01-15", 800, 270, 1030), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-01-15 14:00")
    assert out.SchedArrUTC[0] == pd.Timestamp("2024-01-15 18:30")
    assert out.SchedDepUTC.dtype == "datetime64[ns]"


def test_overnight_crosses_date():
    out, _ = add_utc_columns(row("LAX", "JFK", "2024-01-15", 2330, 300, 730), tz)
    assert out.SchedArrUTC[0] == pd.Timestamp("2024-01-16 12:30")
    assert check_arrivals(out, tz).Match_Percent[0] == 100.0


def test_2400_is_next_midnight():
    out, _ = add_utc_columns(row("ORD", "LAX", "2024-01-15", 2400, 240, 200), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-01-16 06:00")


def test_arizona_no_dst():  # PHX 09:00 in July = MST UTC-7
    out, _ = add_utc_columns(row("PHX", "LAX", "2024-07-01", 900, 90, 1030), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-07-01 16:00")


def test_spring_forward_gap():
    out, stats = add_utc_columns(row("ORD", "LAX", "2024-03-10", 230, 240, 430), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-03-10 08:00")
    assert stats["DST_Nonexistent"] == 1


def test_fall_back_ambiguous():
    out, stats = add_utc_columns(row("ORD", "LAX", "2024-11-03", 130, 240, 330), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-11-03 06:30")
    assert stats["DST_Ambiguous"] == 1


def test_arrival_fallback_when_no_elapsed():
    out, stats = add_utc_columns(
        row("ORD", "LGA", "2024-01-15", 2200, float("nan"), 130), tz)
    assert out.SchedArrUTC[0] == pd.Timestamp("2024-01-16 06:30")
    assert bool(out.ArrivalFallback[0]) and stats["Arrival_Fallback"] == 1


def test_actuals_null_when_delay_null():
    out, _ = add_utc_columns(
        row("ORD", "LAX", "2024-01-15", 800, 270, 1030,
            dep_delay=float("nan"), arr_delay=float("nan")), tz)
    assert pd.isna(out.ActualDepUTC[0]) and pd.isna(out.ActualArrUTC[0])


def test_wrong_zone_fails_check():
    bad = dict(tz, LAX="America/Chicago")
    out, _ = add_utc_columns(row("ORD", "LAX", "2024-01-15", 800, 270, 1030), bad)
    assert check_arrivals(out, bad).Match_Percent[0] == 0.0


def test_unknown_airport_raises():
    with pytest.raises((KeyError, ValueError), match="XXX"):
        add_utc_columns(row("ORD", "XXX", "2024-01-15", 800, 270, 1030), tz)


def test_actuals_apply_delays_and_fallback_excluded_from_check():
    df = pd.concat([
        row("ORD", "LAX", "2024-01-15", 800, 270, 1030, dep_delay=10, arr_delay=-5),
        row("ORD", "LGA", "2024-01-15", 2200, float("nan"), 130),
    ], ignore_index=True)
    out, _ = add_utc_columns(df, tz)
    assert out.ActualDepUTC[0] == pd.Timestamp("2024-01-15 14:10")
    assert out.ActualArrUTC[0] == pd.Timestamp("2024-01-15 18:25")
    res = check_arrivals(out, tz)
    assert list(res.Dest) == ["LAX", "LGA"]
    assert res.Flights.tolist() == [1, 0]
    assert pd.isna(res.Match_Percent[1])


def test_real_dtypes():
    df = row("ORD", "LAX", "2024-01-15", 800, 270, 1030)
    df["CRSDepTime"] = df.CRSDepTime.astype("Int16")
    df["CRSArrTime"] = df.CRSArrTime.astype("Int16")
    for c in ("CRSElapsedTime", "DepDelay", "ArrDelay"):
        df[c] = df[c].astype("float32")
    df["Origin"] = df.Origin.astype("category")
    df["Dest"] = df.Dest.astype("category")
    out, _ = add_utc_columns(df, tz)
    assert out.SchedArrUTC[0] == pd.Timestamp("2024-01-15 18:30")
    assert check_arrivals(out, tz).Match_Percent[0] == 100.0
