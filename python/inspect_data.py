
from pathlib import Path
import pandas as pd

# 1. Locate project folders
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DOCS = ROOT / "docs"

DOCS.mkdir(exist_ok=True)

# 2. Find all CSV files
files = sorted(RAW.rglob("*.csv"))

print(f"Found {len(files)} CSV files")

if not files:
    raise FileNotFoundError("No CSV files found in data/raw")

# 3. Inspect each file individually
results = []
column_sets = {}

for file in files:
    print(f"Inspecting: {file.name}")

    df = pd.read_csv(file, low_memory=False)

    column_sets[str(file.relative_to(RAW))] = set(df.columns)

    
    results.append({
        "File": str(file.relative_to(RAW)),
        "Rows": len(df),
        "Columns": len(df.columns),
        "Missing_Cells": int(df.isna().sum().sum()),
        "Duplicate_Rows": int(df.duplicated().sum())
    })

    # NEW: Identify which columns contain missing values
    missing_report = pd.DataFrame({
        "Missing_Count": df.isna().sum(),
        "Missing_Percent": (
            df.isna().mean() * 100
        ).round(2)
    })

    print(f"\n=== MISSING VALUES: {file.name} ===")
    print(
        missing_report
        .sort_values("Missing_Count", ascending=False)
        .head(15)
        .to_string()
    )

    # NEW: Check important flight information
    important_columns = [
        "FlightDate",
        "Reporting_Airline",
        "Origin",
        "Dest",
        "ArrDelay",
        "Cancelled",
        "Diverted"
    ]

    available = [
        col for col in important_columns
        if col in df.columns
    ]

    print("\n=== IMPORTANT COLUMN QUALITY ===")

    if available:
        print(
            (df[available].isna().mean() * 100)
            .round(2)
            .sort_values(ascending=False)
        )
    else:
        print("Expected columns not found.")

    # Release memory before processing the next file
    del df


# 4. Build a summary report
report = pd.DataFrame(results)

print("\n=== DATASET SUMMARY ===")
print(report.to_string(index=False))

print("\nTotal records:", f"{report['Rows'].sum():,}")

# 5. Compare column structures
all_columns = set.union(*column_sets.values())

for filename, columns in column_sets.items():
    missing = all_columns - columns

    if missing:
        print(f"\n{filename} missing columns:")
        print(sorted(missing))

# 6. Export the inspection report
output = DOCS / "data_inspection_report.csv"

report.to_csv(output, index=False)

print(f"\nReport saved to: {output}")
