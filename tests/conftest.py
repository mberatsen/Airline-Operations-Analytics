import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

NAN = float("nan")

# Column order produced by clean_data.clean_file
COLUMN_ORDER = [
    "Year", "Quarter", "Month", "DayofMonth", "DayOfWeek", "FlightDate",
    "Reporting_Airline", "Tail_Number", "Flight_Number_Reporting_Airline",
    "Origin", "OriginCityName", "OriginState",
    "Dest", "DestCityName", "DestState", "Distance",
    "CRSDepTime", "DepTime", "DepDelay", "DepDel15", "DepTimeBlk", "TaxiOut",
    "CRSArrTime", "ArrTime", "ArrDelay", "ArrDel15", "TaxiIn",
    "Cancelled", "Diverted",
    "CRSElapsedTime", "ActualElapsedTime", "AirTime",
    "CarrierDelay", "WeatherDelay", "NASDelay", "SecurityDelay",
    "LateAircraftDelay",
    "CancellationCode", "CancellationReason", "FlightStatus", "DepHour", "ArrHour",
]


def _row(**kw):
    base = dict(
        Year=2024, Quarter=1, Month=1, DayofMonth=1, DayOfWeek=1,
        FlightDate="2024-01-01", Tail_Number="N123AA",
        DepDel15=0.0, ArrDel15=0.0, Cancelled=False, Diverted=False,
        CarrierDelay=0.0, WeatherDelay=0.0, NASDelay=0.0,
        SecurityDelay=0.0, LateAircraftDelay=0.0,
        CancellationCode=None, CancellationReason=None, FlightStatus="On Time",
    )
    base.update(kw)
    return base


def _build():
    rows = [
        # 1. on time
        _row(Reporting_Airline="AA", Tail_Number="N123AA",
             Flight_Number_Reporting_Airline=100,
             Origin="ORD", OriginCityName="Chicago, IL", OriginState="IL",
             Dest="LAX", DestCityName="Los Angeles, CA", DestState="CA",
             Distance=1744.0, CRSDepTime=900, DepTime=855, DepDelay=-5.0,
             DepTimeBlk="0900-0959", TaxiOut=15.0, CRSArrTime=1130,
             ArrTime=1120, ArrDelay=-10.0, TaxiIn=7.0,
             CRSElapsedTime=270.0, ActualElapsedTime=265.0, AirTime=243.0),
        # 2. delayed (causes sum to ArrDelay = 50)
        _row(DayofMonth=2, DayOfWeek=2, FlightDate="2024-01-02",
             Reporting_Airline="DL", Tail_Number="N321DL",
             Flight_Number_Reporting_Airline=200,
             Origin="ATL", OriginCityName="Atlanta, GA", OriginState="GA",
             Dest="JFK", DestCityName="New York, NY", DestState="NY",
             Distance=760.0, CRSDepTime=1400, DepTime=1450, DepDelay=50.0,
             DepDel15=1.0, DepTimeBlk="1400-1459", TaxiOut=20.0,
             CRSArrTime=1620, ArrTime=1710, ArrDelay=50.0, ArrDel15=1.0,
             TaxiIn=9.0, CRSElapsedTime=140.0, ActualElapsedTime=140.0,
             AirTime=111.0, CarrierDelay=20.0, WeatherDelay=0.0,
             NASDelay=10.0, SecurityDelay=0.0, LateAircraftDelay=20.0,
             FlightStatus="Delayed"),
        # 3. cancelled (weather)
        _row(DayofMonth=3, DayOfWeek=3, FlightDate="2024-01-03",
             Reporting_Airline="AA", Tail_Number="N456AA",
             Flight_Number_Reporting_Airline=300,
             Origin="DEN", OriginCityName="Denver, CO", OriginState="CO",
             Dest="ORD", DestCityName="Chicago, IL", DestState="IL",
             Distance=888.0, CRSDepTime=1800, DepTime=NAN, DepDelay=12.0,
             DepTimeBlk="1800-1859", TaxiOut=NAN, CRSArrTime=2125,
             ArrTime=NAN, ArrDelay=NAN, TaxiIn=NAN, CRSElapsedTime=145.0,
             ActualElapsedTime=NAN, AirTime=NAN, Cancelled=True,
             CarrierDelay=NAN, WeatherDelay=NAN, NASDelay=NAN,
             SecurityDelay=NAN, LateAircraftDelay=NAN,
             CancellationCode="B", CancellationReason="Weather",
             FlightStatus="Cancelled"),
        # 4. diverted
        _row(DayofMonth=4, DayOfWeek=4, FlightDate="2024-01-04",
             Reporting_Airline="DL", Tail_Number="N654DL",
             Flight_Number_Reporting_Airline=400,
             Origin="LAX", OriginCityName="Los Angeles, CA",
             OriginState="CA", Dest="ATL", DestCityName="Atlanta, GA",
             DestState="GA", Distance=1947.0, CRSDepTime=700, DepTime=705,
             DepDelay=5.0, DepTimeBlk="0700-0759", TaxiOut=14.0,
             CRSArrTime=1500, ArrTime=NAN, ArrDelay=NAN, TaxiIn=NAN,
             CRSElapsedTime=240.0, ActualElapsedTime=NAN, AirTime=NAN,
             Diverted=True, CarrierDelay=NAN, WeatherDelay=NAN,
             NASDelay=NAN, SecurityDelay=NAN, LateAircraftDelay=NAN,
             FlightStatus="Diverted"),
        # 5. completed, missing tail number
        _row(DayofMonth=5, DayOfWeek=5, FlightDate="2024-01-05",
             Reporting_Airline="AA", Tail_Number=pd.NA,
             Flight_Number_Reporting_Airline=500,
             Origin="JFK", OriginCityName="New York, NY", OriginState="NY",
             Dest="DEN", DestCityName="Denver, CO", DestState="CO",
             Distance=1626.0, CRSDepTime=1000, DepTime=1002, DepDelay=2.0,
             DepTimeBlk="1000-1059", TaxiOut=18.0, CRSArrTime=1315,
             ArrTime=1310, ArrDelay=-5.0, TaxiIn=6.0,
             CRSElapsedTime=275.0, ActualElapsedTime=268.0, AirTime=244.0),
        # 6. Allegiant, tail 188NV
        _row(DayofMonth=6, DayOfWeek=6, FlightDate="2024-01-06",
             Reporting_Airline="G4", Tail_Number="188NV",
             Flight_Number_Reporting_Airline=600,
             Origin="LAS", OriginCityName="Las Vegas, NV", OriginState="NV",
             Dest="DEN", DestCityName="Denver, CO", DestState="CO",
             Distance=628.0, CRSDepTime=2330, DepTime=2335, DepDelay=5.0,
             DepTimeBlk="2300-2359", TaxiOut=12.0, CRSArrTime=200,
             ArrTime=205, ArrDelay=5.0, TaxiIn=5.0,
             CRSElapsedTime=90.0, ActualElapsedTime=90.0, AirTime=73.0),
    ]
    df = pd.DataFrame(rows)
    df["FlightDate"] = pd.to_datetime(df["FlightDate"], format="%Y-%m-%d")

    types = {
        "Year": "int16", "Quarter": "int8", "Month": "int8",
        "DayofMonth": "int8", "DayOfWeek": "int8",
        "Reporting_Airline": "category", "Tail_Number": "string",
        "Flight_Number_Reporting_Airline": "Int32",
        "Origin": "category", "OriginCityName": "category",
        "OriginState": "category", "Dest": "category",
        "DestCityName": "category", "DestState": "category",
        "Distance": "float32",
        "CRSDepTime": "Int16", "DepTime": "Int16",
        "CRSArrTime": "Int16", "ArrTime": "Int16",
        "DepDelay": "float32", "DepDel15": "float32", "TaxiOut": "float32",
        "ArrDelay": "float32", "ArrDel15": "float32", "TaxiIn": "float32",
        "DepTimeBlk": "category", "Cancelled": "bool", "Diverted": "bool",
        "CRSElapsedTime": "float32", "ActualElapsedTime": "float32",
        "AirTime": "float32",
        "CarrierDelay": "float32", "WeatherDelay": "float32",
        "NASDelay": "float32", "SecurityDelay": "float32",
        "LateAircraftDelay": "float32",
        "CancellationCode": "category",
        "CancellationReason": "category", "FlightStatus": "category",
    }
    df = df.astype(types)
    df = df[COLUMN_ORDER[:-2]]
    df["DepHour"] = ((df["CRSDepTime"] // 100) % 24).astype("Int8")
    df["ArrHour"] = ((df["CRSArrTime"] // 100) % 24).astype("Int8")
    return df


@pytest.fixture
def tiny_flights():
    return _build()
