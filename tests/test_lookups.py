from lookups import (
    parse_airport_description,
    parse_carrier_history,
    read_lookup,
)


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
