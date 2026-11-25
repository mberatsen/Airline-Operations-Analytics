"""Dimension table builders for the MySQL star schema.

Each builder returns a DataFrame whose columns are named and ordered exactly
like the matching table in sql/schema/01_create_tables.sql.
"""

from typing import Dict, Iterable, List

import pandas as pd

from lookups import parse_airport_description, parse_carrier_history, read_lookup

STATUS_IDS = {"On Time": 1, "Delayed": 2, "Cancelled": 3, "Diverted": 4}


def _missing(codes: Iterable[str], known: Iterable[str]) -> List[str]:
    return sorted(set(codes) - set(known))


def _raise_missing(lookup: str, missing: List[str]) -> None:
    if missing:
        raise ValueError("Missing from %s: %s" % (lookup, ", ".join(missing)))


def build_dim_date(start: str = "2024-01-01", end: str = "2026-12-31") -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D")
    months = read_lookup("L_MONTHS").set_index("Code")["Description"]
    weekdays = read_lookup("L_WEEKDAYS").set_index("Code")["Description"]
    month_names = pd.Series([months[str(m)] for m in days.month], dtype=object)
    dow = days.dayofweek + 1  # 1 = Monday
    return pd.DataFrame({
        "date_key": (days.year * 10000 + days.month * 100 + days.day).astype("int64"),
        "full_date": days,
        "year": days.year.astype("int64"),
        "quarter": days.quarter.astype("int64"),
        "quarter_label": ["Q%d" % q for q in days.quarter],
        "month": days.month.astype("int64"),
        "month_name": month_names.values,
        "month_short": month_names.str[:3].values,
        "year_month": days.strftime("%Y-%m"),
        "day_of_month": days.day.astype("int64"),
        "day_of_week": dow.astype("int64"),
        "weekday_name": [weekdays[str(d)] for d in dow],
        "is_weekend": (dow >= 6).astype("int64"),
        "iso_week": days.isocalendar().week.to_numpy().astype("int64"),
    })


def build_dim_carrier(codes: Iterable[str]) -> pd.DataFrame:
    codes = sorted(set(str(c) for c in codes))
    lk = read_lookup("L_UNIQUE_CARRIERS")
    names = dict(zip(lk["Code"], lk["Description"]))
    _raise_missing("L_UNIQUE_CARRIERS", _missing(codes, names))
    return pd.DataFrame({"carrier_code": codes,
                         "carrier_name": [names[c] for c in codes]})


def build_dim_carrier_history() -> pd.DataFrame:
    """Parse L_CARRIER_HISTORY. Rows sharing (carrier_code, start_year) are
    collapsed, keeping the open-ended / latest end_year; the count is printed.
    """
    lk = read_lookup("L_CARRIER_HISTORY")
    rows = []
    for code, desc in zip(lk["Code"], lk["Description"]):
        name, start, end = parse_carrier_history(desc)
        rows.append((code, name, start, end))
    df = pd.DataFrame(rows, columns=["carrier_code", "carrier_name", "start_year", "end_year"])
    # open-ended (NaN) sorts as the latest
    df["_end_sort"] = df["end_year"].fillna(10 ** 6)
    df = df.sort_values(["carrier_code", "start_year", "_end_sort"], kind="mergesort")
    before = len(df)
    df = df.drop_duplicates(["carrier_code", "start_year"], keep="last")
    collapsed = before - len(df)
    if collapsed:
        print("dim_carrier_history: collapsed %d duplicate (carrier_code, start_year) rows" % collapsed)
    df = df.drop(columns="_end_sort").reset_index(drop=True)
    df["start_year"] = df["start_year"].astype("int64")
    df["end_year"] = df["end_year"].astype("Int64")
    return df[["carrier_code", "carrier_name", "start_year", "end_year"]]


def build_dim_airport(codes: Iterable[str], tz: Dict[str, str]) -> pd.DataFrame:
    codes = sorted(set(str(c) for c in codes))
    lk = read_lookup("L_AIRPORT")
    desc = dict(zip(lk["Code"], lk["Description"]))
    _raise_missing("L_AIRPORT", _missing(codes, desc))
    _raise_missing("timezone map", _missing(codes, tz))

    states_lk = read_lookup("L_STATE_ABR_AVIATION")
    states = dict(zip(states_lk["Code"], states_lk["Description"]))

    rows = []
    for code in codes:
        city, state_code, name = parse_airport_description(desc[code])
        rows.append((code, name, city, state_code, tz[code]))
    df = pd.DataFrame(rows, columns=["airport_code", "airport_name", "city", "state_code", "timezone"])
    used = set(df["state_code"]) - {""}
    _raise_missing("L_STATE_ABR_AVIATION", _missing(used, states))
    df["state_name"] = df["state_code"].map(lambda s: states[s] if s else "")
    return df[["airport_code", "airport_name", "city", "state_code", "state_name", "timezone"]]


def build_dim_route(flights: pd.DataFrame) -> pd.DataFrame:
    df = flights[["Origin", "Dest", "Distance", "FlightDate"]].copy()
    df["Origin"] = df["Origin"].astype(str)
    df["Dest"] = df["Dest"].astype(str)
    # latest FlightDate wins; ties -> max distance
    df = df.sort_values(["Origin", "Dest", "FlightDate", "Distance"], kind="mergesort")
    last = df.drop_duplicates(["Origin", "Dest"], keep="last").reset_index(drop=True)
    miles = last["Distance"].astype("float64").round().astype("int64")
    bands = read_lookup("L_DISTANCE_GROUP_250")
    labels = dict(zip(bands["Code"].astype(int), bands["Description"]))
    group = ((miles // 250) + 1).clip(upper=11).astype("int64")
    return pd.DataFrame({
        "route_id": range(1, len(last) + 1),
        "origin_code": last["Origin"],
        "dest_code": last["Dest"],
        "route_label": last["Origin"] + "-" + last["Dest"],
        "distance_miles": miles,
        "distance_group": group,
        "distance_group_label": group.map(labels),
    })


def build_dim_aircraft(flights: pd.DataFrame) -> pd.DataFrame:
    df = flights[["Tail_Number", "Reporting_Airline", "FlightDate"]].copy()
    df = df[df["Tail_Number"].notna()]
    df["Tail_Number"] = df["Tail_Number"].astype(str)
    df["Reporting_Airline"] = df["Reporting_Airline"].astype(str)

    per = (df.groupby(["Tail_Number", "Reporting_Airline"], observed=True)
             .size().rename("n").reset_index())
    # most flights; ties -> alphabetical carrier code
    per = per.sort_values(["Tail_Number", "n", "Reporting_Airline"],
                          ascending=[True, False, True], kind="mergesort")
    primary = per.drop_duplicates("Tail_Number", keep="first").set_index("Tail_Number")["Reporting_Airline"]

    agg = df.groupby("Tail_Number", observed=True)["FlightDate"].agg(["min", "max", "size"]).sort_index()
    return pd.DataFrame({
        "aircraft_id": range(1, len(agg) + 1),
        "tail_number": agg.index.to_numpy(),
        "primary_carrier_code": primary.reindex(agg.index).to_numpy(),
        "first_flight_date": agg["min"].to_numpy(),
        "last_flight_date": agg["max"].to_numpy(),
        "flight_count": agg["size"].to_numpy().astype("int64"),
    })


def _day_part(hour: int) -> str:
    if hour < 6:
        return "Night"
    if hour < 12:
        return "Morning"
    if hour < 18:
        return "Afternoon"
    return "Evening"


def build_dim_time_block() -> pd.DataFrame:
    lk = read_lookup("L_DEPARRBLK")
    rows = []
    for code, label in zip(lk["Code"], lk["Description"]):
        start, end = int(code[:2]), int(code[5:7])
        rows.append((code, label, start, end, _day_part(start)))
    return pd.DataFrame(rows, columns=["block_code", "block_label", "start_hour", "end_hour", "day_part"])


def build_dim_cancellation() -> pd.DataFrame:
    lk = read_lookup("L_CANCELLATION")
    return pd.DataFrame({"cancellation_code": lk["Code"], "reason": lk["Description"]})


def build_dim_status() -> pd.DataFrame:
    return pd.DataFrame({
        "status_id": list(STATUS_IDS.values()),
        "status_name": list(STATUS_IDS.keys()),
        "sort_order": list(STATUS_IDS.values()),
    })
