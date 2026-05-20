"""APRS-IS integration for Home Assistant."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_NOGATE,
    CONF_STATIONS,
    CONF_TRANSPORT,
    CONF_WEATHER_STATIONS,
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
    DOMAIN,
    SERVICE_DELETE_OBJECT,
    SERVICE_SEND_ANNOUNCEMENT,
    SERVICE_SEND_BULLETIN,
    SERVICE_SEND_MESSAGE,
    SERVICE_SEND_OBJECT,
    SERVICE_SEND_POSITION,
    SERVICE_SEND_WX_FROM_ENTITIES,
    SERVICE_SEND_WX_REPORT,
    TRANSPORT_AUTO,
    TRANSPORT_BOTH,
    TX_PRIMARY_APRS_IS,
    TX_PRIMARY_KISS,
)
from .coordinator import AprsIsCoordinator, _wx_data_from_entity_options

type AprsIsConfigEntry = ConfigEntry[AprsIsCoordinator]

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.DEVICE_TRACKER, Platform.GEO_LOCATION, Platform.WEATHER]

# Validator for services that support all four transport modes.
_TRANSPORT_WITH_BOTH = vol.In(
    [TRANSPORT_AUTO, TRANSPORT_BOTH, TX_PRIMARY_APRS_IS, TX_PRIMARY_KISS]
)
# send_message omits TRANSPORT_BOTH — duplicate msgid delivery on RF is unreliable.
_TRANSPORT_NO_BOTH = vol.In(
    [TRANSPORT_AUTO, TX_PRIMARY_APRS_IS, TX_PRIMARY_KISS]
)

# Service schemas
_SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("to"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("from_call"): cv.string,
        vol.Optional(CONF_TRANSPORT, default=TRANSPORT_AUTO): _TRANSPORT_NO_BOTH,
        vol.Optional(CONF_NOGATE, default=False): cv.boolean,
    }
)
_SEND_BULLETIN_SCHEMA = vol.Schema(
    {
        vol.Required("bulletin_id"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("from_call"): cv.string,
        vol.Optional(CONF_TRANSPORT, default=TRANSPORT_AUTO): _TRANSPORT_WITH_BOTH,
        vol.Optional(CONF_NOGATE, default=False): cv.boolean,
    }
)
_SEND_ANNOUNCEMENT_SCHEMA = vol.Schema(
    {
        vol.Required("announcement_id"): vol.All(cv.string, vol.Length(min=1, max=1)),
        vol.Required("message"): cv.string,
        vol.Optional("from_call"): cv.string,
        vol.Optional(CONF_TRANSPORT, default=TRANSPORT_AUTO): _TRANSPORT_WITH_BOTH,
        vol.Optional(CONF_NOGATE, default=False): cv.boolean,
    }
)
_SEND_WX_SCHEMA = vol.Schema(
    {
        vol.Optional("temperature_f"): vol.Coerce(float),
        vol.Optional("humidity"): vol.Coerce(float),
        vol.Optional("pressure_mb"): vol.Coerce(float),
        vol.Optional("wind_speed_mph"): vol.Coerce(float),
        vol.Optional("wind_dir"): vol.Coerce(float),
        vol.Optional("wind_gust_mph"): vol.Coerce(float),
        vol.Optional("rain_1h_hundredths"): vol.Coerce(int),
        vol.Optional("rain_24h_hundredths"): vol.Coerce(int),
        vol.Optional("rain_midnight_hundredths"): vol.Coerce(int),
        vol.Optional("luminosity"): vol.Coerce(int),
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
        vol.Optional("from_call"): cv.string,
        vol.Optional(CONF_TRANSPORT, default=TRANSPORT_AUTO): _TRANSPORT_WITH_BOTH,
        vol.Optional(CONF_NOGATE, default=False): cv.boolean,
    }
)
_SEND_OBJECT_SCHEMA = vol.Schema(
    {
        vol.Required("object_name"): cv.string,
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
        vol.Optional("symbol_table", default="/"): vol.All(cv.string, vol.Length(min=1, max=1)),
        vol.Optional("symbol_code", default=">"): vol.All(cv.string, vol.Length(min=1, max=1)),
        vol.Optional("comment", default=""): cv.string,
        vol.Optional("from_call"): cv.string,
        vol.Optional(CONF_TRANSPORT, default=TRANSPORT_AUTO): _TRANSPORT_WITH_BOTH,
        vol.Optional(CONF_NOGATE, default=False): cv.boolean,
    }
)
_DELETE_OBJECT_SCHEMA = vol.Schema(
    {
        vol.Required("object_name"): cv.string,
        vol.Optional("from_call"): cv.string,
        vol.Optional(CONF_TRANSPORT, default=TRANSPORT_AUTO): _TRANSPORT_WITH_BOTH,
        vol.Optional(CONF_NOGATE, default=False): cv.boolean,
    }
)
_SEND_WX_ENTITIES_SCHEMA = vol.Schema(
    {
        vol.Optional("temperature_entity"): cv.entity_id,
        vol.Optional("humidity_entity"): cv.entity_id,
        vol.Optional("pressure_entity"): cv.entity_id,
        vol.Optional("wind_speed_entity"): cv.entity_id,
        vol.Optional("wind_dir_entity"): cv.entity_id,
        vol.Optional("wind_gust_entity"): cv.entity_id,
        vol.Optional("rain_1h_entity"): cv.entity_id,
        vol.Optional("rain_24h_entity"): cv.entity_id,
        vol.Optional("rain_midnight_entity"): cv.entity_id,
        vol.Optional("luminosity_entity"): cv.entity_id,
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
        vol.Optional("from_call"): cv.string,
        vol.Optional(CONF_TRANSPORT, default=TRANSPORT_AUTO): _TRANSPORT_WITH_BOTH,
        vol.Optional(CONF_NOGATE, default=False): cv.boolean,
    }
)
_SEND_POSITION_SCHEMA = vol.Schema(
    {
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
        vol.Optional("symbol_table", default="/"): vol.All(cv.string, vol.Length(min=1, max=1)),
        vol.Optional("symbol_code", default=">"): vol.All(cv.string, vol.Length(min=1, max=1)),
        vol.Optional("comment", default=""): cv.string,
        vol.Optional("speed_mph"): vol.Coerce(float),
        vol.Optional("course"): vol.All(vol.Coerce(int), vol.Range(min=0, max=360)),
        vol.Optional("altitude_ft"): vol.Coerce(int),
        vol.Optional("from_call"): cv.string,
        vol.Optional(CONF_TRANSPORT, default=TRANSPORT_AUTO): _TRANSPORT_WITH_BOTH,
        vol.Optional(CONF_NOGATE, default=False): cv.boolean,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: AprsIsConfigEntry) -> bool:
    coordinator = AprsIsCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AprsIsConfigEntry) -> bool:
    await entry.runtime_data.async_stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove services only when the last entry is unloaded
    if unload_ok and not hass.config_entries.async_entries(DOMAIN):
        for svc in (
            SERVICE_SEND_MESSAGE,
            SERVICE_SEND_BULLETIN,
            SERVICE_SEND_ANNOUNCEMENT,
            SERVICE_SEND_WX_REPORT,
            SERVICE_SEND_WX_FROM_ENTITIES,
            SERVICE_SEND_OBJECT,
            SERVICE_DELETE_OBJECT,
            SERVICE_SEND_POSITION,
        ):
            hass.services.async_remove(DOMAIN, svc)

    return unload_ok


async def _async_options_updated(
    hass: HomeAssistant, entry: AprsIsConfigEntry
) -> None:
    """On options change: clean up removed callsign devices, reload entity platforms,
    then reconnect TCP so the updated filter string takes effect.
    The coordinator stays alive throughout so existing entities are minimally disrupted.
    """
    coordinator: AprsIsCoordinator = entry.runtime_data

    # Build the set of callsign identifiers that should still exist after this update.
    keep = {coordinator.callsign.upper()}
    for s in entry.options.get(CONF_STATIONS, []):
        keep.add(s["callsign"].upper())
    for s in entry.options.get(CONF_WEATHER_STATIONS, []):
        keep.add(s["callsign"].upper())

    # Remove devices for any callsign no longer present. This cascades to remove
    # their entity registry entries so stale entities don't linger as "Unavailable".
    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        for id_domain, identifier in device.identifiers:
            if id_domain == DOMAIN and identifier not in keep:
                dev_reg.async_remove_device(device.id)
                break

    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_reconnect()


def _get_coordinator(hass: HomeAssistant, from_call: str | None) -> AprsIsCoordinator:
    """Find the coordinator that owns from_call, falling back to the first entry."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("No APRS-IS integration is configured")

    if from_call:
        base = from_call.upper().split("-")[0]
        for entry in entries:
            coord: AprsIsCoordinator = entry.runtime_data
            if coord.callsign.upper().split("-")[0] == base:
                return coord
        raise ServiceValidationError(
            f"No APRS-IS connection found for base callsign {base}"
        )

    return entries[0].runtime_data


def _register_services(hass: HomeAssistant) -> None:
    """Register domain services (idempotent — skipped if already registered)."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        return

    async def handle_send_message(call: ServiceCall) -> None:
        coord = _get_coordinator(hass, call.data.get("from_call"))
        await coord.async_send_message(
            to=call.data["to"],
            message=call.data["message"],
            from_call=call.data.get("from_call"),
            transport=call.data.get(CONF_TRANSPORT, TRANSPORT_AUTO),
            nogate=call.data.get(CONF_NOGATE, False),
        )

    async def handle_send_bulletin(call: ServiceCall) -> None:
        coord = _get_coordinator(hass, call.data.get("from_call"))
        await coord.async_send_bulletin(
            bulletin_id=call.data["bulletin_id"],
            message=call.data["message"],
            from_call=call.data.get("from_call"),
            transport=call.data.get(CONF_TRANSPORT, TRANSPORT_AUTO),
            nogate=call.data.get(CONF_NOGATE, False),
        )

    async def handle_send_announcement(call: ServiceCall) -> None:
        coord = _get_coordinator(hass, call.data.get("from_call"))
        await coord.async_send_announcement(
            announcement_id=call.data["announcement_id"],
            message=call.data["message"],
            from_call=call.data.get("from_call"),
            transport=call.data.get(CONF_TRANSPORT, TRANSPORT_AUTO),
            nogate=call.data.get(CONF_NOGATE, False),
        )

    async def handle_send_wx_report(call: ServiceCall) -> None:
        coord = _get_coordinator(hass, call.data.get("from_call"))
        await coord.async_send_wx_report(
            data=dict(call.data),
            from_call=call.data.get("from_call"),
            latitude=call.data.get("latitude"),
            longitude=call.data.get("longitude"),
            transport=call.data.get(CONF_TRANSPORT, TRANSPORT_AUTO),
            nogate=call.data.get(CONF_NOGATE, False),
        )

    async def handle_send_object(call: ServiceCall) -> None:
        coord = _get_coordinator(hass, call.data.get("from_call"))
        await coord.async_send_object(
            object_name=call.data["object_name"],
            lat=call.data.get("latitude", hass.config.latitude),
            lon=call.data.get("longitude", hass.config.longitude),
            symbol_table=call.data.get("symbol_table", "/"),
            symbol_code=call.data.get("symbol_code", ">"),
            comment=call.data.get("comment", ""),
            from_call=call.data.get("from_call"),
            transport=call.data.get(CONF_TRANSPORT, TRANSPORT_AUTO),
            nogate=call.data.get(CONF_NOGATE, False),
        )

    async def handle_delete_object(call: ServiceCall) -> None:
        coord = _get_coordinator(hass, call.data.get("from_call"))
        await coord.async_send_object(
            object_name=call.data["object_name"],
            lat=0,
            lon=0,
            symbol_table="/",
            symbol_code=">",
            from_call=call.data.get("from_call"),
            killed=True,
            transport=call.data.get(CONF_TRANSPORT, TRANSPORT_AUTO),
            nogate=call.data.get(CONF_NOGATE, False),
        )

    async def handle_send_wx_from_entities(call: ServiceCall) -> None:
        coord = _get_coordinator(hass, call.data.get("from_call"))
        entity_map = {
            CONF_WX_ENT_TEMP:         call.data.get("temperature_entity"),
            CONF_WX_ENT_HUMIDITY:     call.data.get("humidity_entity"),
            CONF_WX_ENT_PRESSURE:     call.data.get("pressure_entity"),
            CONF_WX_ENT_WIND_SPEED:   call.data.get("wind_speed_entity"),
            CONF_WX_ENT_WIND_DIR:     call.data.get("wind_dir_entity"),
            CONF_WX_ENT_WIND_GUST:    call.data.get("wind_gust_entity"),
            CONF_WX_ENT_RAIN_1H:      call.data.get("rain_1h_entity"),
            CONF_WX_ENT_RAIN_24H:     call.data.get("rain_24h_entity"),
            CONF_WX_ENT_RAIN_MIDNIGHT: call.data.get("rain_midnight_entity"),
            CONF_WX_ENT_LUMINOSITY:   call.data.get("luminosity_entity"),
        }
        data = _wx_data_from_entity_options(hass, entity_map)
        await coord.async_send_wx_report(
            data=data,
            from_call=call.data.get("from_call"),
            latitude=call.data.get("latitude"),
            longitude=call.data.get("longitude"),
            transport=call.data.get(CONF_TRANSPORT, TRANSPORT_AUTO),
            nogate=call.data.get(CONF_NOGATE, False),
        )

    async def handle_send_position(call: ServiceCall) -> None:
        coord = _get_coordinator(hass, call.data.get("from_call"))
        await coord.async_send_position(
            lat=call.data.get("latitude", hass.config.latitude),
            lon=call.data.get("longitude", hass.config.longitude),
            symbol_table=call.data.get("symbol_table", "/"),
            symbol_code=call.data.get("symbol_code", ">"),
            comment=call.data.get("comment", ""),
            speed_mph=call.data.get("speed_mph"),
            course=call.data.get("course"),
            altitude_ft=call.data.get("altitude_ft"),
            from_call=call.data.get("from_call"),
            transport=call.data.get(CONF_TRANSPORT, TRANSPORT_AUTO),
            nogate=call.data.get(CONF_NOGATE, False),
        )

    hass.services.async_register(DOMAIN, SERVICE_SEND_MESSAGE, handle_send_message, _SEND_MESSAGE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_BULLETIN, handle_send_bulletin, _SEND_BULLETIN_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_ANNOUNCEMENT, handle_send_announcement, _SEND_ANNOUNCEMENT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_WX_REPORT, handle_send_wx_report, _SEND_WX_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_OBJECT, handle_send_object, _SEND_OBJECT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_OBJECT, handle_delete_object, _DELETE_OBJECT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_WX_FROM_ENTITIES, handle_send_wx_from_entities, _SEND_WX_ENTITIES_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_POSITION, handle_send_position, _SEND_POSITION_SCHEMA)
