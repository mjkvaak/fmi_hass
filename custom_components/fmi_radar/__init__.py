"""FMI precipitation radar fetch, crop, map render, and Home Assistant integration."""

from __future__ import annotations

from .alert import RainAlert
from .config import Config, Theme
from .pipeline import RenderResult, render_latest

__all__ = [
    "Config",
    "Theme",
    "RainAlert",
    "RenderResult",
    "render_latest",
    "async_setup_entry",
    "async_unload_entry",
]


async def async_setup_entry(hass, entry):
    from .ha_entry import async_setup_entry as _setup

    return await _setup(hass, entry)


async def async_unload_entry(hass, entry):
    from .ha_entry import async_unload_entry as _unload

    return await _unload(hass, entry)
