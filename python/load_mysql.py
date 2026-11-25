"""Load the cleaned monthly Parquet files into the MySQL star schema.

Dimensions are built from all files and inserted with executemany; the fact table
is bulk-loaded month by month with LOAD DATA LOCAL INFILE.

    python python/load_mysql.py [--database NAME] [--months 2024_01,2024_02]
"""
import argparse
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pymysql

import db
from build_timezones import load_timezones
from dimensions import (STATUS_IDS, build_dim_aircraft, build_dim_airport,
                        build_dim_cancellation, build_dim_carrier,
                        build_dim_carrier_history, build_dim_date,
                        build_dim_route, build_dim_status, build_dim_time_block)

ROOT = db.ROOT
FLIGHTS_DIR = ROOT / "data" / "processed" / "flights"
CLEANING_REPORT = ROOT / "docs" / "cleaning_report.csv"
VERIFICATION_CSV = ROOT / "docs" / "load_verification.csv"
BATCH = 5000

FACT_COLUMNS = [
    "date_key", "carrier_code", "flight_number", "origin_code", "dest_code",
    "route_id", "aircraft_id", "dep_time_block", "status_id", "cancellation_code",
    "is_cancelled", "is_diverted", "crs_dep_time", "dep_time", "crs_arr_time",
    "arr_time", "dep_hour", "arr_hour", "sched_dep_utc", "sched_arr_utc",
    "actual_dep_utc", "actual_arr_utc", "dep_delay", "arr_delay", "dep_del15",
    "arr_del15", "taxi_out", "taxi_in", "crs_elapsed_time", "actual_elapsed_time",
    "air_time", "distance", "carrier_delay", "weather_delay", "nas_delay",
    "security_delay", "late_aircraft_delay",
]

# fact column -> source Parquet column, for plain numeric copies
_NUMERIC = {
    "flight_number": "Flight_Number_Reporting_Airline",
    "crs_dep_time": "CRSDepTime", "dep_time": "DepTime",
    "crs_arr_time": "CRSArrTime", "arr_time": "ArrTime",
    "dep_hour": "DepHour", "arr_hour": "ArrHour",
    "dep_delay": "DepDelay", "arr_delay": "ArrDelay",
    "dep_del15": "DepDel15", "arr_del15": "ArrDel15",
    "taxi_out": "TaxiOut", "taxi_in": "TaxiIn",
    "crs_elapsed_time": "CRSElapsedTime", "actual_elapsed_time": "ActualElapsedTime",
    "air_time": "AirTime", "distance": "Distance",
    "carrier_delay": "CarrierDelay", "weather_delay": "WeatherDelay",
    "nas_delay": "NASDelay", "security_delay": "SecurityDelay",
    "late_aircraft_delay": "LateAircraftDelay",
}
_DATETIMES = {
    "sched_dep_utc": "SchedDepUTC", "sched_arr_utc": "SchedArrUTC",
    "actual_dep_utc": "ActualDepUTC", "actual_arr_utc": "ActualArrUTC",
}


def _db_value(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def insert_dim(conn, table: str, df: pd.DataFrame) -> None:
    """Insert a dimension DataFrame (columns in table order) in batches of 5,000."""
    cols = list(df.columns)
    sql = "INSERT INTO `%s` (%s) VALUES (%s)" % (
        table, ", ".join("`%s`" % c for c in cols), ", ".join(["%s"] * len(cols)))
    rows = [tuple(_db_value(v) for v in r) for r in df.astype(object).itertuples(index=False, name=None)]
    with conn.cursor() as cur:
        for i in range(0, len(rows), BATCH):
            cur.executemany(sql, rows[i:i + BATCH])
    conn.commit()


def _parquet_files(flights_dir: Path, months: Optional[Sequence[str]] = None) -> List[Path]:
    files = sorted(Path(flights_dir).glob("bts_flights_*.parquet"))
    if months:
        wanted = {"bts_flights_%s.parquet" % m for m in months}
        files = [f for f in files if f.name in wanted]
    return files


def load_dimensions(conn, flights_dir: Path) -> Tuple[Dict[Tuple[str, str], int], Dict[str, int]]:
    """Build and insert every dimension; return (route_ids, aircraft_ids) maps."""
    cols = ["FlightDate", "Reporting_Airline", "Tail_Number", "Origin", "Dest", "Distance"]
    files = _parquet_files(flights_dir)
    if not files:
        raise FileNotFoundError("No bts_flights_*.parquet in %s" % flights_dir)
    flights = pd.concat([pd.read_parquet(f, columns=cols) for f in files], ignore_index=True)
    for c in ("Reporting_Airline", "Origin", "Dest"):
        flights[c] = flights[c].astype(str)

    airports = set(flights["Origin"]) | set(flights["Dest"])
    route = build_dim_route(flights)
    aircraft = build_dim_aircraft(flights)
    aircraft["first_flight_date"] = aircraft["first_flight_date"].dt.strftime("%Y-%m-%d")
    aircraft["last_flight_date"] = aircraft["last_flight_date"].dt.strftime("%Y-%m-%d")

    # parents before children
    insert_dim(conn, "dim_date", build_dim_date())
    insert_dim(conn, "dim_carrier", build_dim_carrier(flights["Reporting_Airline"].unique()))
    insert_dim(conn, "dim_carrier_history", build_dim_carrier_history())
    insert_dim(conn, "dim_airport", build_dim_airport(airports, load_timezones()))
    insert_dim(conn, "dim_time_block", build_dim_time_block())
    insert_dim(conn, "dim_cancellation", build_dim_cancellation())
    insert_dim(conn, "dim_status", build_dim_status())
    insert_dim(conn, "dim_route", route)
    insert_dim(conn, "dim_aircraft", aircraft)

    route_ids = {(o, d): int(i) for o, d, i in zip(route["origin_code"], route["dest_code"], route["route_id"])}
    aircraft_ids = {t: int(i) for t, i in zip(aircraft["tail_number"], aircraft["aircraft_id"])}
    return route_ids, aircraft_ids


def read_id_maps(conn) -> Tuple[Dict[Tuple[str, str], int], Dict[str, int]]:
    """Read the route and aircraft id maps back from an already-loaded database."""
    hint = "Run without --months (or with --rebuild) first to build the dimensions."
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT origin_code, dest_code, route_id FROM dim_route")
            routes = {(o, d): int(i) for o, d, i in cur.fetchall()}
            cur.execute("SELECT tail_number, aircraft_id FROM dim_aircraft")
            aircraft = {t: int(i) for t, i in cur.fetchall()}
    except pymysql.err.ProgrammingError as exc:
        raise RuntimeError("Dimension tables are missing (%s). %s" % (exc, hint))
    if not routes or not aircraft:
        raise RuntimeError("dim_route / dim_aircraft are empty. " + hint)
    return routes, aircraft


def to_fact_frame(df: pd.DataFrame, route_ids, aircraft_ids) -> pd.DataFrame:
    """Map a cleaned month to fact_flights columns (without flight_id)."""
    origin = df["Origin"].astype(str).reset_index(drop=True)
    dest = df["Dest"].astype(str).reset_index(drop=True)
    keys = pd.MultiIndex.from_arrays([origin, dest])
    route_series = pd.Series(route_ids)
    if len(route_series):
        route_series.index = pd.MultiIndex.from_tuples(list(route_series.index))
    route_id = pd.Series(route_series.reindex(keys).to_numpy())
    if route_id.isna().any():
        bad = route_id.isna().to_numpy()
        pairs = sorted(set(zip(origin[bad], dest[bad])))[:5]
        raise ValueError("Route not in dim_route: %s. A full rebuild is needed (run without --months, or with --rebuild)." % ", ".join("%s-%s" % p for p in pairs))

    tail = df["Tail_Number"].astype("string").reset_index(drop=True)
    aircraft_id = tail.map(aircraft_ids)
    unknown = tail.notna() & aircraft_id.isna()
    if unknown.any():
        raise ValueError("Tail number not in dim_aircraft: %s. A full rebuild is needed "
                         "(run without --months, or with --rebuild)." %
                         ", ".join(sorted(set(tail[unknown].astype(str)))[:5]))

    status = df["FlightStatus"].astype(str).map(STATUS_IDS)
    if status.isna().any():
        raise ValueError("Unknown FlightStatus: %s" %
                         ", ".join(sorted(set(df["FlightStatus"].astype(str)[status.isna().to_numpy()]))))

    out = pd.DataFrame(index=range(len(df)))
    fd = pd.to_datetime(df["FlightDate"]).reset_index(drop=True)
    out["date_key"] = (fd.dt.year * 10000 + fd.dt.month * 100 + fd.dt.day).astype("int64")
    out["carrier_code"] = df["Reporting_Airline"].astype(str).to_numpy()
    out["origin_code"] = origin
    out["dest_code"] = dest
    out["route_id"] = route_id.astype("int64")
    out["aircraft_id"] = aircraft_id.astype("Int64")
    out["dep_time_block"] = df["DepTimeBlk"].astype(str).to_numpy()
    out["status_id"] = status.to_numpy().astype("int64")
    cc = df["CancellationCode"].astype(object).reset_index(drop=True)
    out["cancellation_code"] = cc.where(cc.notna(), None)
    out["is_cancelled"] = df["Cancelled"].to_numpy().astype("int64")
    out["is_diverted"] = df["Diverted"].to_numpy().astype("int64")
    for col, src in _NUMERIC.items():
        s = pd.to_numeric(df[src], errors="coerce").reset_index(drop=True)
        out[col] = s.round().astype("Int64")
    for col, src in _DATETIMES.items():
        out[col] = pd.to_datetime(df[src]).reset_index(drop=True)
    return out[FACT_COLUMNS]


def write_mysql_csv(df: pd.DataFrame, path: Path) -> None:
    """Write df for LOAD DATA: NULL as unquoted \\N, no header, UTF-8, \\n endings."""
    df.to_csv(path, index=False, header=False, na_rep="\\N", encoding="utf-8",
              lineterminator="\n", date_format="%Y-%m-%d %H:%M:%S")


def _sql_string(path: Path) -> str:
    return "'" + str(path).replace("\\", "\\\\").replace("'", "\\'") + "'"


def load_month(conn, parquet_path: Path, route_ids, aircraft_ids) -> int:
    """Replace one month in fact_flights (DELETE + LOAD DATA in one transaction)."""
    df = pd.read_parquet(parquet_path)
    fact = to_fact_frame(df, route_ids, aircraft_ids)
    lo, hi = int(fact["date_key"].min()), int(fact["date_key"].max())
    fd, tmp = tempfile.mkstemp(suffix=".csv", prefix="fact_")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        write_mysql_csv(fact, tmp_path)
        sql = ("LOAD DATA LOCAL INFILE %s INTO TABLE fact_flights "
               "CHARACTER SET utf8mb4 "
               "FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' ESCAPED BY '\\\\' "
               "LINES TERMINATED BY '\\n' (%s)" % (
                   _sql_string(tmp_path), ", ".join("`%s`" % c for c in FACT_COLUMNS)))
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM fact_flights WHERE date_key BETWEEN %s AND %s", (lo, hi))
                cur.execute(sql)
                loaded = cur.rowcount
                cur.execute("SHOW WARNINGS")
                warns = [w for w in cur.fetchall() if w[0] in ("Warning", "Error")]
            if warns:
                raise RuntimeError("LOAD DATA warnings for %s: %s" % (parquet_path.name, warns[:5]))
            if loaded != len(fact):
                raise RuntimeError("Loaded %d rows, expected %d" % (loaded, len(fact)))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    finally:
        _rm(tmp_path)
    return loaded


def _rm(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def verify(conn, report_csv: Path, months: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Compare per-month counts in fact_flights with the cleaning report."""
    rep = pd.read_csv(report_csv)
    rep["Month"] = rep["File"].str.extract(r"(\d{4}_\d{2})")[0]
    if months:
        rep = rep[rep["Month"].isin(list(months))]
    with conn.cursor() as cur:
        cur.execute("SELECT date_key DIV 100, COUNT(*), SUM(is_cancelled), SUM(is_diverted), "
                    "SUM(status_id = %s) FROM fact_flights GROUP BY date_key DIV 100",
                    (STATUS_IDS["Delayed"],))
        got = {"%04d_%02d" % divmod(int(r[0]), 100): [int(x) for x in r[1:]] for r in cur.fetchall()}
    rows = []
    for _, r in rep.iterrows():
        g = got.get(r["Month"], [0, 0, 0, 0])
        rows.append({
            "Month": r["Month"],
            "Rows_Report": int(r["Rows_Clean"]), "Rows_DB": g[0],
            "Cancelled_Report": int(r["Cancelled"]), "Cancelled_DB": g[1],
            "Diverted_Report": int(r["Diverted"]), "Diverted_DB": g[2],
            "Delayed_Report": int(r["Delayed_15"]), "Delayed_DB": g[3],
        })
    out = pd.DataFrame(rows)
    ok = ((out["Rows_Report"] == out["Rows_DB"]) & (out["Cancelled_Report"] == out["Cancelled_DB"])
          & (out["Diverted_Report"] == out["Diverted_DB"]) & (out["Delayed_Report"] == out["Delayed_DB"]))
    out["Match"] = ok
    if not ok.all():
        raise AssertionError("Load does not match the cleaning report:\n%s" % out[~ok].to_string())
    return out


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--database", default=None, help="default: airline_ops")
    ap.add_argument("--months", default=None, help="comma list like 2024_01,2024_02 (default all)")
    ap.add_argument("--rebuild", action="store_true",
                    help="with --months: drop and rebuild the schema and dimensions first")
    ap.add_argument("--flights-dir", default=str(FLIGHTS_DIR))
    ap.add_argument("--report", default=str(CLEANING_REPORT))
    ap.add_argument("--output", default=str(VERIFICATION_CSV))
    args = ap.parse_args(argv)

    months = [m.strip() for m in args.months.split(",") if m.strip()] if args.months else None
    flights_dir = Path(args.flights_dir)
    files = _parquet_files(flights_dir, months)
    if months and len(files) != len(months):
        raise SystemExit("Missing Parquet files for some of: %s" % ", ".join(months))

    conn = db.connect(args.database or "airline_ops")
    try:
        if months is None or args.rebuild:
            db.apply_schema(conn)
            t0 = time.time()
            route_ids, aircraft_ids = load_dimensions(conn, flights_dir)
            print("dimensions loaded in %.1fs (%d routes, %d aircraft)" %
                  (time.time() - t0, len(route_ids), len(aircraft_ids)))
            verify_months = months
        else:
            route_ids, aircraft_ids = read_id_maps(conn)
            verify_months = months
        for f in files:
            t = time.time()
            n = load_month(conn, f, route_ids, aircraft_ids)
            print("%s: %d rows in %.1fs" % (f.name, n, time.time() - t), flush=True)
        result = verify(conn, Path(args.report), verify_months)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.output, index=False)
        print("verified %d month(s); wrote %s" % (len(result), args.output))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
