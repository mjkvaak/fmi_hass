"""Config flow for FMI precipitation radar."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from fmi_radar.hass_config import default_setup_lat_lon

from .const import (
    CONF_BOX_KM,
    CONF_FLOW_ARROW_DENSITY,
    CONF_OF_PADDING_KM,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_FLOW_ARROWS,
    CONF_THEME,
    CONF_TIMEOUT,
    CONF_WARN_RADIUS_KM,
    CONF_WRITE_GIF,
    DEFAULT_BOX_KM,
    DEFAULT_FLOW_ARROW_DENSITY,
    DEFAULT_OF_PADDING_KM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SHOW_FLOW_ARROWS,
    DEFAULT_THEME,
    DEFAULT_TIMEOUT,
    DEFAULT_WARN_RADIUS_KM,
    DEFAULT_WRITE_GIF,
    DOMAIN,
)


def _schema(hass: HomeAssistant, defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    lat, lon = default_setup_lat_lon(hass.config.latitude, hass.config.longitude)
    return vol.Schema(
        {
            vol.Optional(
                CONF_NAME,
                default=d.get(CONF_NAME, "FMI Radar"),
            ): cv.string,
            vol.Required(
                CONF_LATITUDE,
                default=d.get(CONF_LATITUDE, lat),
            ): cv.latitude,
            vol.Required(
                CONF_LONGITUDE,
                default=d.get(CONF_LONGITUDE, lon),
            ): cv.longitude,
            vol.Required(
                CONF_BOX_KM,
                default=d.get(CONF_BOX_KM, DEFAULT_BOX_KM),
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=200.0)),
            vol.Required(
                CONF_WARN_RADIUS_KM,
                default=d.get(CONF_WARN_RADIUS_KM, DEFAULT_WARN_RADIUS_KM),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.25, max=50.0)),
            vol.Optional(
                CONF_OF_PADDING_KM,
                default=d.get(CONF_OF_PADDING_KM, DEFAULT_OF_PADDING_KM),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
            vol.Optional(
                CONF_THEME,
                default=d.get(CONF_THEME, DEFAULT_THEME),
            ): vol.In(["hass", "dark", "light"]),
            vol.Optional(
                CONF_WRITE_GIF,
                default=d.get(CONF_WRITE_GIF, DEFAULT_WRITE_GIF),
            ): cv.boolean,
            vol.Optional(
                CONF_SHOW_FLOW_ARROWS,
                default=d.get(CONF_SHOW_FLOW_ARROWS, DEFAULT_SHOW_FLOW_ARROWS),
            ): cv.boolean,
            vol.Optional(
                CONF_FLOW_ARROW_DENSITY,
                default=d.get(CONF_FLOW_ARROW_DENSITY, DEFAULT_FLOW_ARROW_DENSITY),
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=d.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Optional(
                CONF_TIMEOUT,
                default=d.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            ): vol.All(vol.Coerce(float), vol.Range(min=30.0, max=600.0)),
        }
    )


class FmiRadarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=_schema(self.hass))

        unique = f"{float(user_input[CONF_LATITUDE]):.4f}_{float(user_input[CONF_LONGITUDE]):.4f}"
        await self.async_set_unique_id(unique)
        self._abort_if_unique_id_configured()

        title = user_input.get(CONF_NAME) or "FMI Radar"
        return self.async_create_entry(title=title, data=user_input)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return FmiRadarOptionsFlow(config_entry)


class FmiRadarOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        defaults = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(self.hass, defaults))
