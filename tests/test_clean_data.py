import pandas as pd

from clean_data import RAW, clean_file, normalize_tail


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
