"""Config flow for the APRS-IS integration."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BEACON_INTERVAL,
    CONF_CALLSIGN,
    CONF_EVENT_RATE_LIMIT,
    CONF_FILTER_EXTRA,
    CONF_HOST,
    CONF_PASSCODE,
    CONF_PORT,
    CONF_POSITION_TYPE,
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
    POSITION_TYPE_DEVICE_TRACKER,
    POSITION_TYPE_GEO_LOCATION,
    POSITION_TYPE_NONE,
    RECEIVE_ONLY_PASSCODE,
)

_WX_ENTITY_KEYS = (
    CONF_WX_ENT_TEMP,
    CONF_WX_ENT_HUMIDITY,
    CONF_WX_ENT_PRESSURE,
    CONF_WX_ENT_WIND_SPEED,
    CONF_WX_ENT_WIND_DIR,
    CONF_WX_ENT_WIND_GUST,
    CONF_WX_ENT_RAIN_1H,
    CONF_WX_ENT_RAIN_24H,
    CONF_WX_ENT_RAIN_MIDNIGHT,
    CONF_WX_ENT_LUMINOSITY,
)

_CALLSIGN_RE = re.compile(r"^[A-Z0-9]{3,7}(-[A-Z0-9]{1,2})?$", re.IGNORECASE)


def _base(callsign: str) -> str:
    return callsign.split("-")[0].upper()


def _validate_callsign(callsign: str) -> str:
    callsign = callsign.strip().upper()
    if not _CALLSIGN_RE.match(callsign):
        raise ValueError("invalid_callsign")
    return callsign


# ---------------------------------------------------------------------------
# Initial config flow
# ---------------------------------------------------------------------------

class AprsIsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup UI."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                callsign = _validate_callsign(user_input[CONF_CALLSIGN])
            except ValueError:
                errors[CONF_CALLSIGN] = "invalid_callsign"
            else:
                await self.async_set_unique_id(callsign)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=callsign,
                    data={
                        CONF_CALLSIGN: callsign,
                        CONF_PASSCODE: int(user_input[CONF_PASSCODE]),
                        CONF_HOST: user_input.get(CONF_HOST, DEFAULT_HOST),
                        CONF_PORT: int(user_input.get(CONF_PORT, DEFAULT_PORT)),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CALLSIGN): selector.TextSelector(
                        selector.TextSelectorConfig(autocomplete="off")
                    ),
                    vol.Required(
                        CONF_PASSCODE, default=RECEIVE_ONLY_PASSCODE
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=-1, max=99999, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(CONF_HOST, default=DEFAULT_HOST): selector.TextSelector(),
                    vol.Optional(
                        CONF_PORT, default=DEFAULT_PORT
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=65535, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        current = entry.data

        if user_input is not None:
            try:
                callsign = _validate_callsign(user_input[CONF_CALLSIGN])
            except ValueError:
                errors[CONF_CALLSIGN] = "invalid_callsign"
            else:
                if callsign != entry.unique_id:
                    await self.async_set_unique_id(callsign)
                    self._abort_if_unique_id_configured()
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=callsign,
                    title=callsign,
                    data={
                        CONF_CALLSIGN: callsign,
                        CONF_PASSCODE: int(user_input[CONF_PASSCODE]),
                        CONF_HOST: user_input.get(CONF_HOST, DEFAULT_HOST),
                        CONF_PORT: int(user_input.get(CONF_PORT, DEFAULT_PORT)),
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CALLSIGN, default=current.get(CONF_CALLSIGN, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(autocomplete="off")
                    ),
                    vol.Required(
                        CONF_PASSCODE, default=current.get(CONF_PASSCODE, RECEIVE_ONLY_PASSCODE)
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=-1, max=99999, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(
                        CONF_HOST, default=current.get(CONF_HOST, DEFAULT_HOST)
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_PORT, default=current.get(CONF_PORT, DEFAULT_PORT)
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=65535, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AprsIsOptionsFlow:
        return AprsIsOptionsFlow()


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------

class AprsIsOptionsFlow(OptionsFlow):
    """Multi-step options flow for managing callsigns and globals."""

    # ------------------------------------------------------------------
    # Top-level menu
    # ------------------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["global", "stations", "weather_stations", "wx_beacon"],
        )

    # ------------------------------------------------------------------
    # Global settings
    # ------------------------------------------------------------------

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )

        current = self.config_entry.options
        return self.async_show_form(
            step_id="global",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_RANGE_FILTER_RADIUS,
                        default=current.get(
                            CONF_RANGE_FILTER_RADIUS, DEFAULT_RANGE_FILTER_RADIUS
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=99999,
                            unit_of_measurement="km",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_FILTER_EXTRA,
                        default=current.get(CONF_FILTER_EXTRA, ""),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(autocomplete="off")
                    ),
                    vol.Optional(
                        CONF_EVENT_RATE_LIMIT,
                        default=current.get(
                            CONF_EVENT_RATE_LIMIT, DEFAULT_EVENT_RATE_LIMIT
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=100,
                            unit_of_measurement="packets/sec",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_BEACON_INTERVAL,
                        default=current.get(
                            CONF_BEACON_INTERVAL, DEFAULT_BEACON_INTERVAL
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1440,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    # ------------------------------------------------------------------
    # Stations (unified)
    # ------------------------------------------------------------------

    _edit_callsign: str = ""

    async def async_step_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        existing = self.config_entry.options.get(CONF_STATIONS, [])
        menu_options = ["add_station"]
        if existing:
            menu_options += ["edit_station", "remove_station"]
        return self.async_show_menu(
            step_id="stations",
            menu_options=menu_options,
        )

    async def async_step_add_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        login = self.config_entry.data[CONF_CALLSIGN]
        base = _base(login)

        if user_input is not None:
            try:
                callsign = _validate_callsign(user_input[CONF_CALLSIGN])
            except ValueError:
                errors[CONF_CALLSIGN] = "invalid_callsign"
            else:
                existing = list(self.config_entry.options.get(CONF_STATIONS, []))
                if any(s["callsign"].upper() == callsign for s in existing):
                    errors[CONF_CALLSIGN] = "already_configured"
                else:
                    existing.append(
                        {
                            CONF_CALLSIGN: callsign,
                            CONF_POSITION_TYPE: user_input[CONF_POSITION_TYPE],
                        }
                    )
                    return self.async_create_entry(
                        data={**self.config_entry.options, CONF_STATIONS: existing}
                    )

        return self.async_show_form(
            step_id="add_station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CALLSIGN): selector.TextSelector(
                        selector.TextSelectorConfig(autocomplete="off")
                    ),
                    vol.Required(
                        CONF_POSITION_TYPE, default=POSITION_TYPE_NONE
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                POSITION_TYPE_NONE,
                                POSITION_TYPE_DEVICE_TRACKER,
                                POSITION_TYPE_GEO_LOCATION,
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                            translation_key=CONF_POSITION_TYPE,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"base_callsign": base},
        )

    async def async_step_edit_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        existing = self.config_entry.options.get(CONF_STATIONS, [])

        if user_input is not None:
            self._edit_callsign = user_input[CONF_CALLSIGN]
            return await self.async_step_edit_station_form()

        return self.async_show_form(
            step_id="edit_station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CALLSIGN): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[s[CONF_CALLSIGN] for s in existing],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_station_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        existing = self.config_entry.options.get(CONF_STATIONS, [])
        current = next(
            s for s in existing if s[CONF_CALLSIGN].upper() == self._edit_callsign.upper()
        )

        if user_input is not None:
            updated = [
                {**s, CONF_POSITION_TYPE: user_input[CONF_POSITION_TYPE]}
                if s[CONF_CALLSIGN].upper() == self._edit_callsign.upper()
                else s
                for s in existing
            ]
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_STATIONS: updated}
            )

        return self.async_show_form(
            step_id="edit_station_form",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POSITION_TYPE,
                        default=current.get(CONF_POSITION_TYPE, POSITION_TYPE_NONE),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                POSITION_TYPE_NONE,
                                POSITION_TYPE_DEVICE_TRACKER,
                                POSITION_TYPE_GEO_LOCATION,
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                            translation_key=CONF_POSITION_TYPE,
                        )
                    ),
                }
            ),
            description_placeholders={"callsign": self._edit_callsign},
        )

    async def async_step_remove_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        existing = self.config_entry.options.get(CONF_STATIONS, [])

        if user_input is not None:
            to_remove = user_input[CONF_CALLSIGN]
            updated = [
                s for s in existing if s[CONF_CALLSIGN].upper() != to_remove.upper()
            ]
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_STATIONS: updated}
            )

        return self.async_show_form(
            step_id="remove_station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CALLSIGN): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[s[CONF_CALLSIGN] for s in existing],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    # ------------------------------------------------------------------
    # Weather stations
    # ------------------------------------------------------------------

    async def async_step_weather_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        existing = self.config_entry.options.get(CONF_WEATHER_STATIONS, [])
        menu_options = ["add_weather_station"]
        if existing:
            menu_options.append("remove_weather_station")
        return self.async_show_menu(
            step_id="weather_stations",
            menu_options=menu_options,
        )

    async def async_step_add_weather_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                callsign = _validate_callsign(user_input[CONF_CALLSIGN])
            except ValueError:
                errors[CONF_CALLSIGN] = "invalid_callsign"
            else:
                existing = list(
                    self.config_entry.options.get(CONF_WEATHER_STATIONS, [])
                )
                if any(s[CONF_CALLSIGN].upper() == callsign for s in existing):
                    errors[CONF_CALLSIGN] = "already_configured"
                else:
                    existing.append({CONF_CALLSIGN: callsign})
                    return self.async_create_entry(
                        data={
                            **self.config_entry.options,
                            CONF_WEATHER_STATIONS: existing,
                        }
                    )

        return self.async_show_form(
            step_id="add_weather_station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CALLSIGN): selector.TextSelector(
                        selector.TextSelectorConfig(autocomplete="off")
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_remove_weather_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        existing = self.config_entry.options.get(CONF_WEATHER_STATIONS, [])

        if user_input is not None:
            to_remove = user_input[CONF_CALLSIGN]
            updated = [
                s for s in existing if s[CONF_CALLSIGN].upper() != to_remove.upper()
            ]
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_WEATHER_STATIONS: updated}
            )

        return self.async_show_form(
            step_id="remove_weather_station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CALLSIGN): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[s[CONF_CALLSIGN] for s in existing],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    # ------------------------------------------------------------------
    # WX beacon
    # ------------------------------------------------------------------

    async def async_step_wx_beacon(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            new_options = dict(self.config_entry.options)
            new_options[CONF_WX_BEACON_INTERVAL] = int(user_input[CONF_WX_BEACON_INTERVAL])
            new_options[CONF_WX_STALENESS_MAX_AGE] = int(user_input[CONF_WX_STALENESS_MAX_AGE])
            from_call = user_input.get(CONF_WX_BEACON_FROM_CALL, "").strip().upper()
            if from_call:
                new_options[CONF_WX_BEACON_FROM_CALL] = from_call
            else:
                new_options.pop(CONF_WX_BEACON_FROM_CALL, None)
            new_options[CONF_WX_BEACON_COMMENT] = user_input.get(CONF_WX_BEACON_COMMENT, "Home Assistant").strip()
            for key in (CONF_WX_BEACON_LATITUDE, CONF_WX_BEACON_LONGITUDE):
                if (val := user_input.get(key)) is not None:
                    new_options[key] = float(val)
                else:
                    new_options.pop(key, None)
            for key in _WX_ENTITY_KEYS:
                val = user_input.get(key)
                if val:
                    new_options[key] = val
                else:
                    new_options.pop(key, None)
            staleness = user_input.get(CONF_WX_STALENESS_ENTITY)
            if staleness:
                new_options[CONF_WX_STALENESS_ENTITY] = staleness
            else:
                new_options.pop(CONF_WX_STALENESS_ENTITY, None)
            return self.async_create_entry(data=new_options)

        current = self.config_entry.options

        def _opt_num(key: str) -> vol.Optional:
            v = current.get(key)
            return vol.Optional(key, default=v) if v is not None else vol.Optional(key)

        def _opt_entity(key: str) -> vol.Optional:
            v = current.get(key)
            return vol.Optional(key, default=v) if v else vol.Optional(key)

        return self.async_show_form(
            step_id="wx_beacon",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_WX_BEACON_INTERVAL,
                        default=current.get(CONF_WX_BEACON_INTERVAL, DEFAULT_WX_BEACON_INTERVAL),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=1440, unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_WX_BEACON_FROM_CALL,
                        default=current.get(CONF_WX_BEACON_FROM_CALL, ""),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(autocomplete="off")
                    ),
                    vol.Optional(
                        CONF_WX_BEACON_COMMENT,
                        default=current.get(CONF_WX_BEACON_COMMENT, "Home Assistant"),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(autocomplete="off")
                    ),
                    _opt_num(CONF_WX_BEACON_LATITUDE): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=-90, max=90, step="any",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    _opt_num(CONF_WX_BEACON_LONGITUDE): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=-180, max=180, step="any",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    _opt_entity(CONF_WX_ENT_TEMP): selector.EntitySelector(),
                    _opt_entity(CONF_WX_ENT_HUMIDITY): selector.EntitySelector(),
                    _opt_entity(CONF_WX_ENT_PRESSURE): selector.EntitySelector(),
                    _opt_entity(CONF_WX_ENT_WIND_DIR): selector.EntitySelector(),
                    _opt_entity(CONF_WX_ENT_WIND_SPEED): selector.EntitySelector(),
                    _opt_entity(CONF_WX_ENT_WIND_GUST): selector.EntitySelector(),
                    _opt_entity(CONF_WX_ENT_RAIN_1H): selector.EntitySelector(),
                    _opt_entity(CONF_WX_ENT_RAIN_24H): selector.EntitySelector(),
                    _opt_entity(CONF_WX_ENT_RAIN_MIDNIGHT): selector.EntitySelector(),
                    _opt_entity(CONF_WX_ENT_LUMINOSITY): selector.EntitySelector(),
                    _opt_entity(CONF_WX_STALENESS_ENTITY): selector.EntitySelector(),
                    vol.Optional(
                        CONF_WX_STALENESS_MAX_AGE,
                        default=current.get(CONF_WX_STALENESS_MAX_AGE, DEFAULT_WX_STALENESS_MAX_AGE),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=120, unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

