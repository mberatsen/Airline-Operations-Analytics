"""
Clean the raw BTS on-time performance files.

For each monthly CSV in data/raw/ this script:
  - keeps only the columns used for analysis (37 of 110)
  - sets compact data types (categories, small ints, float32)
  - turns Cancelled / Diverted into True/False
  - adds readable fields: CancellationReason, FlightStatus, DepHour, ArrHour
  - sets delay-cause minutes to 0 for flights that arrived normally
  - drops duplicate rows and rows missing key fields
  - writes data/processed/flights/<same name>.parquet

A per-file log is saved to docs/cleaning_report.csv.

Usage:
  python python/clean_data.py              # clean every file not yet cleaned
  python python/clean_data.py --force      # re-clean everything
  python python/clean_data.py 2024_01      # clean only files whose name contains "2024_01"
"""

import sys
from pathlib import Path

import pandas as pd

# 1. Locate project folders
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "flights"
DOCS = ROOT / "docs"

OUT.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(exist_ok=True)

# 2. Columns to keep, with the data type to read each one as
COLUMNS = {
    # Date
    "Year": "int16",
    "Quarter": "int8",
    "Month": "int8",
    "DayofMonth": "int8",
    "DayOfWeek": "int8",
    "FlightDate": "string",
    # Airline and aircraft
    "Reporting_Airline": "category",
    "Tail_Number": "string",
    "Flight_Number_Reporting_Airline": "Int32",  # nullable: a few rows are blank
    # Route
    "Origin": "category",
    "OriginCityName": "category",
    "OriginState": "category",
    "Dest": "category",
    "DestCityName": "category",
    "DestState": "category",
    "Distance": "float32",
    # Departure
    "CRSDepTime": "Int16",
    "DepTime": "Int16",
    "DepDelay": "float32",
    "DepDel15": "float32",
    "DepTimeBlk": "category",
    "TaxiOut": "float32",
    # Arrival
    "CRSArrTime": "Int16",
    "ArrTime": "Int16",
    "ArrDelay": "float32",
    "ArrDel15": "float32",
    "TaxiIn": "float32",
    # Outcome
    "Cancelled": "float32",
    "CancellationCode": "category",
    "Diverted": "float32",
    # Durations (minutes)
    "CRSElapsedTime": "float32",
    "ActualElapsedTime": "float32",
    "AirTime": "float32",
    # Delay causes (minutes)
    "CarrierDelay": "float32",
    "WeatherDelay": "float32",
    "NASDelay": "float32",
    "SecurityDelay": "float32",
    "LateAircraftDelay": "float32",
}

DELAY_CAUSES = [
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
]

# Fields every flight must have, cancelled or not
REQUIRED = ["FlightDate", "Reporting_Airline", "Origin", "Dest", "CRSDepTime"]

CANCELLATION_REASONS = {
    "A": "Carrier",
    "B": "Weather",
    "C": "National Air System",
    "D": "Security",
}


def hhmm_to_hour(series):
    """Turn BTS hhmm times (e.g. 1435, 2400) into an hour 0-23."""
    return ((series // 100) % 24).astype("Int8")


def clean_file(path):
    """Clean one monthly file. Returns (DataFrame, log dict)."""
    df = pd.read_csv(path, usecols=list(COLUMNS), dtype=COLUMNS)
    log = {"File": path.name, "Rows_Raw": len(df)}

    # 3. Remove exact duplicates
    before = len(df)
    df = df.drop_duplicates()
    log["Duplicates_Removed"] = before - len(df)

    # 4. Remove rows missing key fields
    before = len(df)
    df = df.dropna(subset=REQUIRED)
    log["Missing_Key_Removed"] = before - len(df)

    # 5. Types
    df["FlightDate"] = pd.to_datetime(df["FlightDate"], format="%Y-%m-%d")
    df["Cancelled"] = df["Cancelled"] == 1
    df["Diverted"] = df["Diverted"] == 1

    completed = ~df["Cancelled"] & ~df["Diverted"]

    # 6. Completed flights must have an arrival delay. If not, the row is broken.
    broken = completed & df["ArrDelay"].isna()
    log["Completed_No_ArrDelay_Removed"] = int(broken.sum())
    df = df[~broken]
    completed = completed[~broken]

    # 7. Delay causes are only reported for flights 15+ min late.
    #    For other completed flights the true value is 0 minutes, not unknown.
    #    Cancelled and diverted flights keep NaN.
    df.loc[completed, DELAY_CAUSES] = df.loc[completed, DELAY_CAUSES].fillna(0)

    # 8. Readable fields
    df["CancellationReason"] = (
        df["CancellationCode"]
        .map(CANCELLATION_REASONS)
        .astype("category")
    )
    df = df.drop(columns="CancellationCode")

    status = pd.Series("On Time", index=df.index)
    status[df["ArrDel15"] == 1] = "Delayed"
    status[df["Diverted"]] = "Diverted"
    status[df["Cancelled"]] = "Cancelled"
    df["FlightStatus"] = status.astype("category")

    df["DepHour"] = hhmm_to_hour(df["CRSDepTime"])
    df["ArrHour"] = hhmm_to_hour(df["CRSArrTime"])

    df = df.reset_index(drop=True)

    log["Rows_Clean"] = len(df)
    log["Cancelled"] = int(df["Cancelled"].sum())
    log["Diverted"] = int(df["Diverted"].sum())
    log["Delayed_15"] = int((df["FlightStatus"] == "Delayed").sum())
    log["Missing_Tail_Number"] = int(df["Tail_Number"].isna().sum())

    return df, log


def main():
    args = sys.argv[1:]
    force = "--force" in args
    filters = [a for a in args if not a.startswith("--")]

    files = sorted(RAW.glob("*.csv"))
    if filters:
        files = [f for f in files if any(x in f.name for x in filters)]

    if not files:
        raise FileNotFoundError("No matching CSV files found in data/raw")

    print(f"Cleaning {len(files)} file(s) -> {OUT}")

    logs = []
    for path in files:
        target = OUT / (path.stem + ".parquet")

        if target.exists() and not force:
            print(f"Skipping {path.name} (already cleaned, use --force to redo)")
            continue

        df, log = clean_file(path)
        df.to_parquet(target, index=False)

        log["Parquet_MB"] = round(target.stat().st_size / 1e6, 1)
        logs.append(log)

        print(
            f"{path.name}: {log['Rows_Raw']:,} -> {log['Rows_Clean']:,} rows, "
            f"{log['Parquet_MB']} MB"
        )
        del df

    if not logs:
        print("Nothing new to clean.")
        return

    # 9. Save the cleaning log, keeping entries for files not cleaned this run
    report_path = DOCS / "cleaning_report.csv"
    report = pd.DataFrame(logs)

    if report_path.exists():
        old = pd.read_csv(report_path)
        old = old[~old["File"].isin(report["File"])]
        report = pd.concat([old, report], ignore_index=True)

    report = report.sort_values("File")
    report.to_csv(report_path, index=False)

    print(f"\nTotal clean rows (this run): {sum(l['Rows_Clean'] for l in logs):,}")
    print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    main()
