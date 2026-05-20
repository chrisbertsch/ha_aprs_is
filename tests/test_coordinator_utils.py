"""Tests for pure-logic helper functions in coordinator.py."""
import pytest

from custom_components.aprs_is.const import (
    PACKET_TYPE_BULLETIN,
    PACKET_TYPE_MESSAGE,
    PACKET_TYPE_OBJECT,
    PACKET_TYPE_POSITION,
    PACKET_TYPE_STATUS,
    PACKET_TYPE_WEATHER,
)
from custom_components.aprs_is.coordinator import (
    _classify_packet,
    _lat_to_aprs,
    _lon_to_aprs,
)


# ---------------------------------------------------------------------------
# _lat_to_aprs
# ---------------------------------------------------------------------------

class TestLatToAprs:
    def test_northern_hemisphere(self):
        # 32.999° = 32° 59.94' N  (matches "3259.94N" in the APRS spec example)
        assert _lat_to_aprs(32.999) == "3259.94N"

    def test_southern_hemisphere(self):
        assert _lat_to_aprs(-33.5) == "3330.00S"

    def test_equator(self):
        assert _lat_to_aprs(0.0) == "0000.00N"

    def test_negative_zero_is_south(self):
        # -0.5° rounds toward South, degrees zero — two-digit zero padding required
        assert _lat_to_aprs(-0.5) == "0030.00S"

    def test_london_latitude(self):
        assert _lat_to_aprs(51.5074) == "5130.44N"

    def test_degree_field_zero_padded(self):
        # Single-digit degree must still produce two digits
        result = _lat_to_aprs(5.0)
        assert result[:2] == "05"

    def test_minutes_field_format(self):
        # Minutes field is always mm.dd (5 chars total including decimal point)
        result = _lat_to_aprs(32.999)
        minutes_str = result[2:7]   # e.g. "59.94"
        assert len(minutes_str) == 5
        assert minutes_str[2] == "."

    def test_direction_suffix(self):
        assert _lat_to_aprs(10.0)[-1] == "N"
        assert _lat_to_aprs(-10.0)[-1] == "S"

    def test_total_length(self):
        # DDmm.mmX → 8 characters
        assert len(_lat_to_aprs(32.999)) == 8
        assert len(_lat_to_aprs(-33.5)) == 8


# ---------------------------------------------------------------------------
# _lon_to_aprs
# ---------------------------------------------------------------------------

class TestLonToAprs:
    def test_western_hemisphere(self):
        # -97.4028° = 097° 24.17' W
        assert _lon_to_aprs(-97.4028) == "09724.17W"

    def test_eastern_hemisphere(self):
        # Paris ≈ 2.3522°E → 002° 21.13' E
        assert _lon_to_aprs(2.3522) == "00221.13E"

    def test_prime_meridian(self):
        assert _lon_to_aprs(0.0) == "00000.00E"

    def test_western_near_prime(self):
        # -0.1278° (near London, slightly west) → 000° 07.67' W
        assert _lon_to_aprs(-0.1278) == "00007.67W"

    def test_san_francisco(self):
        assert _lon_to_aprs(-122.4194) == "12225.16W"

    def test_degree_field_zero_padded_to_three(self):
        # Single-digit degree must produce three digits
        result = _lon_to_aprs(2.3522)
        assert result[:3] == "002"

    def test_minutes_field_format(self):
        result = _lon_to_aprs(-97.4028)
        minutes_str = result[3:8]   # e.g. "24.17"
        assert len(minutes_str) == 5
        assert minutes_str[2] == "."

    def test_direction_suffix(self):
        assert _lon_to_aprs(10.0)[-1] == "E"
        assert _lon_to_aprs(-10.0)[-1] == "W"

    def test_total_length(self):
        # DDDmm.mmX → 9 characters
        assert len(_lon_to_aprs(-97.4028)) == 9
        assert len(_lon_to_aprs(2.3522)) == 9


# ---------------------------------------------------------------------------
# _classify_packet
# ---------------------------------------------------------------------------

class TestClassifyPacket:
    # --- basic type classification ---

    def test_direct_message(self):
        assert _classify_packet({"addresse": "W1ABC"}) == PACKET_TYPE_MESSAGE

    def test_bulletin_bln_prefix(self):
        assert _classify_packet({"addresse": "BLN1"}) == PACKET_TYPE_BULLETIN

    def test_bulletin_named(self):
        assert _classify_packet({"addresse": "BLNTEST"}) == PACKET_TYPE_BULLETIN

    def test_weather(self):
        assert _classify_packet({"weather": {"temperature": 25.0}}) == PACKET_TYPE_WEATHER

    def test_object(self):
        assert _classify_packet({"object_name": "SHELTER1"}) == PACKET_TYPE_OBJECT

    def test_position(self):
        assert _classify_packet({"latitude": 32.0, "longitude": -97.0}) == PACKET_TYPE_POSITION

    def test_status(self):
        assert _classify_packet({"status": "testing 1-2-3"}) == PACKET_TYPE_STATUS

    def test_unknown(self):
        assert _classify_packet({}) == "unknown"
        assert _classify_packet({"raw": "garbage"}) == "unknown"

    # --- addresse normalisation ---

    def test_addresse_stripped_and_uppercased(self):
        # aprslib sometimes pads the addressee field with spaces
        assert _classify_packet({"addresse": "  bln0  "}) == PACKET_TYPE_BULLETIN
        assert _classify_packet({"addresse": "  w1abc  "}) == PACKET_TYPE_MESSAGE

    # --- priority ordering ---

    def test_message_beats_weather(self):
        assert _classify_packet({"addresse": "W1ABC", "weather": {}}) == PACKET_TYPE_MESSAGE

    def test_message_beats_position(self):
        assert _classify_packet({"addresse": "W1ABC", "latitude": 32.0}) == PACKET_TYPE_MESSAGE

    def test_weather_beats_position(self):
        assert _classify_packet({"weather": {}, "latitude": 32.0}) == PACKET_TYPE_WEATHER

    def test_weather_beats_object(self):
        assert _classify_packet({"weather": {}, "object_name": "X"}) == PACKET_TYPE_WEATHER

    def test_object_beats_position(self):
        assert _classify_packet({"object_name": "X", "latitude": 32.0}) == PACKET_TYPE_OBJECT

    def test_position_beats_status(self):
        assert _classify_packet({"latitude": 32.0, "status": "X"}) == PACKET_TYPE_POSITION
