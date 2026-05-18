"""Binary sensor platform for APRS-IS."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_WX_BEACON_INTERVAL,
    CONF_WX_STALENESS_ENTITY,
    CONF_WX_STALENESS_MAX_AGE,
    DEFAULT_WX_BEACON_INTERVAL,
    DEFAULT_WX_STALENESS_MAX_AGE,
)
from .coordinator import AprsIsCoordinator
from .sensor import _wx_beacon_device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AprsIsCoordinator = entry.runtime_data
    opts = entry.options

    if (
        int(opts.get(CONF_WX_BEACON_INTERVAL, DEFAULT_WX_BEACON_INTERVAL)) > 0
        and opts.get(CONF_WX_STALENESS_ENTITY)
    ):
        async_add_entities([
            WxBeaconStalenessSensor(coordinator, _wx_beacon_device(coordinator))
        ])


class WxBeaconStalenessSensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Data Stale"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AprsIsCoordinator, device: DeviceInfo) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_wx_beacon_stale"
        self._attr_device_info = device
        self._unregister_coord: None = None
        self._unregister_state: None = None
        self._unregister_timer: None = None

    async def async_added_to_hass(self) -> None:
        self._unregister_coord = self.coordinator.register_callback(self._handle_coord_callback)

        entity_id = self.coordinator.entry.options.get(CONF_WX_STALENESS_ENTITY)
        if entity_id:
            self._unregister_state = async_track_state_change_event(
                self.hass, [entity_id], self._handle_state_change
            )

        self._unregister_timer = async_track_time_interval(
            self.hass, self._handle_timer, timedelta(minutes=1)
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unregister_coord:
            self._unregister_coord()
        if self._unregister_state:
            self._unregister_state()
        if self._unregister_timer:
            self._unregister_timer()

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        opts = self.coordinator.entry.options
        entity_id = opts.get(CONF_WX_STALENESS_ENTITY)
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return True
        max_age_min = int(opts.get(CONF_WX_STALENESS_MAX_AGE, DEFAULT_WX_STALENESS_MAX_AGE))
        age_min = (dt_util.utcnow() - state.last_updated).total_seconds() / 60
        return age_min > max_age_min

    @callback
    def _handle_coord_callback(self, data: dict) -> None:
        if data.get("type") in ("wx_beacon_sent", "connection_status"):
            self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_timer(self, now) -> None:
        self.async_write_ha_state()
