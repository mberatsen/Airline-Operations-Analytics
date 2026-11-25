"""Readers and parsers for the BTS lookup tables in data/lookup/."""

import re
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOOKUP_DIR = ROOT / "data" / "lookup"

_CARRIER_RE = re.compile(r"^(.*) \((\d{4}) - (\d{4})?\)$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")


def read_lookup(name: str) -> pd.DataFrame:
    """Read data/lookup/<name>.csv as strings (Code, Description).

    Tries UTF-8 first and falls back to cp1252 (the L_AIRPORT files).
    Empty values are kept as "".
    """
    path = LOOKUP_DIR / (name + ".csv")
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="cp1252")


def parse_airport_description(desc: str) -> Tuple[str, str, str]:
    """Split 'City, ST: Airport Name' into (city, state_code, airport_name).

    Foreign airports have no state code (state_code is ""). A description
    with no colon returns ("", "", desc).
    """
    if ":" not in desc:
        return "", "", desc

    place, name = desc.split(":", 1)
    name = name.strip()

    head, sep, tail = place.rpartition(", ")
    if sep and _STATE_RE.match(tail):
        return head, tail, name

    return place.split(", ", 1)[0], "", name


def parse_carrier_history(desc: str) -> Tuple[str, int, Optional[int]]:
    """Split 'Name (2006 - 2023)' into (name, start_year, end_year).

    end_year is None for carriers still active ('(2006 - )').
    """
    match = _CARRIER_RE.match(desc)
    if not match:
        raise ValueError("Unrecognised carrier description: %r" % desc)
    name, start, end = match.groups()
    return name, int(start), int(end) if end else None
