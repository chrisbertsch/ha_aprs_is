"""Coordinator tests using a real HA instance (pytest-homeassistant-custom-component)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.aprs_is.const import (
    CONF_CALLSIGN,
    CONF_KISS_HOST,
    CONF_PASSCODE,
    CONF_STATIONS,
    CONF_TX_PRIMARY,
    CONF_WEATHER_STATIONS,
    DOMAIN,
    EVENT_PACKET_SENT,
    TRANSPORT_BOTH,
    TX_PRIMARY_APRS_IS,
    TX_PRIMARY_KISS,
)
from custom_components.aprs_is.coordinator import AprsIsCoordinator

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BASE_DATA = {
    CONF_CALLSIGN: "KE5YIM",
    CONF_PASSCODE: "12345",
}


def _make_entry(hass: HomeAssistant, options: dict | None = None, data: dict | None = None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**_BASE_DATA, **(data or {})},
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


def _make_coordinator(hass: HomeAssistant, options: dict | None = None, data: dict | None = None):
    return AprsIsCoordinator(hass, _make_entry(hass, options=options, data=data))


# ---------------------------------------------------------------------------
# _build_filter
# ---------------------------------------------------------------------------

class TestBuildFilter:
    def test_no_stations_only_g_term(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        assert coord._build_filter() == "#filter g/KE5YIM"

    def test_callsign_uppercased_in_g_term(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, data={**_BASE_DATA, CONF_CALLSIGN: "ke5yim"})
        assert "g/KE5YIM" in coord._build_filter()

    def test_stations_produce_b_term(self, hass: HomeAssistant):
        opts = {CONF_STATIONS: [{"callsign": "W1ABC", "position_type": "none"}]}
        coord = _make_coordinator(hass, options=opts)
        result = coord._build_filter()
        assert "b/W1ABC" in result

    def test_stations_sorted_alphabetically(self, hass: HomeAssistant):
        opts = {CONF_STATIONS: [
            {"callsign": "W1ZZZ", "position_type": "none"},
            {"callsign": "W1AAA", "position_type": "none"},
        ]}
        coord = _make_coordinator(hass, options=opts)
        assert "b/W1AAA/W1ZZZ" in coord._build_filter()

    def test_weather_stations_included_in_b_term(self, hass: HomeAssistant):
        opts = {CONF_WEATHER_STATIONS: [{"callsign": "W1WX"}]}
        coord = _make_coordinator(hass, options=opts)
        assert "b/W1WX" in coord._build_filter()

    def test_stations_and_wx_merged_and_sorted(self, hass: HomeAssistant):
        opts = {
            CONF_STATIONS: [{"callsign": "W1ZZZ", "position_type": "none"}],
            CONF_WEATHER_STATIONS: [{"callsign": "W1AAA"}],
        }
        coord = _make_coordinator(hass, options=opts)
        assert "b/W1AAA/W1ZZZ" in coord._build_filter()

    def test_full_filter_term_order(self, hass: HomeAssistant):
        opts = {CONF_STATIONS: [{"callsign": "W1ABC", "position_type": "none"}]}
        coord = _make_coordinator(hass, options=opts)
        result = coord._build_filter()
        # b/ before g/
        assert result.index("b/") < result.index("g/")


# ---------------------------------------------------------------------------
# _tx_order
# ---------------------------------------------------------------------------

class TestTxOrder:
    def test_default_is_aprs_is_first(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        assert coord._tx_order() == [TX_PRIMARY_APRS_IS, TX_PRIMARY_KISS]

    def test_aprs_is_primary_explicit(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, options={CONF_TX_PRIMARY: TX_PRIMARY_APRS_IS})
        assert coord._tx_order() == [TX_PRIMARY_APRS_IS, TX_PRIMARY_KISS]

    def test_kiss_primary(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, options={CONF_TX_PRIMARY: TX_PRIMARY_KISS})
        assert coord._tx_order() == [TX_PRIMARY_KISS, TX_PRIMARY_APRS_IS]


# ---------------------------------------------------------------------------
# is_my_callsign
# ---------------------------------------------------------------------------

class TestIsMyCallsign:
    def test_exact_match(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        assert coord.is_my_callsign("KE5YIM") is True

    def test_different_ssid_same_base(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        assert coord.is_my_callsign("KE5YIM-9") is True

    def test_login_has_ssid_station_matches_base(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, data={**_BASE_DATA, CONF_CALLSIGN: "KE5YIM-1"})
        assert coord.is_my_callsign("KE5YIM-9") is True

    def test_different_callsign(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        assert coord.is_my_callsign("W1ABC") is False

    def test_case_insensitive(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        assert coord.is_my_callsign("ke5yim-5") is True


# ---------------------------------------------------------------------------
# _next_msg_id
# ---------------------------------------------------------------------------

class TestNextMsgId:
    def test_starts_at_one(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        assert coord._next_msg_id() == "00001"

    def test_increments(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        coord._next_msg_id()
        assert coord._next_msg_id() == "00002"

    def test_zero_padded_to_five_digits(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        assert len(coord._next_msg_id()) == 5

    def test_max_value_is_99998(self, hass: HomeAssistant):
        # modulo is 99999, so valid IDs are 00000–99998
        coord = _make_coordinator(hass)
        coord._msg_id_counter = 99997
        assert coord._next_msg_id() == "99998"

    def test_wraps_after_99998(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        coord._msg_id_counter = 99998
        assert coord._next_msg_id() == "00000"


# ---------------------------------------------------------------------------
# _is_duplicate_message
# ---------------------------------------------------------------------------

class TestIsDuplicateMessage:
    def test_first_occurrence_not_duplicate(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        assert coord._is_duplicate_message("KE5YIM", "W1ABC", "001") is False

    def test_second_occurrence_is_duplicate(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        coord._is_duplicate_message("KE5YIM", "W1ABC", "001")
        assert coord._is_duplicate_message("KE5YIM", "W1ABC", "001") is True

    def test_different_msgid_not_duplicate(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        coord._is_duplicate_message("KE5YIM", "W1ABC", "001")
        assert coord._is_duplicate_message("KE5YIM", "W1ABC", "002") is False

    def test_different_sender_not_duplicate(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        coord._is_duplicate_message("KE5YIM", "W1ABC", "001")
        assert coord._is_duplicate_message("KE5YIM", "W1DEF", "001") is False


# ---------------------------------------------------------------------------
# _check_rate_limit
# ---------------------------------------------------------------------------

class TestCheckRateLimit:
    def test_limit_zero_always_passes(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)   # DEFAULT_EVENT_RATE_LIMIT = 0
        for _ in range(100):
            assert coord._check_rate_limit() is True
        assert coord.events_dropped == 0

    def test_within_limit_passes(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, options={"event_rate_limit": 5})
        for _ in range(5):
            assert coord._check_rate_limit() is True

    def test_at_limit_drops_and_counts(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, options={"event_rate_limit": 3})
        for _ in range(3):
            coord._check_rate_limit()
        assert coord._check_rate_limit() is False
        assert coord.events_dropped == 1

    def test_multiple_drops_counted(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, options={"event_rate_limit": 2})
        coord._check_rate_limit()
        coord._check_rate_limit()
        coord._check_rate_limit()
        coord._check_rate_limit()
        assert coord.events_dropped == 2


# ---------------------------------------------------------------------------
# _send — transport routing
# ---------------------------------------------------------------------------

class TestSend:
    def _aprs_coord(self, hass, **opts):
        """Coordinator with APRS-IS in a simulated connected state."""
        coord = _make_coordinator(hass, options=opts)
        coord._connected = True
        coord._writer = MagicMock()
        coord._raw_write = AsyncMock()
        return coord

    def _kiss_coord(self, hass, **opts):
        """Coordinator with KISS TNC in a simulated connected state."""
        coord = _make_coordinator(hass, options={
            CONF_KISS_HOST: "localhost",
            **opts,
        })
        coord._kiss_connected = True
        coord._kiss_write_packet = AsyncMock()
        return coord

    async def test_aprs_is_connected_uses_aprs_is(self, hass: HomeAssistant):
        coord = self._aprs_coord(hass)
        await coord._send("KE5YIM>APZHA:test")
        coord._raw_write.assert_awaited_once()
        assert coord.tx_packets == 1

    async def test_aprs_is_increments_tx_packets(self, hass: HomeAssistant):
        coord = self._aprs_coord(hass)
        await coord._send("KE5YIM>APZHA:test")
        await coord._send("KE5YIM>APZHA:test2")
        assert coord.tx_packets == 2

    async def test_aprs_is_disconnected_falls_back_to_kiss(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, options={CONF_KISS_HOST: "localhost"})
        coord._connected = False
        coord._kiss_connected = True
        coord._kiss_write_packet = AsyncMock()
        await coord._send("KE5YIM>APZHA:test")
        coord._kiss_write_packet.assert_awaited_once()
        assert coord.kiss_tx_packets == 1

    async def test_receive_only_passcode_uses_kiss(self, hass: HomeAssistant):
        coord = _make_coordinator(
            hass,
            data={**_BASE_DATA, CONF_PASSCODE: str(-1)},
            options={CONF_KISS_HOST: "localhost"},
        )
        coord._kiss_connected = True
        coord._kiss_write_packet = AsyncMock()
        await coord._send("KE5YIM>APZHA:test")
        coord._kiss_write_packet.assert_awaited_once()
        assert coord.tx_packets == 0

    async def test_neither_connected_raises(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)
        coord._connected = False
        with pytest.raises(RuntimeError):
            await coord._send("KE5YIM>APZHA:test")

    async def test_send_fires_packet_sent_event(self, hass: HomeAssistant):
        coord = self._aprs_coord(hass)
        events = []
        hass.bus.async_listen(EVENT_PACKET_SENT, lambda e: events.append(e))
        await coord._send("KE5YIM>APZHA:test")
        await hass.async_block_till_done()
        assert len(events) == 1
        assert events[0].data["raw"] == "KE5YIM>APZHA:test"

    async def test_transport_both_sends_on_both(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, options={CONF_KISS_HOST: "localhost"})
        coord._connected = True
        coord._writer = MagicMock()
        coord._raw_write = AsyncMock()
        coord._kiss_connected = True
        coord._kiss_write_packet = AsyncMock()
        await coord._send("KE5YIM>APZHA:test", transport=TRANSPORT_BOTH)
        coord._raw_write.assert_awaited_once()
        coord._kiss_write_packet.assert_awaited_once()
        assert coord.tx_packets == 1
        assert coord.kiss_tx_packets == 1

    async def test_transport_both_forces_nogate_on_kiss(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, options={CONF_KISS_HOST: "localhost"})
        coord._connected = True
        coord._writer = MagicMock()
        coord._raw_write = AsyncMock()
        coord._kiss_connected = True
        coord._kiss_write_packet = AsyncMock()
        await coord._send("KE5YIM>APZHA:test", transport=TRANSPORT_BOTH, nogate=False)
        _, kwargs = coord._kiss_write_packet.call_args
        assert kwargs.get("nogate") is True

    async def test_transport_both_no_nogate_when_aprs_is_disconnected(self, hass: HomeAssistant):
        coord = _make_coordinator(hass, options={CONF_KISS_HOST: "localhost"})
        coord._connected = False  # APRS-IS is down
        coord._kiss_connected = True
        coord._kiss_write_packet = AsyncMock()
        await coord._send("KE5YIM>APZHA:test", transport=TRANSPORT_BOTH, nogate=False)
        _, kwargs = coord._kiss_write_packet.call_args
        assert kwargs.get("nogate") is False

    async def test_transport_both_partial_ok_when_only_aprs_connected(self, hass: HomeAssistant):
        coord = _make_coordinator(hass)  # no KISS host
        coord._connected = True
        coord._writer = MagicMock()
        coord._raw_write = AsyncMock()
        # Should succeed without raising even though KISS is not available
        await coord._send("KE5YIM>APZHA:test", transport=TRANSPORT_BOTH)
        assert coord.tx_packets == 1


# ---------------------------------------------------------------------------
# _handle_kiss_line — local station filter
# ---------------------------------------------------------------------------

class TestKissLineFilter:
    def _coord_with_stations(self, hass):
        opts = {CONF_STATIONS: [{"callsign": "KE5YIM-9", "position_type": "none"}]}
        coord = _make_coordinator(hass, options=opts)
        coord._process_packet = AsyncMock()
        return coord

    async def test_configured_station_accepted(self, hass: HomeAssistant):
        coord = self._coord_with_stations(hass)
        await coord._handle_kiss_line("KE5YIM-9>APZHA,WIDE1-1:!3259.94N/09724.17W>Home")
        coord._process_packet.assert_awaited_once()

    async def test_unconfigured_station_dropped(self, hass: HomeAssistant):
        coord = self._coord_with_stations(hass)
        await coord._handle_kiss_line("W1DEF>APZHA,WIDE1-1:!3259.94N/09724.17W>Home")
        coord._process_packet.assert_not_awaited()

    async def test_kiss_rx_always_incremented(self, hass: HomeAssistant):
        coord = self._coord_with_stations(hass)
        await coord._handle_kiss_line("W1DEF>APZHA,WIDE1-1:!3259.94N/09724.17W>Home")
        assert coord.kiss_rx_packets == 1

    async def test_message_to_login_callsign_accepted_from_any_source(self, hass: HomeAssistant):
        coord = self._coord_with_stations(hass)
        # W1DEF is not in configured stations, but message is addressed to KE5YIM
        await coord._handle_kiss_line("W1DEF>APZHA::KE5YIM   :Hello{001")
        coord._process_packet.assert_awaited_once()

    async def test_message_to_other_callsign_dropped(self, hass: HomeAssistant):
        coord = self._coord_with_stations(hass)
        await coord._handle_kiss_line("W1DEF>APZHA::W1OTHER  :Hello{002")
        coord._process_packet.assert_not_awaited()
