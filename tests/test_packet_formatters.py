"""Tests for _build_wx_packet and _build_object_packet in coordinator.py."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.aprs_is.const import APRS_TOCALL
from custom_components.aprs_is.coordinator import _build_object_packet, _build_wx_packet

_FIXED_DT = datetime(2026, 5, 18, 12, 34, 0, tzinfo=timezone.utc)
_FIXED_TS = "181234z"
_DT_PATH = "custom_components.aprs_is.coordinator.dt_util"


@pytest.fixture(autouse=True)
def freeze_time():
    with patch(_DT_PATH) as mock_dt:
        mock_dt.utcnow.return_value = _FIXED_DT
        yield mock_dt


@pytest.fixture
def hass():
    m = MagicMock()
    m.config.latitude = 32.999
    m.config.longitude = -97.4028
    return m


# ---------------------------------------------------------------------------
# _build_wx_packet
# ---------------------------------------------------------------------------

class TestBuildWxPacket:
    def _build(self, hass, data=None, **kwargs):
        return _build_wx_packet("KE5YIM-13", data or {}, hass, **kwargs)

    def test_header_format(self, hass):
        result = self._build(hass)
        assert result.startswith(f"KE5YIM-13>{APRS_TOCALL},TCPIP*:@")

    def test_timestamp_from_utcnow(self, hass):
        result = self._build(hass)
        assert _FIXED_TS in result

    def test_hass_location_used_when_no_override(self, hass):
        result = self._build(hass)
        assert "3259.94N/09724.17W" in result

    def test_lat_lon_override_replaces_hass_location(self, hass):
        result = self._build(hass, lat_override=51.5074, lon_override=-0.1278)
        assert "5130.44N" in result
        assert "00007.67W" in result
        assert "3259.94N" not in result

    def test_missing_temperature_uses_placeholder(self, hass):
        result = self._build(hass)
        assert "t..." in result

    def test_temperature_encoded(self, hass):
        result = self._build(hass, {"temperature_f": 72})
        assert "t072" in result

    def test_missing_humidity_uses_placeholder(self, hass):
        result = self._build(hass)
        assert "h.." in result

    def test_humidity_normal(self, hass):
        result = self._build(hass, {"humidity": 65})
        assert "h65" in result

    def test_humidity_100_encodes_as_00(self, hass):
        # APRS spec: 100% relative humidity encodes as 00
        result = self._build(hass, {"humidity": 100})
        assert "h00" in result

    def test_missing_pressure_uses_placeholder(self, hass):
        result = self._build(hass)
        assert "b....." in result

    def test_pressure_encoded(self, hass):
        # 1013.2 hPa → stored as tenths: 10132
        result = self._build(hass, {"pressure_mb": 1013.2})
        assert "b10132" in result

    def test_luminosity_under_1000_uses_uppercase_L(self, hass):
        result = self._build(hass, {"luminosity": 750})
        assert "L750" in result

    def test_luminosity_1000_uses_lowercase_l_offset(self, hass):
        # ≥1000 W/m²: lowercase l, value is luminosity-1000
        result = self._build(hass, {"luminosity": 1000})
        assert "l000" in result

    def test_luminosity_1500(self, hass):
        result = self._build(hass, {"luminosity": 1500})
        assert "l500" in result

    def test_missing_luminosity_omitted_from_body(self, hass):
        result = self._build(hass)
        body = result.split(":", 1)[1]
        assert "L" not in body
        assert "l" not in body

    def test_wind_fields(self, hass):
        result = self._build(hass, {"wind_dir": 270, "wind_speed_mph": 12, "wind_gust_mph": 18})
        assert "270/012g018" in result

    def test_rain_fields(self, hass):
        result = self._build(hass, {
            "rain_1h_hundredths": 10,
            "rain_24h_hundredths": 25,
            "rain_midnight_hundredths": 5,
        })
        assert "r010p025P005" in result

    def test_comment_appended(self, hass):
        result = self._build(hass, comment="Home Assistant")
        assert result.endswith("Home Assistant")

    def test_full_packet(self, hass):
        data = {
            "temperature_f": 72,
            "humidity": 65,
            "pressure_mb": 1013.2,
            "wind_speed_mph": 12,
            "wind_dir": 270,
            "wind_gust_mph": 18,
            "rain_1h_hundredths": 10,
            "rain_24h_hundredths": 25,
            "rain_midnight_hundredths": 5,
            "luminosity": 750,
        }
        result = self._build(hass, data, comment="Home Assistant")
        expected = (
            f"KE5YIM-13>{APRS_TOCALL},TCPIP*:"
            "@181234z3259.94N/09724.17W_"
            "270/012g018t072r010p025P005h65b10132L750"
            "Home Assistant"
        )
        assert result == expected


# ---------------------------------------------------------------------------
# _build_object_packet
# ---------------------------------------------------------------------------

class TestBuildObjectPacket:
    def _build(self, **kwargs):
        defaults = dict(
            sender="KE5YIM",
            name="SHELTER1",
            lat=32.999,
            lon=-97.4028,
            symbol_table="/",
            symbol_code="h",
            comment="",
            killed=False,
        )
        defaults.update(kwargs)
        return _build_object_packet(**defaults)

    def test_header_format(self):
        result = self._build()
        assert result.startswith(f"KE5YIM>{APRS_TOCALL},TCPIP*:;")

    def test_alive_object_uses_asterisk(self):
        result = self._build(killed=False)
        assert "SHELTER1 *" in result

    def test_killed_object_uses_underscore(self):
        result = self._build(killed=True)
        assert "SHELTER1 _" in result

    def test_short_name_padded_to_9(self):
        result = self._build(name="SHORT")
        assert ";SHORT    *" in result   # 4 spaces to reach 9 chars

    def test_long_name_truncated_to_9(self):
        result = self._build(name="TOOLONGNAME")
        assert ";TOOLONGNA*" in result

    def test_name_exactly_9_not_padded(self):
        result = self._build(name="SHELTER12")
        assert ";SHELTER12*" in result

    def test_timestamp_in_packet(self):
        result = self._build()
        assert _FIXED_TS in result

    def test_coordinates_encoded(self):
        result = self._build()
        assert "3259.94N" in result
        assert "09724.17W" in result

    def test_symbol_table_between_lat_and_lon(self):
        # Format: {lat}{symbol_table}{lon}{symbol_code}
        result = self._build(symbol_table="/", symbol_code="h")
        assert "3259.94N/09724.17Wh" in result

    def test_comment_appended(self):
        result = self._build(comment="Emergency shelter")
        assert result.endswith("Emergency shelter")

    def test_full_alive_packet(self):
        result = self._build(comment="test")
        expected = (
            f"KE5YIM>{APRS_TOCALL},TCPIP*:"
            ";SHELTER1 *181234z"
            "3259.94N/09724.17Wh"
            "test"
        )
        assert result == expected

    def test_full_killed_packet(self):
        result = self._build(killed=True)
        expected = (
            f"KE5YIM>{APRS_TOCALL},TCPIP*:"
            ";SHELTER1 _181234z"
            "3259.94N/09724.17Wh"
        )
        assert result == expected
