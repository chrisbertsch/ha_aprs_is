"""Tests for the APRS symbol lookup helper (symbols.py)."""
from custom_components.aprs_is.symbols import aprs_symbol_name


class TestPrimaryTable:
    def test_car(self):
        assert aprs_symbol_name("/", ">") == "Car"

    def test_house(self):
        assert aprs_symbol_name("/", "-") == "House"

    def test_weather_station(self):
        assert aprs_symbol_name("/", "_") == "Weather Station"

    def test_digipeater(self):
        assert aprs_symbol_name("/", "#") == "Digipeater"

    def test_unknown_code_returns_raw(self):
        assert aprs_symbol_name("/", "~") == "/~"


class TestAlternateTable:
    def test_weather_station_alt(self):
        assert aprs_symbol_name("\\", "_") == "Weather Station (Alt)"

    def test_house_alt(self):
        assert aprs_symbol_name("\\", "-") == "House (Alt)"

    def test_train(self):
        assert aprs_symbol_name("\\", "=") == "Train"

    def test_unknown_code_returns_raw(self):
        assert aprs_symbol_name("\\", "~") == "\\~"


class TestSameCodeDifferentTables:
    def test_hyphen_primary_vs_alternate(self):
        primary = aprs_symbol_name("/", "-")
        alternate = aprs_symbol_name("\\", "-")
        assert primary == "House"
        assert alternate == "House (Alt)"
        assert primary != alternate

    def test_underscore_primary_vs_alternate(self):
        primary = aprs_symbol_name("/", "_")
        alternate = aprs_symbol_name("\\", "_")
        assert primary == "Weather Station"
        assert alternate == "Weather Station (Alt)"


class TestOverlaySymbols:
    def test_digit_overlay_known_code(self):
        # digit table char → looks up in alternate table, appends overlay
        result = aprs_symbol_name("0", "_")
        assert result == "Weather Station (Alt) (overlay: 0)"

    def test_letter_overlay_known_code(self):
        result = aprs_symbol_name("A", "^")
        assert result == "Aircraft (overlay: A)"

    def test_overlay_unknown_code_returns_raw_with_overlay(self):
        result = aprs_symbol_name("3", "~")
        assert result == "\\~ (overlay: 3)"

    def test_overlay_digit_9(self):
        result = aprs_symbol_name("9", "=")
        assert result == "Train (overlay: 9)"

    def test_overlay_letter_z(self):
        result = aprs_symbol_name("Z", "t")
        assert result == "Tornado (overlay: Z)"
