"""Sensor platform for APRS-IS."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfIrradiance,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BEACON_INTERVAL,
    CONF_STATIONS,
    CONF_WEATHER_STATIONS,
    CONF_WX_BEACON_INTERVAL,
    DEFAULT_BEACON_INTERVAL,
    DEFAULT_WX_BEACON_INTERVAL,
    DOMAIN,
    PACKET_TYPE_POSITION,
    PACKET_TYPE_WEATHER,
)
from .coordinator import AprsIsCoordinator
from .symbols import aprs_symbol_name

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AprsIsCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    # Connection-level sensors (always created)
    entities += [
        ConnectionSensor(coordinator),
        RxPacketsSensor(coordinator),
        TxPacketsSensor(coordinator),
        TxMessagesSensor(coordinator),
    ]

    if int(entry.options.get(CONF_BEACON_INTERVAL, DEFAULT_BEACON_INTERVAL)) > 0:
        entities.append(BeaconLastSentSensor(coordinator))

    # Per-station sensors
    for station_conf in entry.options.get(CONF_STATIONS, []):
        callsign = station_conf["callsign"].upper()
        dev = _station_device(coordinator, callsign)
        entities += [
            CallsignRxPacketsSensor(coordinator, callsign, dev),
            LastSeenSensor(coordinator, callsign, dev, "last_seen"),
            SymbolSensor(coordinator, callsign, dev),
        ]

    # Per-weather-station sensors
    for wx_conf in entry.options.get(CONF_WEATHER_STATIONS, []):
        callsign = wx_conf["callsign"].upper()
        dev = _wx_station_device(coordinator, callsign)
        entities += [
            CallsignRxPacketsSensor(coordinator, callsign, dev),
            LastSeenSensor(coordinator, callsign, dev, "last_seen"),
            SymbolSensor(coordinator, callsign, dev, packet_type=PACKET_TYPE_WEATHER),
        ]
        for desc in _WX_DESCRIPTIONS:
            entities.append(
                WeatherSensor(coordinator, callsign, desc, dev)
            )

    if int(entry.options.get(CONF_WX_BEACON_INTERVAL, DEFAULT_WX_BEACON_INTERVAL)) > 0:
        dev = _wx_beacon_device(coordinator)
        entities += [
            WxBeaconPacketsSentSensor(coordinator, dev),
            WxBeaconLastSentSensor(coordinator, dev),
        ]

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Device info helpers
# ---------------------------------------------------------------------------

def _connection_device(coordinator: AprsIsCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.callsign)},
        name=coordinator.callsign,
        manufacturer="APRS-IS",
        model="Connection",
    )


def _station_device(coordinator: AprsIsCoordinator, callsign: str) -> DeviceInfo:
    model = "My Station" if coordinator.is_my_callsign(callsign) else "Tracked Station"
    return DeviceInfo(
        identifiers={(DOMAIN, callsign.upper())},
        name=callsign.upper(),
        manufacturer="APRS-IS",
        model=model,
        via_device=(DOMAIN, coordinator.callsign),
    )


def _wx_station_device(coordinator: AprsIsCoordinator, callsign: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, callsign.upper())},
        name=callsign.upper(),
        manufacturer="APRS-IS",
        model="Weather Station",
        via_device=(DOMAIN, coordinator.callsign),
    )


def _wx_beacon_device(coordinator: AprsIsCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_wx_beacon")},
        name=f"{coordinator.wx_beacon_callsign} (Weather Beacon)",
        manufacturer="APRS-IS",
        model="Weather Beacon",
        via_device=(DOMAIN, coordinator.callsign),
    )



# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class _AprsIsSensorBase(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: AprsIsCoordinator) -> None:
        self.coordinator = coordinator
        self._unregister: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        self._unregister = self.coordinator.register_callback(self._handle_callback)

    async def async_will_remove_from_hass(self) -> None:
        if self._unregister:
            self._unregister()

    @property
    def available(self) -> bool:
        return self.coordinator.connected

    def _handle_callback(self, data: dict) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Connection-level sensors
# ---------------------------------------------------------------------------

class ConnectionSensor(_AprsIsSensorBase):
    _attr_name = "Connection"
    _attr_icon = "mdi:radio-tower"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AprsIsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_connection"
        self._attr_device_info = _connection_device(coordinator)

    @property
    def available(self) -> bool:
        return True  # always available — state reflects connection status

    @property
    def native_value(self) -> str:
        return "connected" if self.coordinator.connected else "disconnected"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        entry = self.coordinator.entry
        return {
            "server": entry.data.get("host", "rotate.aprs.net"),
            "port": entry.data.get("port", 14580),
            "filter": self.coordinator.filter_string,
            "connected_since": self.coordinator.connected_at,
            "events_dropped": self.coordinator.events_dropped,
        }

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") == "connection_status":
            self.async_write_ha_state()


class RxPacketsSensor(_AprsIsSensorBase):
    _attr_name = "Packets Received"
    _attr_icon = "mdi:download-network"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "packets"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AprsIsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_rx_packets"
        self._attr_device_info = _connection_device(coordinator)

    @property
    def native_value(self) -> int:
        return self.coordinator.rx_packets

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pkt = self.coordinator.last_rx_packet
        if not pkt:
            return {}
        return {
            "last_from": pkt.get("from"),
            "last_type": pkt.get("_type"),
            "last_raw": pkt.get("raw", "")[:120],
        }

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") == "connection_status" or "_type" in data:
            self.async_write_ha_state()


class TxPacketsSensor(_AprsIsSensorBase):
    _attr_name = "Packets Sent"
    _attr_icon = "mdi:upload-network"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "packets"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AprsIsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_tx_packets"
        self._attr_device_info = _connection_device(coordinator)

    @property
    def native_value(self) -> int:
        return self.coordinator.tx_packets

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"last_raw": (self.coordinator.last_tx_packet or "")[:120]}

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") in ("connection_status", "tx_update"):
            self.async_write_ha_state()


class TxMessagesSensor(_AprsIsSensorBase):
    _attr_name = "Messages Sent"
    _attr_icon = "mdi:message-arrow-right"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "messages"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AprsIsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_tx_messages"
        self._attr_device_info = _connection_device(coordinator)

    @property
    def native_value(self) -> int:
        return self.coordinator.tx_messages

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") in ("connection_status", "tx_update"):
            self.async_write_ha_state()


class BeaconLastSentSensor(_AprsIsSensorBase):
    _attr_name = "Beacon Last Sent"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AprsIsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_beacon_last_sent"
        self._attr_device_info = _connection_device(coordinator)

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_beacon_at

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") in ("beacon_sent", "connection_status"):
            self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Per-callsign sensors
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-callsign packet counters
# ---------------------------------------------------------------------------

class CallsignRxPacketsSensor(_AprsIsSensorBase):
    """Count of all packets received from a specific callsign."""

    _attr_name = "Packets Received"
    _attr_icon = "mdi:download-network-outline"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "packets"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: AprsIsCoordinator,
        callsign: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._callsign = callsign.upper()
        self._count: int = 0
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._callsign}_rx_packets"
        )
        self._attr_device_info = device_info

    @property
    def native_value(self) -> int:
        return self._count

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") == "connection_status":
            self.async_write_ha_state()
            return
        if "_type" not in data:
            return
        if data.get("from", "").upper() == self._callsign:
            self._count += 1
            self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Weather sensors
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class _AprsWxDesc(SensorEntityDescription):
    """Extends SensorEntityDescription with APRS-specific fields."""
    aprs_key: str = ""
    value_fn: Callable[[Any], Any] | None = None


_WX_DESCRIPTIONS: tuple[_AprsWxDesc, ...] = (
    _AprsWxDesc(
        key="temperature",
        aprs_key="temperature",
        name="Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _AprsWxDesc(
        key="humidity",
        aprs_key="humidity",
        name="Humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _AprsWxDesc(
        key="pressure",
        aprs_key="pressure",
        name="Pressure",
        native_unit_of_measurement=UnitOfPressure.HPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _AprsWxDesc(
        key="wind_speed",
        aprs_key="wind_speed",
        name="Wind Speed",
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _AprsWxDesc(
        key="wind_direction",
        aprs_key="wind_direction",
        name="Wind Direction",
        native_unit_of_measurement="°",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:compass-rose",
    ),
    _AprsWxDesc(
        key="wind_gust",
        aprs_key="wind_gust",
        name="Wind Gust",
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _AprsWxDesc(
        key="rain_1h",
        aprs_key="rain_1h",
        name="Rain Last Hour",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _AprsWxDesc(
        key="rain_24h",
        aprs_key="rain_24h",
        name="Rain Last 24h",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _AprsWxDesc(
        key="rain_since_midnight",
        aprs_key="rain_since_midnight",
        name="Rain Since Midnight",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _AprsWxDesc(
        key="luminosity",
        aprs_key="luminosity",
        name="Luminosity",
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        device_class=SensorDeviceClass.IRRADIANCE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


class WeatherSensor(_AprsIsSensorBase):
    """One sensor entity for a single weather field from an APRS WX station."""

    def __init__(
        self,
        coordinator: AprsIsCoordinator,
        callsign: str,
        desc: _AprsWxDesc,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._callsign = callsign.upper()
        self.entity_description = desc
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._callsign}_wx_{desc.key}"
        )
        self._attr_device_info = device_info
        self._value: Any = None

    @property
    def native_value(self) -> Any:
        return self._value

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") == "connection_status":
            self.async_write_ha_state()
            return
        if data.get("_type") != PACKET_TYPE_WEATHER:
            return
        if data.get("from", "").upper() != self._callsign:
            return
        weather = dict(data.get("weather", {}))
        _LOGGER.debug(
            "WX packet from %s: weather=%s speed=%s course=%s",
            data.get("from"), weather, data.get("speed"), data.get("course"),
        )
        if weather.get("wind_direction") is None and data.get("course") is not None:
            weather["wind_direction"] = data["course"]
        if weather.get("wind_speed") is None and data.get("speed") is not None:
            weather["wind_speed"] = data["speed"] / 1.852 * 0.44704
        raw = weather.get(self.entity_description.aprs_key)
        if raw is None:
            return
        fn = self.entity_description.value_fn
        self._value = fn(raw) if fn else raw
        self.async_write_ha_state()




class SymbolSensor(_AprsIsSensorBase):
    """Current APRS symbol for a tracked callsign, shown as a human-readable name."""

    _attr_name = "Symbol"
    _attr_icon = "mdi:map-marker-question"

    def __init__(
        self,
        coordinator: AprsIsCoordinator,
        callsign: str,
        device_info: DeviceInfo,
        packet_type: str = PACKET_TYPE_POSITION,
    ) -> None:
        super().__init__(coordinator)
        self._callsign = callsign.upper()
        self._packet_type = packet_type
        self._symbol_table: str | None = None
        self._symbol_code: str | None = None
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._callsign}_symbol"
        )
        self._attr_device_info = device_info

    @property
    def native_value(self) -> str | None:
        if self._symbol_table is None or self._symbol_code is None:
            return None
        return aprs_symbol_name(self._symbol_table, self._symbol_code)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._symbol_table is None:
            return {}
        return {
            "symbol_table": self._symbol_table,
            "symbol_code": self._symbol_code,
        }

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") == "connection_status":
            self.async_write_ha_state()
            return
        if data.get("_type") != self._packet_type:
            return
        if data.get("from", "").upper() != self._callsign:
            return
        table = data.get("symbol_table", "")
        code = data.get("symbol", "")
        if table and code:
            self._symbol_table = table
            self._symbol_code = code
            self.async_write_ha_state()


class LastSeenSensor(_AprsIsSensorBase):
    """Timestamp of the last packet received from a specific callsign."""

    _attr_name = "Last Seen"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: AprsIsCoordinator,
        callsign: str,
        device_info: DeviceInfo,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._callsign = callsign.upper()
        self._last: datetime | None = None
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._callsign}_{unique_id_suffix}"
        )
        self._attr_device_info = device_info

    @property
    def native_value(self) -> datetime | None:
        return self._last

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") == "connection_status":
            self.async_write_ha_state()
            return
        if "_type" not in data:
            return
        if data.get("from", "").upper() != self._callsign:
            return
        self._last = dt_util.utcnow()
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Weather beacon sensors
# ---------------------------------------------------------------------------

class WxBeaconPacketsSentSensor(_AprsIsSensorBase):
    _attr_name = "Packets Sent"
    _attr_icon = "mdi:weather-cloudy-arrow-right"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "packets"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AprsIsCoordinator, device: DeviceInfo) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_wx_beacon_tx_packets"
        self._attr_device_info = device

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> int:
        return self.coordinator.tx_wx_beacon_packets

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") in ("wx_beacon_sent", "connection_status"):
            self.async_write_ha_state()


class WxBeaconLastSentSensor(_AprsIsSensorBase):
    _attr_name = "Last Sent"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AprsIsCoordinator, device: DeviceInfo) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_wx_beacon_last_sent"
        self._attr_device_info = device

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_wx_beacon_at

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") in ("wx_beacon_sent", "connection_status"):
            self.async_write_ha_state()
