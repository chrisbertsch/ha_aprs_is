"""Device tracker platform for APRS-IS position packets."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_STATIONS,
    DOMAIN,
    PACKET_TYPE_POSITION,
    POSITION_TYPE_DEVICE_TRACKER,
)
from .coordinator import AprsIsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AprsIsCoordinator = entry.runtime_data
    entities: list[AprsDeviceTracker] = []

    for station_conf in entry.options.get(CONF_STATIONS, []):
        if station_conf.get("position_type") == POSITION_TYPE_DEVICE_TRACKER:
            entities.append(AprsDeviceTracker(coordinator, station_conf["callsign"]))

    async_add_entities(entities)


class AprsDeviceTracker(TrackerEntity):
    """Tracks the last known position of an APRS callsign."""

    _attr_has_entity_name = True
    _attr_name = "Location"
    _attr_should_poll = False
    _attr_source_type = SourceType.GPS
    _attr_location_accuracy = 0

    def __init__(self, coordinator: AprsIsCoordinator, callsign: str) -> None:
        self.coordinator = coordinator
        self._callsign = callsign.upper()
        self._lat: float | None = None
        self._lon: float | None = None
        self._extra: dict[str, Any] = {}
        self._unregister: Callable[[], None] | None = None

        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._callsign}_tracker"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._callsign)},
            name=self._callsign,
            manufacturer="APRS-IS",
            model="My Station" if coordinator.is_my_callsign(self._callsign) else "Tracked Station",
            via_device=(DOMAIN, coordinator.callsign),
        )

    async def async_added_to_hass(self) -> None:
        self._unregister = self.coordinator.register_callback(self._handle_callback)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._unregister:
            self._unregister()

    @property
    def available(self) -> bool:
        return self.coordinator.connected

    @property
    def latitude(self) -> float | None:
        return self._lat

    @property
    def longitude(self) -> float | None:
        return self._lon

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") == "connection_status":
            self.async_write_ha_state()
            return

        if data.get("_type") != PACKET_TYPE_POSITION:
            return
        if data.get("from", "").upper() != self._callsign:
            return

        self._lat = data.get("latitude")
        self._lon = data.get("longitude")
        self._extra = {
            "callsign": self._callsign,
            "course": data.get("course"),
            "speed": data.get("speed"),
            "altitude": data.get("altitude"),
            "comment": data.get("comment", ""),
            "symbol_table": data.get("symbol_table", ""),
            "symbol": data.get("symbol", ""),
            "path": data.get("path", ""),
            "last_heard": dt_util.utcnow().isoformat(),
        }
        self.async_write_ha_state()
