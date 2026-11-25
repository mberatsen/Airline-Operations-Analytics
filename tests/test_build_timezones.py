import pandas as pd
import pytest

from build_timezones import airport_codes_from_raw, build_timezone_table, parse_openflights


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


def test_airport_codes_from_raw_reads_origin_and_dest(tmp_path):
    (tmp_path / "a.csv").write_text("Origin,Dest,Other\nORD,LAX,1\nLAX,ORD,2\n")
    (tmp_path / "b.csv").write_text("Origin,Dest,Other\nDEN,JFK,3\n")
    assert airport_codes_from_raw(tmp_path) == {"ORD", "LAX", "DEN", "JFK"}


def test_airport_codes_from_raw_requires_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        airport_codes_from_raw(tmp_path)
