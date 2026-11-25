"""Convert BTS local hhmm times to UTC (tz-naive datetime64[ns] holding UTC)."""
from typing import Dict, Tuple

import numpy as np
import pandas as pd

_NS_MIN = np.timedelta64(1, "m")


def _codes_to_zones(codes: pd.Series, tz: Dict[str, str], label: str) -> pd.Series:
    """Map airport codes to IANA zones; raise KeyError naming unknown codes."""
    codes = codes.astype(object)
    uniq = pd.unique(codes)
    missing = sorted(str(c) for c in uniq if c not in tz)
    if missing:
        raise KeyError("%s not in time zone map: %s" % (label, ", ".join(missing)))
    return codes.map(tz)


def _hhmm_to_minutes(s: pd.Series) -> np.ndarray:
    """hhmm -> minutes since midnight (2400 -> 1440); NaN when missing."""
    v = pd.to_numeric(s, errors="coerce").astype("float64").to_numpy()
    return (v // 100) * 60 + (v % 100)


def _local_naive(dates: pd.Series, minutes: np.ndarray) -> pd.Series:
    base = dates.to_numpy().astype("datetime64[ns]")
    delta = pd.to_timedelta(minutes, unit="m")
    return pd.Series(pd.DatetimeIndex(base) + delta, index=dates.index)


def _localize_to_utc(local: pd.Series, zones: pd.Series, count: bool = False):
    """Localize naive wall-clock values per zone and convert to naive UTC.

    Returns (utc values as datetime64[ns] ndarray, nonexistent, ambiguous).
    """
    out = np.full(len(local), np.datetime64("NaT"), dtype="datetime64[ns]")
    n_non = n_amb = 0
    zarr = zones.to_numpy()
    for zone in pd.unique(zarr):
        pos = np.flatnonzero(zarr == zone)
        s = pd.DatetimeIndex(local.to_numpy()[pos])
        amb = np.ones(len(s), dtype=bool)  # True = first (DST) occurrence
        loc = s.tz_localize(zone, nonexistent="shift_forward", ambiguous=amb)
        out[pos] = loc.tz_convert("UTC").tz_localize(None).to_numpy()
        if count:
            valid = int(s.notna().sum())
            n_non += valid - int(s.tz_localize(
                zone, nonexistent="NaT", ambiguous=amb).notna().sum())
            n_amb += valid - int(s.tz_localize(
                zone, nonexistent="shift_forward", ambiguous="NaT").notna().sum())
    return out, n_non, n_amb


def add_utc_columns(df: pd.DataFrame, tz: Dict[str, str]) -> Tuple[pd.DataFrame, Dict[str, int]]:
    out = df.copy()
    o_zone = _codes_to_zones(df["Origin"], tz, "Origin")
    d_zone = _codes_to_zones(df["Dest"], tz, "Dest")

    dep_local = _local_naive(df["FlightDate"], _hhmm_to_minutes(df["CRSDepTime"]))
    dep_utc, n_non, n_amb = _localize_to_utc(dep_local, o_zone, count=True)

    elapsed = pd.to_numeric(df["CRSElapsedTime"], errors="coerce").astype("float64").to_numpy()
    fallback = ~(elapsed > 0)  # NaN or <= 0
    with np.errstate(invalid="ignore"):
        arr_utc = dep_utc + pd.to_timedelta(
            np.where(fallback, np.nan, elapsed), unit="m").to_numpy()

    if fallback.any():
        arr_local = _local_naive(df["FlightDate"], _hhmm_to_minutes(df["CRSArrTime"]))
        fb_utc, _, _ = _localize_to_utc(arr_local, d_zone)
        fb_utc = np.where(fb_utc < dep_utc, fb_utc + np.timedelta64(1, "D"), fb_utc)
        arr_utc = np.where(fallback, fb_utc, arr_utc)

    def _plus(base, col):
        d = pd.to_numeric(df[col], errors="coerce").astype("float64").to_numpy()
        return base + pd.to_timedelta(d, unit="m").to_numpy()

    out["SchedDepUTC"] = dep_utc
    out["SchedArrUTC"] = arr_utc
    out["ActualDepUTC"] = _plus(dep_utc, "DepDelay")
    out["ActualArrUTC"] = _plus(arr_utc, "ArrDelay")
    out["ArrivalFallback"] = fallback
    stats = {
        "DST_Nonexistent": int(n_non),
        "DST_Ambiguous": int(n_amb),
        "Arrival_Fallback": int(fallback.sum()),
    }
    return out, stats


def check_arrivals(df: pd.DataFrame, tz: Dict[str, str]) -> pd.DataFrame:
    """Per-Dest share of flights whose SchedArrUTC, in the dest zone, equals CRSArrTime."""
    dest = df["Dest"].astype(object)
    zones = _codes_to_zones(dest, tz, "Dest")
    crs_min = _hhmm_to_minutes(df["CRSArrTime"]) % 1440
    sched = df["SchedArrUTC"].to_numpy()
    eligible = (~df["ArrivalFallback"].to_numpy(dtype=bool)
                & ~np.isnat(sched) & ~np.isnan(crs_min))
    matched = np.zeros(len(df), dtype=bool)
    zarr = zones.to_numpy()
    for zone in pd.unique(zarr):
        pos = np.flatnonzero((zarr == zone) & eligible)
        if len(pos) == 0:
            continue
        loc = pd.DatetimeIndex(sched[pos]).tz_localize("UTC").tz_convert(zone)
        mins = loc.hour * 60 + loc.minute
        matched[pos] = np.asarray(mins) == crs_min[pos]

    res = pd.DataFrame({
        "Dest": dest.to_numpy(),
        "Flights": eligible.astype("int64"),
        "Matched": matched.astype("int64"),
    }).groupby("Dest", sort=True, as_index=False).sum()
    pct = 100.0 * res["Matched"] / res["Flights"].where(res["Flights"] > 0)
    res["Match_Percent"] = pct.round(2)
    return res.reset_index(drop=True)
