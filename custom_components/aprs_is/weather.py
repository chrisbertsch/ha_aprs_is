"""Weather platform for APRS-IS weather stations."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.weather import WeatherEntity, WeatherEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPressure, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_WEATHER_STATIONS,
    DOMAIN,
    PACKET_TYPE_WEATHER,
)
from .coordinator import AprsIsCoordinator

_LOGGER = logging.getLogger(__name__)

# Condition derivation thresholds (aprslib returns mm for rain, m/s for wind)
_RAIN_POURING_MM = 12.7     # ≥ 0.50 in/hr
_RAIN_RAINY_MM = 0.1        # any meaningful rain
_GUST_WINDY_MS = 17.9       # ≈ 40 mph


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AprsIsCoordinator = entry.runtime_data
    entities: list[AprsWeatherEntity] = [
        AprsWeatherEntity(coordinator, wx_conf["callsign"])
        for wx_conf in entry.options.get(CONF_WEATHER_STATIONS, [])
    ]
    async_add_entities(entities)


class AprsWeatherEntity(WeatherEntity):
    """Weather entity for an APRS weather station.

    The entity name is set to None so HA uses the device name (the callsign)
    directly — e.g. 'KE5YIM-13' rather than 'KE5YIM-13 Weather'.
    """

    _attr_has_entity_name = True
    _attr_name = None               # entity name == device name (callsign)
    _attr_should_poll = False
    _attr_supported_features = WeatherEntityFeature(0)  # no forecast

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND

    def __init__(
        self,
        coordinator: AprsIsCoordinator,
        callsign: str,
    ) -> None:
        self.coordinator = coordinator
        self._callsign = callsign.upper()
        self._wx: dict[str, Any] = {}
        self._unregister: Callable[[], None] | None = None

        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._callsign}_weather"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._callsign)},
            name=self._callsign,
            manufacturer="APRS-IS",
            model="Weather Station",
            via_device=(DOMAIN, coordinator.callsign),
        )

    async def async_added_to_hass(self) -> None:
        self._unregister = self.coordinator.register_callback(self._handle_callback)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._unregister:
            self._unregister()

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.coordinator.connected

    # ------------------------------------------------------------------
    # Condition — derived from rain and wind since APRS has no sky condition
    # ------------------------------------------------------------------

    @property
    def condition(self) -> str | None:
        rain = self._wx.get("rain_1h")
        gust = self._wx.get("wind_gust")
        if rain is not None:
            if rain >= _RAIN_POURING_MM:
                return "pouring"
            if rain >= _RAIN_RAINY_MM:
                return "rainy"
        if gust is not None and gust >= _GUST_WINDY_MS:
            return "windy"
        return None

    # ------------------------------------------------------------------
    # Weather properties
    # ------------------------------------------------------------------

    @property
    def native_temperature(self) -> float | None:
        return self._wx.get("temperature")

    @property
    def humidity(self) -> float | None:
        return self._wx.get("humidity")

    @property
    def native_pressure(self) -> float | None:
        return self._wx.get("pressure")

    @property
    def native_wind_speed(self) -> float | None:
        return self._wx.get("wind_speed")

    @property
    def wind_bearing(self) -> float | None:
        return self._wx.get("wind_direction")

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self._wx.get("wind_gust")

    # ------------------------------------------------------------------
    # Packet callback
    # ------------------------------------------------------------------

    def _handle_callback(self, data: dict) -> None:
        if data.get("type") == "connection_status":
            self.async_write_ha_state()
            return

        if data.get("_type") != PACKET_TYPE_WEATHER:
            return
        if data.get("from", "").upper() != self._callsign:
            return

        wx = dict(data.get("weather", {}))
        if wx.get("wind_direction") is None and data.get("course") is not None:
            wx["wind_direction"] = data["course"]
        if wx.get("wind_speed") is None and data.get("speed") is not None:
            wx["wind_speed"] = data["speed"] / 1.852 * 0.44704
        self._wx = wx
        self.async_write_ha_state()
