# MySQL Star Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load the 18.8M cleaned BTS flights into a MySQL star schema (`fact_flights` + 9 dimensions + 4 views) with correct UTC timestamps, rebuilt entirely from scripts.

**Architecture:**
- The Python pipeline stays the source of truth.
- `clean_data.py` adds UTC timestamps (using a new airport → IANA time zone lookup) and normalized tail numbers to the Parquet files.
- A new `dimensions.py` builds the dimension tables from Parquet + BTS lookups.
- `load_mysql.py` creates the schema from SQL files and bulk-loads each month with `LOAD DATA LOCAL INFILE`, one transaction per month.

**Tech Stack:** Python 3.9 (`.venv`), pandas 2.3, pyarrow 21, `zoneinfo`/`tzdata`, PyMySQL, python-dotenv, pytest, MySQL 8.x/9.x (Homebrew).

**Spec:** `docs/superpowers/specs/2026-11-24-mysql-star-schema-design.md`

## Global Constraints

- **Python 3.9:** no `X | Y` type unions and no `match` statements; use `typing.Optional`/`Union`.
- **Scripts live in `python/` as plain modules, not a package.** Tests import them through `tests/conftest.py`, which puts `python/` on `sys.path`.
- **Encoding:** MySQL charset `utf8mb4`, collation `utf8mb4_0900_ai_ci`. `L_AIRPORT*.csv` are cp1252; all other lookups are UTF-8.
- **Database name `airline_ops`; test database `airline_ops_test`.** Connection settings come from `.env` (git-ignored): `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`.
- **Dimensions contain only codes present in the flight data.** A code missing from a lookup raises `ValueError` naming the code(s).
- **Foreign keys on, no partitioning.**
- **Keys:** airports by 3-letter code; dates by `date_key = YYYYMMDD` (INT); `dim_date` covers 2024-01-01 to 2026-12-31.
- **Delay columns:** 0 = completed flight and that cause didn't apply; NULL = cancelled or diverted.
- **Time zone self-check:** an airport below 99% match on scheduled arrival stops the clean.
- **Two actions need the user's yes when reached:** `brew install mysql` (Task 5) and downloading OpenFlights `airports.dat` (Task 2).

## Review Focus

1. **Rerunning a month after a failed or partial load** must leave exactly one copy of each flight. Covered by `test_load_month_twice_no_duplicates` (Task 7).
2. **A new airport or carrier code with no time zone or lookup entry** must stop with an error naming the code, not load a blank. Covered by `test_build_fails_on_missing_airport` (Task 2) and `test_dim_airport_missing_code_raises` (Task 6).
3. **Flights scheduled in a DST gap or overlap** must convert without crashing and be counted. Covered by `test_spring_forward_gap` and `test_fall_back_ambiguous` (Task 3).
4. **Accented airport names from cp1252 files** must arrive in MySQL as the same characters. Covered by `test_airport_name_roundtrip_accents` (Task 7).
5. **pandas NaN / pd.NA** must become MySQL NULL, not `0`, `nan` or an empty string. Covered by `test_nulls_load_as_null` (Task 7).

---

### Task 1: Test setup and lookup readers

**Files:**
- Create: `requirements.txt`, `tests/conftest.py`, `python/lookups.py`, `tests/test_lookups.py`

**Interfaces:**
- Produces:
  - `LOOKUP_DIR: Path` (`data/lookup`)
  - `read_lookup(name: str) -> pd.DataFrame`: columns `Code`, `Description`, all `str`, empty values kept as `""`, encoding chosen automatically (UTF-8, falling back to cp1252)
  - `parse_airport_description(desc: str) -> Tuple[str, str, str]`: returns `(city, state_code, airport_name)`
  - `parse_carrier_history(desc: str) -> Tuple[str, int, Optional[int]]`: returns `(name, start_year, end_year)`

- [ ] **Step 1:** Write `requirements.txt` with `pandas==2.3.3`, `pyarrow==21.0.0`, `tzdata`, `PyMySQL`, `python-dotenv`, `pytest`. Run `.venv/bin/pip install -r requirements.txt`. Expected: it installs without errors.
- [ ] **Step 2:** Write `tests/conftest.py`. It inserts `ROOT / "python"` into `sys.path` and defines a `tiny_flights` fixture: a DataFrame with the same columns and dtypes as `clean_data.clean_file` output, with 6 rows covering on time, delayed, cancelled, diverted, missing tail and an Allegiant tail `188NV`.
- [ ] **Step 3: Write the failing tests** in `tests/test_lookups.py`:
```python
def test_read_lookup_utf8():
    df = read_lookup("L_CANCELLATION")
    assert list(df.columns) == ["Code", "Description"]
    assert df.set_index("Code").loc["B", "Description"] == "Weather"

def test_read_lookup_cp1252_has_accents():
    df = read_lookup("L_AIRPORT")
    assert len(df) == 6942
    assert df["Description"].str.contains("[À-ÿ]", regex=True).any()

def test_parse_airport_description():
    assert parse_airport_description("Afognak Lake, AK: Afognak Lake Airport") == ("Afognak Lake", "AK", "Afognak Lake Airport")
    assert parse_airport_description("Washington, DC: Ronald Reagan Washington National") == ("Washington", "DC", "Ronald Reagan Washington National")
    assert parse_airport_description("Kekaha, Kauai, HI: Barking Sands PMRF") == ("Kekaha, Kauai", "HI", "Barking Sands PMRF")
    # foreign: country contains commas -> no state code
    assert parse_airport_description("Saba, Bonaire, Sint Eustatius, and Saba: Juancho E. Yrausquin") == ("Saba", "", "Juancho E. Yrausquin")
    # double space after colon is stripped
    assert parse_airport_description("Jamestown, Saint Helena, Ascension, and Tristan da Cunha:  Saint Helena")[2] == "Saint Helena"

def test_parse_carrier_history():
    assert parse_carrier_history("Tradewind Aviation (2006 - 2023)") == ("Tradewind Aviation", 2006, 2023)
    assert parse_carrier_history("Titan Airways (2006 - )") == ("Titan Airways", 2006, None)
```
- [ ] **Step 4:** Run `.venv/bin/pytest tests/test_lookups.py -v`. Expected: FAIL with `ModuleNotFoundError: lookups`.
- [ ] **Step 5:** Implement `python/lookups.py`.
  - Airport descriptions:
    - Split on the first `":"`. The name is the part after it, stripped of spaces.
    - In the part before it, if the text after the last `", "` is exactly 2 uppercase letters, that's `state_code` and everything before it is the city.
    - Otherwise the city is the text before the first `", "` and `state_code` is `""`.
    - With no `":"` at all, return `("", "", description)`. Two lookup rows have no colon.
  - Carrier history is parsed with the regex `^(.*) \((\d{4}) - (\d{4})?\)$`.
- [ ] **Step 6:** Run the tests. Expected: 4 passed.
- [ ] **Step 7:** Commit: `git add requirements.txt tests/ python/lookups.py && git commit -m "Add lookup readers and test setup"`

### Task 2: Airport time zone lookup

**Files:**
- Create: `python/build_timezones.py`, `data/lookup/airport_timezone_overrides.csv` (header `airport_code,timezone,note`), `tests/test_build_timezones.py`
- Output: `data/lookup/airport_timezones.csv` (`airport_code,timezone`)

**Interfaces:**
- Consumes: Parquet in `data/processed/flights/` (`Origin`, `Dest`)
- Produces:
  - `parse_openflights(path: Path) -> pd.DataFrame`: columns `airport_code`, `timezone`. `airports.dat` has no header; IATA code is column 4 and the time zone is column 11 (0-based: 4 and 11). Drop rows where the IATA code is `\N` or the time zone is `\N`.
  - `build_timezone_table(codes: Iterable[str], openflights: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame`: overrides win; raises `ValueError("No time zone for airports: ...")` listing the missing codes, sorted
  - `load_timezones() -> Dict[str, str]`: reads `airport_timezones.csv`
  - `main()`: reads the codes used in Parquet and writes the CSV

- [ ] **Step 1: Ask the user to confirm the download.** File: `airports.dat`. Source: `https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat`. Size: about 1.1 MB. Destination: `data/lookup/openflights_airports.dat`. Check its size with `curl -sI` first and include it in the ask. Download only after a yes.
- [ ] **Step 2: Write the failing tests:**
```python
def test_parse_openflights_reads_iata_and_tz(tmp_path):
    p = tmp_path / "a.dat"
    p.write_text('3830,"Chicago O\'Hare","Chicago","United States","ORD","KORD",41.97,-87.90,672,-6,"A","America/Chicago","airport","OurAirports"\n'
                 '1,"No IATA","X","Y",\\N,"XXXX",0,0,0,0,"U",\\N,"airport","x"\n')
    df = parse_openflights(p)
    assert df.to_dict("records") == [{"airport_code": "ORD", "timezone": "America/Chicago"}]

def test_overrides_win():
    of = pd.DataFrame({"airport_code": ["ORD"], "timezone": ["America/New_York"]})
    ov = pd.DataFrame({"airport_code": ["ORD"], "timezone": ["America/Chicago"], "note": ["fix"]})
    assert build_timezone_table(["ORD"], of, ov).set_index("airport_code").loc["ORD", "timezone"] == "America/Chicago"

def test_build_fails_on_missing_airport():
    of = pd.DataFrame({"airport_code": ["ORD"], "timezone": ["America/Chicago"]})
    with pytest.raises(ValueError, match="No time zone for airports: XWA, ZZZ"):
        build_timezone_table(["ORD", "ZZZ", "XWA"], of, pd.DataFrame(columns=["airport_code", "timezone", "note"]))
```
- [ ] **Step 3:** Run `.venv/bin/pytest tests/test_build_timezones.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4:** Implement `python/build_timezones.py`. Every time zone must be a valid `zoneinfo.ZoneInfo` key; raise `ValueError` naming any that aren't.
- [ ] **Step 5:** Run the tests. Expected: 3 passed.
- [ ] **Step 6:** Run `.venv/bin/python python/build_timezones.py`.
  - If it raises for missing airports, add each one to the overrides CSV with its IANA zone and a note (e.g. city), then rerun.
  - Expected: `airport_timezones.csv` with 365 rows.
- [ ] **Step 7:** Commit the script, the tests, both CSVs and `openflights_airports.dat` (a small public source file, kept so the build can be reproduced).

### Task 3: UTC conversion

**Files:**
- Create: `python/utc.py`, `tests/test_utc.py`

**Interfaces:**
- Consumes: `Dict[str, str]` from `load_timezones()`
- Produces:
  - `add_utc_columns(df: pd.DataFrame, tz: Dict[str, str]) -> Tuple[pd.DataFrame, Dict[str, int]]`
    - Adds `SchedDepUTC`, `SchedArrUTC`, `ActualDepUTC`, `ActualArrUTC`: tz-naive `datetime64[ns]` values that represent UTC.
    - Returns stats with keys `DST_Nonexistent`, `DST_Ambiguous`, `Arrival_Fallback`.
  - `check_arrivals(df: pd.DataFrame, tz: Dict[str, str]) -> pd.DataFrame`
    - Columns: `Dest`, `Flights`, `Matched`, `Match_Percent`.
    - Excludes the fallback rows (marked by a boolean column `ArrivalFallback` that `add_utc_columns` adds).

Rules (from spec §6.1):
- Departure: local `FlightDate + CRSDepTime`, where `2400` means 00:00 the next day. Localize per origin zone with `nonexistent="shift_forward"` and `ambiguous=True`, i.e. the first occurrence.
- Scheduled arrival: `SchedDepUTC + CRSElapsedTime` minutes.
  - When `CRSElapsedTime` is NaN or ≤ 0, use the fallback: `CRSArrTime` in the destination zone on `FlightDate`, plus 1 day if that is earlier than `SchedDepUTC`. Set `ArrivalFallback = True`.
- Actual departure = `SchedDepUTC + DepDelay`. Actual arrival = `SchedArrUTC + ArrDelay`. Either is NaT when its delay is NaN.
- Vectorize by grouping on the time zone, not by looping over rows.

- [ ] **Step 1: Write the failing tests.** Use a helper `row(origin, dest, date, crs_dep, elapsed, crs_arr, dep_delay=0, arr_delay=0)` that builds a 1-row frame. Use `tz = {"ORD": "America/Chicago", "LAX": "America/Los_Angeles", "JFK": "America/New_York", "LGA": "America/New_York", "PHX": "America/Phoenix"}`.
```python
def test_simple_winter():          # ORD 08:00 CST -> 14:00Z; +270 min -> 18:30Z
    out, _ = add_utc_columns(row("ORD","LAX","2024-01-15",800,270,1030), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-01-15 14:00")
    assert out.SchedArrUTC[0] == pd.Timestamp("2024-01-15 18:30")

def test_overnight_crosses_date(): # LAX 23:30 PST -> 07:30Z next day; +300 -> 12:30Z = 07:30 EST at JFK
    out, _ = add_utc_columns(row("LAX","JFK","2024-01-15",2330,300,730), tz)
    assert out.SchedArrUTC[0] == pd.Timestamp("2024-01-16 12:30")
    assert check_arrivals(out, tz).Match_Percent[0] == 100.0

def test_2400_is_next_midnight():
    out, _ = add_utc_columns(row("ORD","LAX","2024-01-15",2400,240,200), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-01-16 06:00")

def test_arizona_no_dst():         # PHX 09:00 in July = MST UTC-7
    out, _ = add_utc_columns(row("PHX","LAX","2024-07-01",900,90,1030), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-07-01 16:00")

def test_spring_forward_gap():     # 02:30 does not exist on 2024-03-10 in Chicago -> 03:00 CDT = 08:00Z
    out, stats = add_utc_columns(row("ORD","LAX","2024-03-10",230,240,430), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-03-10 08:00")
    assert stats["DST_Nonexistent"] == 1

def test_fall_back_ambiguous():    # 01:30 occurs twice on 2024-11-03; first occurrence is CDT -> 06:30Z
    out, stats = add_utc_columns(row("ORD","LAX","2024-11-03",130,240,330), tz)
    assert out.SchedDepUTC[0] == pd.Timestamp("2024-11-03 06:30")
    assert stats["DST_Ambiguous"] == 1

def test_arrival_fallback_when_no_elapsed():  # ORD 22:00 CST = 04:00Z Jan16; LGA 01:30 EST -> 06:30Z Jan16
    out, stats = add_utc_columns(row("ORD","LGA","2024-01-15",2200,float("nan"),130), tz)
    assert out.SchedArrUTC[0] == pd.Timestamp("2024-01-16 06:30")
    assert bool(out.ArrivalFallback[0]) and stats["Arrival_Fallback"] == 1

def test_actuals_null_when_delay_null():
    out, _ = add_utc_columns(row("ORD","LAX","2024-01-15",800,270,1030, dep_delay=float("nan"), arr_delay=float("nan")), tz)
    assert pd.isna(out.ActualDepUTC[0]) and pd.isna(out.ActualArrUTC[0])

def test_wrong_zone_fails_check(): # LAX mislabelled as Chicago -> 2-hour offset -> 0% match
    bad = dict(tz, LAX="America/Chicago")
    out, _ = add_utc_columns(row("ORD","LAX","2024-01-15",800,270,1030), bad)
    assert check_arrivals(out, bad).Match_Percent[0] == 0.0
```
- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_utc.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `python/utc.py`.
  - Count `DST_Nonexistent` by localizing once with `nonexistent="NaT"` and counting the NaT rows.
  - Count `DST_Ambiguous` by localizing once with `ambiguous="NaT"`.
- [ ] **Step 4:** Run the tests. Expected: 9 passed.
- [ ] **Step 5:** Commit.

### Task 4: Wire UTC and tail numbers into `clean_data.py`, then re-clean

**Files:**
- Modify: `python/clean_data.py` (`clean_file`, `main`)
- Create: `tests/test_clean_data.py`
- Outputs: refreshed Parquet, `docs/cleaning_report.csv` (new columns), `docs/timezone_check.csv`

**Interfaces:**
- Consumes: `add_utc_columns`, `check_arrivals`, `load_timezones`
- Produces:
  - `normalize_tail(s: pd.Series) -> pd.Series`: uppercase, strip whitespace, add `N` in front when the value doesn't start with `N`, keep missing values as missing
  - Parquet keeps `CancellationCode` (category) in addition to `CancellationReason`, and adds `SchedDepUTC`, `SchedArrUTC`, `ActualDepUTC`, `ActualArrUTC`, `ArrivalFallback`
  - Report columns added: `DST_Nonexistent`, `DST_Ambiguous`, `Arrival_Fallback`

- [ ] **Step 1: Write the failing tests:**
```python
def test_normalize_tail():
    s = pd.Series(["188NV", "n346FR", " N123AA ", pd.NA], dtype="string")
    assert normalize_tail(s).tolist()[:3] == ["N188NV", "N346FR", "N123AA"]
    assert pd.isna(normalize_tail(s)[3])

def test_clean_file_keeps_code_and_adds_utc():
    df, log = clean_file(RAW / "bts_flights_2024_01.csv")
    assert {"CancellationCode", "CancellationReason", "SchedDepUTC", "SchedArrUTC"} <= set(df.columns)
    assert (df.SchedArrUTC > df.SchedDepUTC).all()
    assert df.Tail_Number.dropna().str.startswith("N").all()
    assert log["Rows_Clean"] == 547271
```
- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_clean_data.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the changes in `clean_data.py`.
  - Load the time zones once in `main`.
  - Keep each month's `check_arrivals` result, then combine them per `Dest` across months, write `docs/timezone_check.csv`, and raise `RuntimeError` listing any airport under 99%.
- [ ] **Step 4:** Run the tests. Expected: 2 passed.
- [ ] **Step 5:** Run `.venv/bin/python python/clean_data.py --force`.
  - Expected: 32 files, total rows 18,809,411.
  - `timezone_check.csv` has 365 airports, all ≥ 99%.
  - If an airport fails, fix its override (Task 2) and rerun.
- [ ] **Step 6:** Commit the code, tests and the two reports.

### Task 5: MySQL install and schema SQL

**Files:**
- Create: `sql/schema/01_create_tables.sql`, `sql/schema/02_views.sql`, `.env.example`, `python/db.py`, `tests/test_schema.py`

**Interfaces:**
- Produces:
  - `db.connect(database: Optional[str] = None) -> pymysql.Connection`: reads `.env`, `local_infile=True`, `autocommit=False`, charset `utf8mb4`
  - `db.run_sql_file(conn, path: Path) -> None`: splits on `;` at line end and executes each statement

- [ ] **Step 1: Ask the user to confirm `brew install mysql`.** After a yes:
  - Run `brew install mysql` and `brew services start mysql`.
  - Add `local_infile=1` under `[mysqld]` in `$(brew --prefix)/etc/my.cnf` and restart.
  - Write `.env` with `MYSQL_HOST=127.0.0.1`, `MYSQL_PORT=3306`, `MYSQL_USER=root`, an empty `MYSQL_PASSWORD` (the Homebrew default) and `MYSQL_DATABASE=airline_ops`.
  - Mirror `.env` in `.env.example` with no values filled in.
  - Expected: `mysql -uroot -e "SHOW VARIABLES LIKE 'local_infile'"` shows `ON`.
- [ ] **Step 2:** Write `01_create_tables.sql`, exactly per spec §5.2–5.3.
  - It must be safe to run against any database name, so no `CREATE DATABASE` and no `USE` inside it.
  - Drop and create in dependency order: drop the fact table first, create the dimensions first.
  - Add column `COMMENT`s for the delay NULL rule (§6.5) and for the local-time `hhmm` columns.
- [ ] **Step 3:** Write `02_views.sql` per spec §5.4.
  - `v_ml_features` adds `prev_leg_arr_delay = LAG(arr_delay) OVER (PARTITION BY aircraft_id ORDER BY sched_dep_utc)`, computed over all flights before filtering to completed ones.
- [ ] **Step 4: Write the failing test** `tests/test_schema.py`. It runs against `airline_ops_test` and is skipped if the connection fails:
```python
def test_schema_creates_all_tables(test_db):
    tables = {r[0] for r in q(test_db, "SHOW FULL TABLES WHERE Table_type='BASE TABLE'")}
    assert tables == {"fact_flights","dim_date","dim_carrier","dim_carrier_history","dim_airport",
                      "dim_route","dim_aircraft","dim_time_block","dim_cancellation","dim_status"}
    views = {r[0] for r in q(test_db, "SHOW FULL TABLES WHERE Table_type='VIEW'")}
    assert views == {"v_dim_origin_airport","v_dim_dest_airport","v_flights","v_ml_features"}

def test_schema_is_rerunnable(test_db):
    apply_schema(test_db); apply_schema(test_db)   # no error
```
  - The `test_db` fixture goes in `conftest.py`: it creates `airline_ops_test` if missing, applies both SQL files, and yields a connection to it.
  - `conftest.py` also adds the helper `q(conn, sql: str, *params) -> List[tuple]`, which runs the query and returns `fetchall()`.
  - `apply_schema(conn)` lives in `db.py` and runs `01` then `02`.
- [ ] **Step 5:** Run `.venv/bin/pytest tests/test_schema.py -v`. Expected: 2 passed.
- [ ] **Step 6:** Commit everything except `.env`. Check with `git status` that `.env` is not listed.

### Task 6: Dimension builders

**Files:**
- Create: `python/dimensions.py`, `tests/test_dimensions.py`

**Interfaces:**
- Consumes: `read_lookup`, `parse_airport_description`, `parse_carrier_history`, `load_timezones`
- Produces. Each function returns a DataFrame whose columns are named and ordered exactly like the MySQL table.
  - `build_dim_date(start: str = "2024-01-01", end: str = "2026-12-31")`
  - `build_dim_carrier(codes: Iterable[str])`
  - `build_dim_carrier_history()`
  - `build_dim_airport(codes: Iterable[str], tz: Dict[str, str])`
  - `build_dim_route(flights: pd.DataFrame)`: input columns `Origin`, `Dest`, `Distance`, `FlightDate`; `route_id` starts at 1 in sorted `(origin, dest)` order
  - `build_dim_aircraft(flights: pd.DataFrame)`: input columns `Tail_Number`, `Reporting_Airline`, `FlightDate`; `aircraft_id` starts at 1 in sorted tail order
  - `build_dim_time_block()`, `build_dim_cancellation()`, `build_dim_status()`
  - `STATUS_IDS = {"On Time": 1, "Delayed": 2, "Cancelled": 3, "Diverted": 4}`
  - Builders that take codes raise `ValueError("Missing from <LOOKUP>: X, Y")` when codes are missing.

- [ ] **Step 1: Write the failing tests:**
```python
def test_dim_date_range_and_fields():
    d = build_dim_date()
    assert len(d) == 1096 and d.date_key.iloc[0] == 20240101
    r = d.set_index("date_key").loc[20240106]          # a Saturday
    assert (r.day_of_week, r.weekday_name, r.is_weekend, r.year_month) == (6, "Saturday", 1, "2024-01")

def test_dim_airport_split_and_tz():
    a = build_dim_airport(["ORD"], {"ORD": "America/Chicago"}).iloc[0]
    assert (a.city, a.state_code, a.state_name, a.timezone) == ("Chicago", "IL", "Illinois", "America/Chicago")

def test_dim_airport_missing_code_raises():
    with pytest.raises(ValueError, match="Missing from L_AIRPORT: QQQ"):
        build_dim_airport(["ORD", "QQQ"], {"ORD": "America/Chicago", "QQQ": "UTC"})

def test_dim_route_latest_distance():
    f = pd.DataFrame({"Origin": ["AGS","AGS"], "Dest": ["PHL","PHL"], "Distance": [583.0, 584.0],
                      "FlightDate": pd.to_datetime(["2024-04-07","2026-04-05"])})
    r = build_dim_route(f).iloc[0]
    assert (r.route_label, r.distance_miles, r.distance_group) == ("AGS-PHL", 584, 3)

def test_dim_aircraft_primary_carrier():
    f = pd.DataFrame({"Tail_Number": ["N1","N1","N1"], "Reporting_Airline": ["OO","OO","AA"],
                      "FlightDate": pd.to_datetime(["2024-01-01","2024-02-01","2024-03-01"])})
    a = build_dim_aircraft(f).iloc[0]
    assert (a.primary_carrier_code, a.flight_count, str(a.first_flight_date)[:10]) == ("OO", 3, "2024-01-01")

def test_dim_carrier_history_years():
    h = build_dim_carrier_history()
    assert h.duplicated(["carrier_code", "start_year"]).sum() == 0
    assert h.end_year.isna().any() and h.start_year.notna().all()

def test_time_block_day_part():
    t = build_dim_time_block().set_index("block_code")
    assert t.loc["0001-0559", "day_part"] == "Night" and t.loc["1800-1859", "day_part"] == "Evening"
```
- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_dimensions.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `python/dimensions.py`.
  - `distance_group` = the 250-mile band number: `min(distance // 250 + 1, 11)`, matching `L_DISTANCE_GROUP_250`.
  - Day parts: Night = hours 0–5, Morning = 6–11, Afternoon = 12–17, Evening = 18–23.
- [ ] **Step 4:** Run the tests. Expected: 7 passed.
- [ ] **Step 5:** Commit.

### Task 7: Loader

**Files:**
- Create: `python/load_mysql.py`, `tests/test_load_mysql.py`, `tests/fixtures/` (tiny Parquet written by a fixture, not committed as a binary)

**Interfaces:**
- Consumes: `db.connect`, `db.apply_schema`, the `dimensions.build_*` functions, `STATUS_IDS`
- Produces:
  - `load_dimensions(conn, flights_dir: Path) -> Tuple[Dict[Tuple[str, str], int], Dict[str, int]]`: builds and inserts every dimension, then returns the route and aircraft id maps
  - `to_fact_frame(df: pd.DataFrame, route_ids, aircraft_ids) -> pd.DataFrame`: columns in `fact_flights` order, without `flight_id`
  - `write_mysql_csv(df: pd.DataFrame, path: Path) -> None`: NULL written as `\N`, booleans as `0`/`1`, datetimes as `%Y-%m-%d %H:%M:%S`, UTF-8, no header, `\n` line endings
  - `load_month(conn, parquet_path: Path, route_ids, aircraft_ids) -> int`: one transaction that runs `DELETE` for the month's `date_key` range and then `LOAD DATA LOCAL INFILE`, commits, and returns the rows loaded
  - `verify(conn, report_csv: Path) -> pd.DataFrame`: per month, compares row, cancelled, diverted and delayed counts; raises `AssertionError` on any mismatch
  - `main(argv)`: flags `--database NAME` and `--months 2024_01,...`; default is all months into `airline_ops`

- [ ] **Step 1: Write the failing tests.** They use the `test_db` fixture and a `tiny_month` fixture, which writes `tiny_flights` (Task 1), passed through `clean_data`'s UTC and tail steps, to `tmp_path/bts_flights_2024_01.parquet`.
```python
def test_load_month_counts(test_db, tiny_month):
    rid, aid = load_dimensions(test_db, tiny_month.parent)
    assert load_month(test_db, tiny_month, rid, aid) == 6

def test_load_month_twice_no_duplicates(test_db, tiny_month):
    rid, aid = load_dimensions(test_db, tiny_month.parent)
    load_month(test_db, tiny_month, rid, aid); load_month(test_db, tiny_month, rid, aid)
    assert q(test_db, "SELECT COUNT(*) FROM fact_flights")[0][0] == 6

def test_nulls_load_as_null(test_db, tiny_month):
    rid, aid = load_dimensions(test_db, tiny_month.parent); load_month(test_db, tiny_month, rid, aid)
    rows = q(test_db, "SELECT arr_delay, carrier_delay, actual_arr_utc, aircraft_id FROM fact_flights WHERE is_cancelled=1")
    assert rows and all(v is None for v in rows[0][:3])
    assert q(test_db, "SELECT COUNT(*) FROM fact_flights WHERE aircraft_id IS NULL")[0][0] == 1

def test_airport_name_roundtrip_accents(test_db):
    expected = read_lookup("L_AIRPORT").pipe(lambda d: d[d.Description.str.contains("[À-ÿ]")]).iloc[0]
    insert_dim(test_db, "dim_airport", build_dim_airport([expected.Code], {expected.Code: "UTC"}))
    got = q(test_db, "SELECT airport_name FROM dim_airport WHERE airport_code=%s", expected.Code)[0][0]
    assert got == parse_airport_description(expected.Description)[2]

def test_cancelled_after_pushback_keeps_dep(test_db, tiny_month):
    ...  # tiny_flights' cancelled row has DepDelay=12 -> actual_dep_utc IS NOT NULL, dep_del15 = 0
```
  - `insert_dim(conn, table: str, df: pd.DataFrame) -> None` is a public helper in `load_mysql.py`, also used by `load_dimensions`.
  - Fill in the last test's assertions per its comment, and make sure `tiny_flights` includes that row.
- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_load_mysql.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `python/load_mysql.py`.
  - Write each month's CSV to a `tempfile.NamedTemporaryFile` and delete it afterwards.
  - On any error inside `load_month`, roll back and re-raise.
  - Insert dimensions with `executemany` in batches of 5,000.
- [ ] **Step 4:** Run the tests. Expected: 5 passed.
- [ ] **Step 5:** Commit.

### Task 8: Full load, verification and docs

**Files:**
- Create: `sql/checks/sanity_checks.sql`
- Modify: `README.md`
- Output: `docs/load_verification.csv`

- [ ] **Step 1:** Run `.venv/bin/python python/load_mysql.py` in the background (it takes minutes).
  - Expected: 32 months loaded; `verify` writes `docs/load_verification.csv` with every row matching; total 18,809,411.
- [ ] **Step 2:** Write `sql/checks/sanity_checks.sql` and run it. Expected results:
  - `SELECT COUNT(*) FROM fact_flights WHERE sched_arr_utc <= sched_dep_utc` → 0
  - January 2024 arrival-delayed share: DL = 0.189, AA = 0.294 (3 decimals; matches the earlier pandas result)
  - `SELECT COUNT(*) FROM dim_airport` → 365; `dim_route` → 7679; `dim_carrier` → 15
  - `SELECT COUNT(*) FROM v_ml_features` = completed flights, i.e. 18,809,411 − 303,116 − 52,698 = 18,453,597
- [ ] **Step 3:** Update `README.md`: project summary, the spec's Mermaid ER diagram, the rebuild commands in order (`build_timezones.py` → `clean_data.py` → `load_mysql.py`) and the folder layout.
- [ ] **Step 4:** Run `.venv/bin/pytest -v`. Expected: all tests pass.
- [ ] **Step 5:** Commit.
