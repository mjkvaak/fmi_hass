"""Infer dark/light map styling from Home Assistant frontend settings."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from fmi_radar.hass_config import infer_ha_light_dark, theme_name


def frontend_theme_snapshot(hass: HomeAssistant) -> dict:
    default = hass.data.get("frontend_default_theme")
    dark = hass.data.get("frontend_default_dark_theme")
    themes = hass.data.get("frontend_themes")
    try:
        from homeassistant.components import frontend as fe

        default = hass.data.get(getattr(fe, "DATA_DEFAULT_THEME", "frontend_default_theme"), default)
        dark = hass.data.get(
            getattr(fe, "DATA_DEFAULT_DARK_THEME", "frontend_default_dark_theme"), dark
        )
        themes = hass.data.get(getattr(fe, "DATA_THEMES", "frontend_themes"), themes)
    except Exception:  # noqa: BLE001 — frontend may be missing in recovery
        pass
    sun = hass.states.get("sun.sun")
    below: bool | None = None
    if sun is not None and sun.state not in ("unknown", "unavailable", ""):
        below = sun.state == "below_horizon"
    return {
        "default_theme": default if isinstance(default, str) else None,
        "default_dark_theme": dark if isinstance(dark, str) else None,
        "themes": themes if isinstance(themes, dict) else {},
        "sun_below_horizon": below,
    }


def resolve_map_theme(hass: HomeAssistant, data: dict, options: dict | None = None) -> str:
    """Return ``dark`` or ``light`` for GIF/stills."""
    return theme_name(
        data,
        options,
        hass_theme=infer_ha_light_dark(**frontend_theme_snapshot(hass)),
    )
