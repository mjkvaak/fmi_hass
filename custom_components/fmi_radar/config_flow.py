"""Config flow for FMI precipitation radar."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .hass_config import coordinates_in_radar_coverage, default_setup_lat_lon

from .const import (
    CONF_BOX_KM,
    CONF_FLOW_ARROW_DENSITY,
    CONF_OF_PADDING_KM,
    CONF_SCAN_INTERVAL,
    CONF_THEME,
    CONF_TIMEOUT,
    CONF_WARN_RADIUS_KM,
    DEFAULT_BOX_KM,
    DEFAULT_FLOW_ARROW_DENSITY,
    DEFAULT_NAME,
    DEFAULT_OF_PADDING_KM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_THEME,
    DEFAULT_TIMEOUT,
    DEFAULT_WARN_RADIUS_KM,
    DOMAIN,
)


def _schema(hass: HomeAssistant, defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    lat, lon = default_setup_lat_lon(hass.config.latitude, hass.config.longitude)
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, DEFAULT_NAME)): cv.string,
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
                default=float(d.get(CONF_BOX_KM, DEFAULT_BOX_KM)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1.0,
                    max=200.0,
                    step=1.0,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="km",
                )
            ),
            vol.Required(
                CONF_WARN_RADIUS_KM,
                default=float(d.get(CONF_WARN_RADIUS_KM, DEFAULT_WARN_RADIUS_KM)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.25,
                    max=50.0,
                    step=0.25,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="km",
                )
            ),
            vol.Required(
                CONF_OF_PADDING_KM,
                default=float(d.get(CONF_OF_PADDING_KM, DEFAULT_OF_PADDING_KM)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.0,
                    max=100.0,
                    step=1.0,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="km",
                )
            ),
            vol.Required(
                CONF_THEME,
                default=d.get(CONF_THEME, DEFAULT_THEME),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=["hass", "dark", "light"],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_FLOW_ARROW_DENSITY,
                default=float(d.get(CONF_FLOW_ARROW_DENSITY, DEFAULT_FLOW_ARROW_DENSITY)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=int(d.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=30,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement=UnitOfTime.MINUTES,
                )
            ),
            vol.Required(
                CONF_TIMEOUT,
                default=float(d.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=30.0,
                    max=600.0,
                    step=10.0,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement=UnitOfTime.SECONDS,
                )
            ),
        }
    )


class FmiRadarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not coordinates_in_radar_coverage(
                float(user_input[CONF_LATITUDE]), float(user_input[CONF_LONGITUDE])
            ):
                errors["base"] = "outside_coverage"
            else:
                unique = (
                    f"{float(user_input[CONF_LATITUDE]):.4f}_"
                    f"{float(user_input[CONF_LONGITUDE]):.4f}"
                )
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                title = user_input.get(CONF_NAME) or DEFAULT_NAME
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(self.hass, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return FmiRadarOptionsFlow()


class FmiRadarOptionsFlow(config_entries.OptionsFlow):
    """Options flow; ``config_entry`` is set by Home Assistant (do not pass it in)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            if not coordinates_in_radar_coverage(
                float(user_input[CONF_LATITUDE]), float(user_input[CONF_LONGITUDE])
            ):
                return self.async_show_form(
                    step_id="init",
                    data_schema=_schema(self.hass, user_input),
                    errors={"base": "outside_coverage"},
                )
            return self.async_create_entry(title="", data=user_input)

        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(self.hass, defaults))
