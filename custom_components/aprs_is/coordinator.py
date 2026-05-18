"""Coordinator for APRS-IS — manages the persistent TCP connection."""
from __future__ import annotations

import asyncio
import logging
import time
import warnings
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

with warnings.catch_warnings():
    # aprslib 0.7.2 uses invalid escape sequences in regex strings; suppress the
    # SyntaxWarning Python 3.12+ emits so it doesn't pollute HA logs.
    warnings.filterwarnings("ignore", category=SyntaxWarning, module="aprslib")
    import aprslib
    from aprslib.exceptions import ParseError, UnknownFormat
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import (
    PressureConverter,
    SpeedConverter,
    TemperatureConverter,
)

from .const import (
    APRS_SOFTWARE_NAME,
    APRS_SOFTWARE_VERSION,
    CONF_BEACON_INTERVAL,
    CONF_CALLSIGN,
    CONF_EVENT_RATE_LIMIT,
    CONF_FILTER_EXTRA,
    CONF_HOST,
    CONF_PASSCODE,
    CONF_PORT,
    CONF_RANGE_FILTER_RADIUS,
    CONF_STATIONS,
    CONF_WEATHER_STATIONS,
    CONF_WX_BEACON_COMMENT,
    CONF_WX_BEACON_FROM_CALL,
    CONF_WX_BEACON_INTERVAL,
    CONF_WX_BEACON_LATITUDE,
    CONF_WX_BEACON_LONGITUDE,
    CONF_WX_ENT_HUMIDITY,
    CONF_WX_ENT_LUMINOSITY,
    CONF_WX_ENT_PRESSURE,
    CONF_WX_ENT_RAIN_1H,
    CONF_WX_ENT_RAIN_24H,
    CONF_WX_ENT_RAIN_MIDNIGHT,
    CONF_WX_ENT_TEMP,
    CONF_WX_ENT_WIND_DIR,
    CONF_WX_ENT_WIND_GUST,
    CONF_WX_ENT_WIND_SPEED,
    CONF_WX_STALENESS_ENTITY,
    CONF_WX_STALENESS_MAX_AGE,
    DEFAULT_BEACON_INTERVAL,
    DEFAULT_EVENT_RATE_LIMIT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_RANGE_FILTER_RADIUS,
    DEFAULT_WX_BEACON_INTERVAL,
    DEFAULT_WX_STALENESS_MAX_AGE,
    DOMAIN,
    EVENT_BULLETIN_RECEIVED,
    EVENT_MESSAGE_RECEIVED,
    EVENT_PACKET_RECEIVED,
    EVENT_PACKET_SENT,
    EVENT_POSITION_RECEIVED,
    EVENT_WEATHER_RECEIVED,
    PACKET_TYPE_BULLETIN,
    PACKET_TYPE_MESSAGE,
    PACKET_TYPE_OBJECT,
    PACKET_TYPE_POSITION,
    PACKET_TYPE_STATUS,
    PACKET_TYPE_WEATHER,
    RECEIVE_ONLY_PASSCODE,
)

_LOGGER = logging.getLogger(__name__)

_DEDUP_TTL = 7200         # expire seen message IDs after 2 hours
_KEEPALIVE_INTERVAL = 60  # send #keepalive every 60 s
_RECONNECT_MAX = 300      # cap backoff at 5 min
_CONNECT_TIMEOUT = 30
_READLINE_TIMEOUT = 130   # slightly longer than keepalive so we never block forever
_MSG_RETRY_DELAYS = (30, 60, 120, 240, 480, 960)  # seconds between retries; 6 attempts total

# HA event → packet type mapping
_TYPED_EVENTS: dict[str, str] = {
    PACKET_TYPE_POSITION: EVENT_POSITION_RECEIVED,
    PACKET_TYPE_WEATHER: EVENT_WEATHER_RECEIVED,
    PACKET_TYPE_MESSAGE: EVENT_MESSAGE_RECEIVED,
    PACKET_TYPE_BULLETIN: EVENT_BULLETIN_RECEIVED,
}


class AprsIsCoordinator:
    """Owns the APRS-IS TCP connection for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

        # TCP handles
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()

        # Lifecycle
        self._shutdown = False
        self._connected = False
        self._connect_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._beacon_task: asyncio.Task | None = None
        self._wx_beacon_task: asyncio.Task | None = None
        self.connected_at: Any = None

        # Connection-level stats
        self.rx_packets: int = 0
        self.tx_packets: int = 0
        self.tx_messages: int = 0   # user-initiated messages only, not ACKs
        self.tx_wx_beacon_packets: int = 0
        self.events_dropped: int = 0
        self.last_rx_packet: dict | None = None
        self.last_tx_packet: str | None = None
        self.last_beacon_at: datetime | None = None
        self.last_wx_beacon_at: datetime | None = None


        # Rate limiter — sliding 1-second window of event fire timestamps
        self._rate_window: deque[float] = deque()

        # Message dedup  {to_ssid: {(from_call, msgid): monotonic_ts}}
        self._message_seen: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)

        # Outbound message ID counter (wraps at 99999)
        self._msg_id_counter: int = 0

        # Pending outbound messages awaiting ACK  {(sender_upper, msgid): retry_task}
        self._pending_messages: dict[tuple[str, str], asyncio.Task] = {}

        # Entity update callbacks registered by platform entities
        self._callbacks: list[Callable[[dict], None]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def callsign(self) -> str:
        return self.entry.data[CONF_CALLSIGN]

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def filter_string(self) -> str:
        """Current auto-built filter string (for display in sensors)."""
        return self._build_filter()

    @property
    def wx_beacon_callsign(self) -> str:
        """Effective sending callsign for the weather beacon."""
        return (self.entry.options.get(CONF_WX_BEACON_FROM_CALL) or self.callsign).upper()

    def is_my_callsign(self, callsign: str) -> bool:
        """True if callsign shares the same base as the login callsign."""
        return self.callsign.upper().split("-")[0] == callsign.upper().split("-")[0]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        self._shutdown = False
        self._connect_task = self.hass.async_create_background_task(
            self._connection_loop(),
            name=f"{DOMAIN}_conn_{self.callsign}",
        )
        self._beacon_task = self.hass.async_create_background_task(
            self._beacon_loop(),
            name=f"{DOMAIN}_beacon_{self.callsign}",
        )
        self._wx_beacon_task = self.hass.async_create_background_task(
            self._wx_beacon_loop(),
            name=f"{DOMAIN}_wx_beacon_{self.callsign}",
        )

    async def async_stop(self) -> None:
        self._shutdown = True
        for task in (self._keepalive_task, self._connect_task, self._beacon_task, self._wx_beacon_task):
            if task:
                task.cancel()
        for task in self._pending_messages.values():
            task.cancel()
        self._pending_messages.clear()
        await self._close_connection()

    async def async_reconnect(self) -> None:
        """Cancel the current connection and immediately start a new one.

        Used when options change so the updated filter string takes effect
        without restarting the whole integration.
        """
        if self._beacon_task:
            self._beacon_task.cancel()
            try:
                await self._beacon_task
            except (asyncio.CancelledError, Exception):
                pass
            self._beacon_task = None
        if self._wx_beacon_task:
            self._wx_beacon_task.cancel()
            try:
                await self._wx_beacon_task
            except (asyncio.CancelledError, Exception):
                pass
            self._wx_beacon_task = None
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self._connect_task:
            self._connect_task.cancel()
            try:
                await self._connect_task
            except (asyncio.CancelledError, Exception):
                pass
        await self._close_connection()
        self._connect_task = self.hass.async_create_background_task(
            self._connection_loop(),
            name=f"{DOMAIN}_conn_{self.callsign}",
        )
        self._beacon_task = self.hass.async_create_background_task(
            self._beacon_loop(),
            name=f"{DOMAIN}_beacon_{self.callsign}",
        )
        self._wx_beacon_task = self.hass.async_create_background_task(
            self._wx_beacon_loop(),
            name=f"{DOMAIN}_wx_beacon_{self.callsign}",
        )

    def register_callback(self, cb: Callable[[dict], None]) -> Callable[[], None]:
        """Register for packet/state updates. Returns an unregister callable."""
        self._callbacks.append(cb)

        def _remove() -> None:
            if cb in self._callbacks:
                self._callbacks.remove(cb)

        return _remove

    # ------------------------------------------------------------------
    # Outbound API (called by services)
    # ------------------------------------------------------------------

    async def async_send_message(
        self, to: str, message: str, from_call: str | None = None
    ) -> None:
        sender = (from_call or self.callsign).upper()
        to_padded = to.upper().ljust(9)
        # Only append a message number ({NNNNN per APRS spec, no closing brace) and
        # start a retry loop when sending as the login callsign. A custom from_call
        # means ACKs go to a callsign we don't receive messages for.
        if sender == self.callsign.upper():
            msgid = self._next_msg_id()
            packet = f"{sender}>APRS,TCPIP*::{to_padded}:{message[:67]}{{{msgid}"
            await self._send(packet, sender=sender, is_message=True)
            key = (sender, msgid)
            self._pending_messages[key] = self.hass.async_create_background_task(
                self._message_retry_loop(packet, sender, msgid),
                name=f"{DOMAIN}_retry_{msgid}",
            )
        else:
            packet = f"{sender}>APRS,TCPIP*::{to_padded}:{message[:67]}"
            await self._send(packet, sender=sender, is_message=True)

    async def async_send_bulletin(
        self, bulletin_id: str, message: str, from_call: str | None = None
    ) -> None:
        sender = (from_call or self.callsign).upper()
        bln_name = f"BLN{str(bulletin_id).upper()}"[:9].ljust(9)
        packet = f"{sender}>APRS,TCPIP*::{bln_name}:{message[:67]}"
        await self._send(packet, sender=sender)

    async def async_send_announcement(
        self, announcement_id: str, message: str, from_call: str | None = None
    ) -> None:
        sender = (from_call or self.callsign).upper()
        ann_name = f"BLN{announcement_id.upper()[0]}"[:9].ljust(9)
        packet = f"{sender}>APRS,TCPIP*::{ann_name}:{message[:67]}"
        await self._send(packet, sender=sender)

    async def async_send_wx_report(
        self,
        data: dict[str, Any],
        from_call: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        comment: str = "",
    ) -> None:
        sender = (from_call or self.callsign).upper()
        packet = _build_wx_packet(
            sender, data, self.hass,
            lat_override=latitude, lon_override=longitude, comment=comment,
        )
        if packet:
            await self._send(packet, sender=sender)

    async def async_send_object(
        self,
        object_name: str,
        lat: float,
        lon: float,
        symbol_table: str,
        symbol_code: str,
        comment: str = "",
        from_call: str | None = None,
        killed: bool = False,
    ) -> None:
        sender = (from_call or self.callsign).upper()
        packet = _build_object_packet(
            sender, object_name, lat, lon, symbol_table, symbol_code, comment, killed
        )
        await self._send(packet, sender=sender)

    async def async_send_position(
        self,
        lat: float,
        lon: float,
        symbol_table: str = "/",
        symbol_code: str = ">",
        comment: str = "",
        speed_mph: float | None = None,
        course: int | None = None,
        altitude_ft: int | None = None,
        from_call: str | None = None,
    ) -> None:
        sender = (from_call or self.callsign).upper()
        data_ext = ""
        if course is not None or speed_mph is not None:
            cse = int(course) if course is not None else 0
            spd = int(round((speed_mph or 0) / 1.15078))
            data_ext = f"{cse:03d}/{spd:03d}"
        alt_str = f"/A={int(altitude_ft):06d}" if altitude_ft is not None else ""
        info = (
            f"!{_lat_to_aprs(lat)}{symbol_table}"
            f"{_lon_to_aprs(lon)}{symbol_code}"
            f"{data_ext}{alt_str}{comment}"
        )
        packet = f"{sender}>APRS,TCPIP*:{info}"
        await self._send(packet, sender=sender)

    async def _send_beacon(self) -> None:
        """Send one position beacon for the login callsign using HA home coordinates."""
        try:
            await self.async_send_position(
                lat=self.hass.config.latitude,
                lon=self.hass.config.longitude,
                symbol_table="/",
                symbol_code="-",
                comment="Home Assistant",
            )
            self.last_beacon_at = dt_util.utcnow()
            self._notify_callbacks({"type": "beacon_sent"})
            _LOGGER.debug("APRS position beacon sent for %s", self.callsign)
        except Exception as exc:
            _LOGGER.debug("APRS position beacon failed: %s", exc)

    async def _beacon_loop(self) -> None:
        """Send a position beacon on connect, then repeat at the configured interval."""
        interval_min = int(
            self.entry.options.get(CONF_BEACON_INTERVAL, DEFAULT_BEACON_INTERVAL)
        )
        if interval_min <= 0:
            return
        interval_sec = interval_min * 60

        # Wait for the initial connection, then beacon immediately.
        while not self._shutdown and not self._connected:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return
        if not self._shutdown:
            await self._send_beacon()

        # Then repeat at the configured interval.
        while not self._shutdown:
            try:
                await asyncio.sleep(interval_sec)
            except asyncio.CancelledError:
                return
            if self._connected:
                await self._send_beacon()

    async def _send_wx_beacon(self) -> None:
        opts = self.entry.options
        staleness_entity = opts.get(CONF_WX_STALENESS_ENTITY)
        max_age_min = int(opts.get(CONF_WX_STALENESS_MAX_AGE, DEFAULT_WX_STALENESS_MAX_AGE))

        if staleness_entity:
            state = self.hass.states.get(staleness_entity)
            if state is None or state.state in ("unavailable", "unknown"):
                _LOGGER.warning(
                    "APRS WX beacon: staleness entity %s unavailable — skipping", staleness_entity
                )
                return
            age_min = (dt_util.utcnow() - state.last_updated).total_seconds() / 60
            if age_min > max_age_min:
                _LOGGER.warning(
                    "APRS WX beacon: %s is stale (%.1f min > %d min) — skipping",
                    staleness_entity, age_min, max_age_min,
                )
                return

        data = _wx_data_from_entity_options(self.hass, opts)
        if not data:
            _LOGGER.debug("APRS WX beacon: no entities configured — skipping")
            return

        from_call = opts.get(CONF_WX_BEACON_FROM_CALL) or None
        comment = opts.get(CONF_WX_BEACON_COMMENT, "Home Assistant")
        latitude = opts.get(CONF_WX_BEACON_LATITUDE)
        longitude = opts.get(CONF_WX_BEACON_LONGITUDE)
        try:
            await self.async_send_wx_report(
                data=data, from_call=from_call, comment=comment,
                latitude=latitude, longitude=longitude,
            )
            self.tx_wx_beacon_packets += 1
            self.last_wx_beacon_at = dt_util.utcnow()
            self._notify_callbacks({"type": "wx_beacon_sent"})
            _LOGGER.debug("APRS WX beacon sent for %s", from_call or self.callsign)
        except Exception as exc:
            _LOGGER.debug("APRS WX beacon failed: %s", exc)

    async def _wx_beacon_loop(self) -> None:
        """Send a WX report from configured entities on a set interval."""
        interval_min = int(
            self.entry.options.get(CONF_WX_BEACON_INTERVAL, DEFAULT_WX_BEACON_INTERVAL)
        )
        if interval_min <= 0:
            return
        interval_sec = interval_min * 60

        while not self._shutdown and (not self._connected or not self.hass.is_running):
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return
        if not self._shutdown:
            await self._send_wx_beacon()

        while not self._shutdown:
            try:
                await asyncio.sleep(interval_sec)
            except asyncio.CancelledError:
                return
            if self._connected:
                await self._send_wx_beacon()

    async def _message_retry_loop(self, packet: str, sender: str, msgid: str) -> None:
        """Retry an outbound message until ACK received or retries exhausted."""
        key = (sender.upper(), msgid)
        for delay in _MSG_RETRY_DELAYS:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if key not in self._pending_messages:
                return  # ACK was received
            if self._connected and self._writer is not None:
                try:
                    await self._raw_write(packet)
                    _LOGGER.debug("APRS message retry (msgid=%s)", msgid)
                except Exception as exc:
                    _LOGGER.debug("APRS message retry failed (msgid=%s): %s", msgid, exc)
        self._pending_messages.pop(key, None)
        _LOGGER.debug("APRS message %s no ACK after %d retries — giving up", msgid, len(_MSG_RETRY_DELAYS))

    def _acknowledge_message(self, sender: str, msgid: str) -> None:
        """Cancel the retry task for an acknowledged outbound message."""
        key = (sender.upper(), msgid)
        task = self._pending_messages.pop(key, None)
        if task:
            task.cancel()
            _LOGGER.debug("ACK received for %s msgid=%s — retries cancelled", sender, msgid)

    # ------------------------------------------------------------------
    # Connection loop
    # ------------------------------------------------------------------

    async def _connection_loop(self) -> None:
        backoff = 5
        while not self._shutdown:
            try:
                await self._connect_and_listen()
                backoff = 5  # reset after a clean session
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _LOGGER.error("APRS-IS connection error: %s", exc)

            if self._shutdown:
                return

            self._connected = False
            self._notify_callbacks({"type": "connection_status"})
            _LOGGER.info("APRS-IS: reconnecting in %ds", backoff)
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                return
            backoff = min(backoff * 2, _RECONNECT_MAX)

    async def _connect_and_listen(self) -> None:
        host = self.entry.data.get(CONF_HOST, DEFAULT_HOST)
        port = int(self.entry.data.get(CONF_PORT, DEFAULT_PORT))
        passcode = int(self.entry.data[CONF_PASSCODE])

        _LOGGER.info("APRS-IS: connecting to %s:%d as %s", host, port, self.callsign)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=_CONNECT_TIMEOUT
        )

        # Read server banner
        banner = await asyncio.wait_for(self._reader.readline(), timeout=10)
        _LOGGER.debug("APRS-IS banner: %s", banner.decode("utf-8", errors="replace").strip())

        # Send login line (filter included inline)
        filter_str = self._build_filter()
        login = (
            f"user {self.callsign} pass {passcode} "
            f"vers {APRS_SOFTWARE_NAME} {APRS_SOFTWARE_VERSION}"
        )
        if filter_str:
            login += f" {filter_str}"
        await self._raw_write(login)

        # Read login response
        resp = (
            await asyncio.wait_for(self._reader.readline(), timeout=10)
        ).decode("utf-8", errors="replace").strip()
        _LOGGER.debug("APRS-IS login response: %s", resp)

        if "unverified" in resp.lower() and passcode != RECEIVE_ONLY_PASSCODE:
            _LOGGER.warning(
                "APRS-IS: login unverified for %s — outbound packets disabled. "
                "Verify your passcode.",
                self.callsign,
            )

        self._connected = True
        self.connected_at = dt_util.utcnow()
        self._notify_callbacks({"type": "connection_status"})
        _LOGGER.info("APRS-IS: connected as %s (filter: %s)", self.callsign, filter_str or "none")

        # Start keepalive
        if self._keepalive_task:
            self._keepalive_task.cancel()
        self._keepalive_task = self.hass.async_create_background_task(
            self._keepalive_loop(), name=f"{DOMAIN}_ka_{self.callsign}"
        )

        # Packet read loop
        while not self._shutdown:
            try:
                raw = await asyncio.wait_for(
                    self._reader.readline(), timeout=_READLINE_TIMEOUT
                )
            except TimeoutError:
                continue  # keepalive loop handles the ping

            if not raw:
                _LOGGER.warning("APRS-IS: server closed the connection")
                break

            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                await self._handle_line(line)

        if self._keepalive_task:
            self._keepalive_task.cancel()

    async def _keepalive_loop(self) -> None:
        while True:
            await asyncio.sleep(_KEEPALIVE_INTERVAL)
            if self._connected and self._writer:
                try:
                    await self._raw_write("#keepalive")
                except Exception:
                    break

    async def _close_connection(self) -> None:
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    # ------------------------------------------------------------------
    # Inbound packet handling
    # ------------------------------------------------------------------

    async def _handle_line(self, line: str) -> None:
        if line.startswith("#"):
            _LOGGER.debug("APRS-IS server msg: %s", line)
            return

        self.rx_packets += 1

        try:
            packet = aprslib.parse(line)
        except (ParseError, UnknownFormat) as exc:
            _LOGGER.debug("APRS parse skip (%s): %s", exc, line[:80])
            return
        except Exception as exc:
            _LOGGER.debug("APRS parse error (%s): %s", exc, line[:80])
            return

        packet["raw"] = line
        packet["_type"] = _classify_packet(packet)
        self.last_rx_packet = packet
        ptype: str = packet["_type"]
        _LOGGER.debug("APRS RX [%s] from=%s: %s", ptype, packet.get("from", "?"), line)

        if ptype == PACKET_TYPE_MESSAGE:
            await self._handle_incoming_message(packet)

        self._notify_callbacks(packet)

        if self._check_rate_limit():
            event_data: dict[str, Any] = {
                "entry_id": self.entry.entry_id,
                "raw": line,
                "from": packet.get("from", ""),
                "type": ptype,
                "parsed": dict(packet),
            }
            self.hass.bus.async_fire(EVENT_PACKET_RECEIVED, event_data)
            if typed_event := _TYPED_EVENTS.get(ptype):
                self.hass.bus.async_fire(typed_event, event_data)

    async def _handle_incoming_message(self, packet: dict) -> None:
        to_call = packet.get("addresse", "").strip().upper()
        from_call = packet.get("from", "").upper()
        msgid = str(packet.get("msgNo", ""))
        text = packet.get("message_text", "")

        if to_call != self.callsign.upper():
            return

        # ACK/REJ — aprslib sets response="ack"|"rej" and puts the referenced
        # message number in msgNo. Fall back to text parsing for implementations
        # that leave the raw "ackXXX" string in message_text instead.
        response = packet.get("response", "")
        if response == "ack" or text.lower().startswith("ack"):
            ack_id = msgid if response == "ack" else text[3:].strip()
            self._acknowledge_message(to_call, ack_id)
            return
        if response == "rej" or text.lower().startswith("rej"):
            return

        is_dup = bool(msgid) and self._is_duplicate_message(to_call, from_call, msgid)

        if msgid:
            await self._send_ack(to_call, from_call, msgid)

        if is_dup:
            return

        persistent_notification.async_create(
            self.hass,
            message=f"**From:** {from_call}\n**To:** {to_call}\n\n{text}",
            title=f"APRS Message — {from_call}",
            notification_id=(
                f"{DOMAIN}_{to_call}_{from_call}_{msgid or int(time.time())}"
            ),
        )

    async def _send_ack(self, from_ssid: str, to_call: str, msgid: str) -> None:
        """Send APRS message ACK. Does not count toward tx stats."""
        to_padded = to_call.ljust(9)
        await self._raw_write(f"{from_ssid}>APRS,TCPIP*::{to_padded}:ack{msgid}")

    # ------------------------------------------------------------------
    # Outbound send
    # ------------------------------------------------------------------

    async def _send(
        self, packet: str, sender: str | None = None, is_message: bool = False
    ) -> None:
        if not self._connected or self._writer is None:
            raise RuntimeError("Not connected to APRS-IS")
        if int(self.entry.data[CONF_PASSCODE]) == RECEIVE_ONLY_PASSCODE:
            raise RuntimeError(
                "Integration is in receive-only mode (passcode -1) — cannot send"
            )

        await self._raw_write(packet)
        self.tx_packets += 1

        if sender and is_message:
            self.tx_messages += 1

        self.last_tx_packet = packet
        self._notify_callbacks({"type": "tx_update", "packet": packet})
        self.hass.bus.async_fire(
            EVENT_PACKET_SENT,
            {
                "entry_id": self.entry.entry_id,
                "raw": packet,
                "from": sender or self.callsign,
            },
        )

    async def _raw_write(self, line: str) -> None:
        async with self._write_lock:
            _LOGGER.debug("APRS TX: %s", line)
            self._writer.write(f"{line}\r\n".encode())
            await self._writer.drain()

    # ------------------------------------------------------------------
    # Filter builder
    # ------------------------------------------------------------------

    def _build_filter(self) -> str:
        options = self.entry.options
        parts: list[str] = []

        # b/ — packets FROM any configured station callsign
        callsigns: set[str] = set()
        for s in options.get(CONF_STATIONS, []):
            callsigns.add(s["callsign"].upper())
        for wx in options.get(CONF_WEATHER_STATIONS, []):
            callsigns.add(wx["callsign"].upper())
        if callsigns:
            parts.append("b/" + "/".join(sorted(callsigns)))

        # g/ — messages addressed TO our login callsign only
        parts.append(f"g/{self.callsign.upper()}")

        # r/ — range filter centred on HA's configured home location
        radius = int(options.get(CONF_RANGE_FILTER_RADIUS, DEFAULT_RANGE_FILTER_RADIUS))
        if radius > 0:
            lat = self.hass.config.latitude
            lon = self.hass.config.longitude
            parts.append(f"r/{lat:.4f}/{lon:.4f}/{radius}")

        # User-supplied extra terms appended verbatim
        extra = options.get(CONF_FILTER_EXTRA, "").strip()
        if extra:
            parts.append(extra)

        if not parts:
            return ""
        return "#filter " + " ".join(parts)

    # ------------------------------------------------------------------
    # Message dedup
    # ------------------------------------------------------------------

    def _is_duplicate_message(
        self, to_call: str, from_call: str, msgid: str
    ) -> bool:
        key = (from_call.upper(), msgid)
        seen = self._message_seen[to_call.upper()]
        now = time.monotonic()

        expired = [k for k, ts in list(seen.items()) if now - ts > _DEDUP_TTL]
        for k in expired:
            del seen[k]

        if key in seen:
            return True
        seen[key] = now
        return False

    # ------------------------------------------------------------------
    # Event rate limiter
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> bool:
        limit = int(
            self.entry.options.get(CONF_EVENT_RATE_LIMIT, DEFAULT_EVENT_RATE_LIMIT)
        )
        if limit == 0:
            return True

        now = time.monotonic()
        while self._rate_window and now - self._rate_window[0] > 1.0:
            self._rate_window.popleft()

        if len(self._rate_window) >= limit:
            self.events_dropped += 1
            return False

        self._rate_window.append(now)
        return True

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _notify_callbacks(self, data: dict) -> None:
        for cb in list(self._callbacks):
            try:
                cb(data)
            except Exception:
                _LOGGER.exception("Error in APRS-IS entity callback")

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _next_msg_id(self) -> str:
        self._msg_id_counter = (self._msg_id_counter + 1) % 99999
        return str(self._msg_id_counter).zfill(5)


# ------------------------------------------------------------------
# Packet type classifier
# ------------------------------------------------------------------

def _classify_packet(packet: dict) -> str:
    """Determine logical packet type from aprslib-parsed fields."""
    if "addresse" in packet:
        addr = str(packet.get("addresse", "")).strip().upper()
        if addr.startswith("BLN"):
            return PACKET_TYPE_BULLETIN
        return PACKET_TYPE_MESSAGE
    if "weather" in packet:
        return PACKET_TYPE_WEATHER
    if "object_name" in packet:
        return PACKET_TYPE_OBJECT
    if "latitude" in packet:
        return PACKET_TYPE_POSITION
    if "status" in packet:
        return PACKET_TYPE_STATUS
    return "unknown"


# ------------------------------------------------------------------
# WX entity helpers
# ------------------------------------------------------------------

def _wx_data_from_entity_options(hass: HomeAssistant, options: dict[str, Any]) -> dict[str, Any]:
    """Build a wx data dict by reading entity IDs stored in config entry options."""
    data: dict[str, Any] = {}

    def _read(entity_id: str) -> tuple[float, str] | None:
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        try:
            val = float(state.state)
        except ValueError:
            return None
        return val, state.attributes.get("unit_of_measurement", "")

    if entity := options.get(CONF_WX_ENT_TEMP):
        if r := _read(entity):
            data["temperature_f"] = TemperatureConverter.convert(
                r[0], r[1], UnitOfTemperature.FAHRENHEIT
            )

    if entity := options.get(CONF_WX_ENT_HUMIDITY):
        if r := _read(entity):
            data["humidity"] = r[0]

    if entity := options.get(CONF_WX_ENT_PRESSURE):
        if r := _read(entity):
            data["pressure_mb"] = PressureConverter.convert(r[0], r[1], UnitOfPressure.HPA)

    if entity := options.get(CONF_WX_ENT_WIND_SPEED):
        if r := _read(entity):
            data["wind_speed_mph"] = SpeedConverter.convert(
                r[0], r[1], UnitOfSpeed.MILES_PER_HOUR
            )

    if entity := options.get(CONF_WX_ENT_WIND_DIR):
        if r := _read(entity):
            data["wind_dir"] = r[0]

    if entity := options.get(CONF_WX_ENT_WIND_GUST):
        if r := _read(entity):
            data["wind_gust_mph"] = SpeedConverter.convert(
                r[0], r[1], UnitOfSpeed.MILES_PER_HOUR
            )

    def _rain_hundredths(val: float, unit: str) -> int:
        if unit == UnitOfPrecipitationDepth.INCHES:
            return int(round(val * 100))
        return int(round(val / 25.4 * 100))  # assume mm

    for conf_key, data_key in (
        (CONF_WX_ENT_RAIN_1H, "rain_1h_hundredths"),
        (CONF_WX_ENT_RAIN_24H, "rain_24h_hundredths"),
        (CONF_WX_ENT_RAIN_MIDNIGHT, "rain_midnight_hundredths"),
    ):
        if entity := options.get(conf_key):
            if r := _read(entity):
                data[data_key] = _rain_hundredths(*r)

    if entity := options.get(CONF_WX_ENT_LUMINOSITY):
        if r := _read(entity):
            data["luminosity"] = int(r[0])

    return data


# ------------------------------------------------------------------
# APRS packet formatters
# ------------------------------------------------------------------

def _lat_to_aprs(lat: float) -> str:
    direction = "N" if lat >= 0 else "S"
    lat = abs(lat)
    deg = int(lat)
    minutes = (lat - deg) * 60
    return f"{deg:02d}{minutes:05.2f}{direction}"


def _lon_to_aprs(lon: float) -> str:
    direction = "E" if lon >= 0 else "W"
    lon = abs(lon)
    deg = int(lon)
    minutes = (lon - deg) * 60
    return f"{deg:03d}{minutes:05.2f}{direction}"


def _build_wx_packet(
    sender: str,
    data: dict[str, Any],
    hass: HomeAssistant,
    lat_override: float | None = None,
    lon_override: float | None = None,
    comment: str = "",
) -> str | None:
    """Format an APRS weather packet from a data dict."""
    now = dt_util.utcnow()
    ts = now.strftime("%d%H%Mz")
    lat = _lat_to_aprs(lat_override if lat_override is not None else hass.config.latitude)
    lon = _lon_to_aprs(lon_override if lon_override is not None else hass.config.longitude)

    wind_dir = int(data.get("wind_dir") or 0)
    wind_speed = int(data.get("wind_speed_mph") or 0)
    wind_gust = int(data.get("wind_gust_mph") or 0)

    temp_f = data.get("temperature_f")
    temp_str = f"t{int(temp_f):03d}" if temp_f is not None else "t..."

    rain_1h = int(data.get("rain_1h_hundredths") or 0)
    rain_24h = int(data.get("rain_24h_hundredths") or 0)
    rain_mn = int(data.get("rain_midnight_hundredths") or 0)

    humidity = data.get("humidity")
    if humidity is not None:
        hum_val = int(humidity) % 100  # APRS encodes 100% as 00
        hum_str = f"h{hum_val:02d}"
    else:
        hum_str = "h.."

    pressure = data.get("pressure_mb")
    baro_str = f"b{int(pressure * 10):05d}" if pressure is not None else "b....."

    luminosity = data.get("luminosity")
    if luminosity is not None:
        lum_val = int(luminosity)
        lum_str = f"L{lum_val:03d}" if lum_val < 1000 else f"l{lum_val - 1000:03d}"
    else:
        lum_str = ""

    body = (
        f"@{ts}{lat}/{lon}_"
        f"{wind_dir:03d}/{wind_speed:03d}"
        f"g{wind_gust:03d}"
        f"{temp_str}"
        f"r{rain_1h:03d}p{rain_24h:03d}P{rain_mn:03d}"
        f"{hum_str}"
        f"{baro_str}"
        f"{lum_str}"
        f"{comment}"
    )
    return f"{sender}>APRS,TCPIP*:{body}"


def _build_object_packet(
    sender: str,
    name: str,
    lat: float,
    lon: float,
    symbol_table: str,
    symbol_code: str,
    comment: str,
    killed: bool,
) -> str:
    """Format an APRS object packet."""
    now = dt_util.utcnow()
    ts = now.strftime("%d%H%Mz")
    obj_name = name[:9].ljust(9)
    alive = "_" if killed else "*"
    return (
        f"{sender}>APRS,TCPIP*:"
        f";{obj_name}{alive}{ts}"
        f"{_lat_to_aprs(lat)}{symbol_table}"
        f"{_lon_to_aprs(lon)}{symbol_code}"
        f"{comment}"
    )
