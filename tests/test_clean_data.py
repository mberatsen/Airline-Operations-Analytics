import pandas as pd
import pytest

from clean_data import RAW, clean_file, normalize_tail, save_timezone_check


def test_normalize_tail():
    s = pd.Series(["188NV", "n346FR", " N123AA ", pd.NA, ""], dtype="string")
    assert normalize_tail(s).tolist()[:3] == ["N188NV", "N346FR", "N123AA"]
    assert pd.isna(normalize_tail(s)[3])
    assert pd.isna(normalize_tail(s)[4])


def test_clean_file_keeps_code_and_adds_utc():
    df, log = clean_file(RAW / "bts_flights_2024_01.csv")
    assert {"CancellationCode", "CancellationReason", "SchedDepUTC", "SchedArrUTC"} <= set(df.columns)
    assert (df.SchedArrUTC > df.SchedDepUTC).all()
    assert df.Tail_Number.dropna().str.startswith("N").all()
    assert log["Rows_Clean"] == 547271


def _checks(matched):
    return [pd.DataFrame({"Dest": ["AAA", "BBB"], "Flights": [100, 100],
                          "Matched": [100, matched], "Match_Percent": [100.0, float(matched)]})]


def test_timezone_check_full_run_writes_and_raises(tmp_path):
    path = tmp_path / "tz.csv"
    with pytest.raises(RuntimeError, match="BBB"):
        save_timezone_check(_checks(90), True, path)
    assert path.exists()
    assert pd.read_csv(path).iloc[0]["Dest"] == "BBB"


def test_timezone_check_full_run_ok(tmp_path):
    path = tmp_path / "tz.csv"
    assert len(save_timezone_check(_checks(100), True, path)) == 2


def test_timezone_check_partial_run_leaves_file(tmp_path, capsys):
    path = tmp_path / "tz.csv"
    path.write_text("keep")
    assert save_timezone_check(_checks(50), False, path) is None   # 100 flights: too few to judge
    assert path.read_text() == "keep"
    assert "NOT updated" in capsys.readouterr().out


def test_timezone_check_partial_run_raises_for_bad_large_airport(tmp_path):
    path = tmp_path / "tz.csv"
    path.write_text("keep")
    checks = [pd.DataFrame({"Dest": ["AAA", "BBB"], "Flights": [150, 100],
                            "Matched": [150, 50], "Match_Percent": [100.0, 50.0]}),
              pd.DataFrame({"Dest": ["BBB"], "Flights": [150], "Matched": [100],
                            "Match_Percent": [66.67]})]
    with pytest.raises(RuntimeError, match="BBB"):
        save_timezone_check(checks, False, path)
    assert path.read_text() == "keep"
