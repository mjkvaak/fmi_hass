"""FMI precipitation radar for Home Assistant.

Keep this module light: Home Assistant imports it when the config flow opens.
GIS rendering stays in the pipeline and is loaded only after setup.
"""

from __future__ import annotations

from .const import DOMAIN

__all__ = [
    "DOMAIN",
    "async_setup_entry",
    "async_unload_entry",
]


async def async_setup_entry(hass, entry):
    from .ha_entry import async_setup_entry as _setup

    return await _setup(hass, entry)


async def async_unload_entry(hass, entry):
    from .ha_entry import async_unload_entry as _unload

    return await _unload(hass, entry)
