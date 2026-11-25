"""Build data/lookup/airport_timezones.csv (airport_code -> IANA time zone).

Source: OpenFlights airports.dat, with manual fixes in
airport_timezone_overrides.csv (overrides win).
"""

from pathlib import Path
from typing import Dict, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from lookups import LOOKUP_DIR, ROOT

OPENFLIGHTS_PATH = LOOKUP_DIR / "openflights_airports.dat"
OVERRIDES_PATH = LOOKUP_DIR / "airport_timezone_overrides.csv"
OUTPUT_PATH = LOOKUP_DIR / "airport_timezones.csv"
FLIGHTS_DIR = ROOT / "data" / "processed" / "flights"


def parse_openflights(path: Path) -> pd.DataFrame:
    """Read airports.dat (no header); keep IATA code (col 4) and time zone (col 11)."""
    raw = pd.read_csv(
        path, header=None, dtype=str, keep_default_na=False,
        usecols=[4, 11], names=None, encoding="utf-8",
    )
    raw.columns = ["airport_code", "timezone"]
    raw = raw[(raw["airport_code"] != "\\N") & (raw["timezone"] != "\\N")]
    raw = raw[(raw["airport_code"] != "") & (raw["timezone"] != "")]
    return raw.drop_duplicates("airport_code").reset_index(drop=True)


def _validate_zones(zones: Iterable[str]) -> None:
    bad = []
    for zone in set(zones):
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            bad.append(zone)
    if bad:
        raise ValueError("Invalid time zones: %s" % ", ".join(sorted(bad)))


def build_timezone_table(
    codes: Iterable[str], openflights: pd.DataFrame, overrides: pd.DataFrame
) -> pd.DataFrame:
    """Return airport_code,timezone for every code; overrides win over OpenFlights."""
    mapping = dict(zip(openflights["airport_code"], openflights["timezone"]))
    mapping.update(dict(zip(overrides["airport_code"], overrides["timezone"])))

    wanted = sorted(set(codes))
    missing = [c for c in wanted if c not in mapping]
    if missing:
        raise ValueError("No time zone for airports: %s" % ", ".join(missing))

    table = pd.DataFrame({"airport_code": wanted, "timezone": [mapping[c] for c in wanted]})
    _validate_zones(table["timezone"])
    return table


def load_timezones() -> Dict[str, str]:
    """Return {airport_code: IANA zone} from airport_timezones.csv."""
    df = pd.read_csv(OUTPUT_PATH, dtype=str, keep_default_na=False)
    return dict(zip(df["airport_code"], df["timezone"]))


def main() -> None:
    flights = pd.read_parquet(FLIGHTS_DIR, columns=["Origin", "Dest"])
    codes = set(flights["Origin"].astype(str)) | set(flights["Dest"].astype(str))
    openflights = parse_openflights(OPENFLIGHTS_PATH)
    overrides = pd.read_csv(OVERRIDES_PATH, dtype=str, keep_default_na=False)
    table = build_timezone_table(codes, openflights, overrides)
    table.to_csv(OUTPUT_PATH, index=False)
    print("Wrote %d airports to %s" % (len(table), OUTPUT_PATH))


if __name__ == "__main__":
    main()
