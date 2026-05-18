"""Geolocation platform for APRS-IS tracked stations and weather stations."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance as haversine_distance

from .const import (
    CONF_STATIONS,
    CONF_WEATHER_STATIONS,
    DOMAIN,
    PACKET_TYPE_POSITION,
    PACKET_TYPE_WEATHER,
    POSITION_TYPE_GEO_LOCATION,
)
from .coordinator import AprsIsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AprsIsCoordinator = entry.runtime_data
    entities: list[AprsGeolocationEntity] = []

    for station_conf in entry.options.get(CONF_STATIONS, []):
        if station_conf.get("position_type") == POSITION_TYPE_GEO_LOCATION:
            model = "My Station" if coordinator.is_my_callsign(station_conf["callsign"]) else "Tracked Station"
            entities.append(
                AprsGeolocationEntity(coordinator, station_conf["callsign"], model=model)
            )

    for wx_conf in entry.options.get(CONF_WEATHER_STATIONS, []):
        entities.append(
            AprsGeolocationEntity(
                coordinator,
                wx_conf["callsign"],
                model="Weather Station",
                packet_type=PACKET_TYPE_WEATHER,
            )
        )

    async_add_entities(entities)


class AprsGeolocationEntity(GeolocationEvent):
    """Map pin for a tracked APRS callsign.

    State is distance from the HA home location in km.
    """

    _attr_has_entity_name = True
    _attr_name = "Location"
    _attr_should_poll = False
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(
        self,
        coordinator: AprsIsCoordinator,
        callsign: str,
        model: str,
        packet_type: str = PACKET_TYPE_POSITION,
    ) -> None:
        self.coordinator = coordinator
        self._callsign = callsign.upper()
        self._packet_type = packet_type
        self._lat: float | None = None
        self._lon: float | None = None
        self._extra: dict[str, Any] = {}
        self._unregister: Callable[[], None] | None = None

        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._callsign}_geo"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._callsign)},
            name=self._callsign,
            manufacturer="APRS-IS",
            model=model,
            via_device=(DOMAIN, coordinator.callsign),
        )

    # ------------------------------------------------------------------
    # GeolocationEvent required properties
    # ------------------------------------------------------------------

    @property
    def source(self) -> str:
        return DOMAIN

    @property
    def latitude(self) -> float | None:
        return self._lat

    @property
    def longitude(self) -> float | None:
        return self._lon

    @property
    def distance(self) -> float | None:
        if self._lat is None or self._lon is None:
            return None
        meters = haversine_distance(
            self.hass.config.latitude,
            self.hass.config.longitude,
            self._lat,
            self._lon,
        )
        return round(meters / 1000, 1) if meters is not None else None

    # ------------------------------------------------------------------
    # Availability and extras
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.coordinator.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        self._unregister = self.coordinator.register_callback(self._handle_callback)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._unregister:
            self._unregister()

    # ------------------------------------------------------------------
    # Packet callback
    # ------------------------------------------------------------------

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") == "connection_status":
            self.async_write_ha_state()
            return

        if data.get("_type") != self._packet_type:
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
