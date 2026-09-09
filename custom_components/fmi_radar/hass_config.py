"""Map config-entry data to the radar library Config (no Home Assistant imports)."""

from __future__ import annotations

from pathlib import Path

from fmi_radar.config import Config
from fmi_radar.const import (
    CONF_ALERT_ALPHA,
    CONF_BOX_KM,
    CONF_CMAP,
    CONF_FLOW_ARROW_DENSITY,
    CONF_OF_PADDING_KM,
    CONF_POLL_SECONDS,
    CONF_SHOW_FLOW_ARROWS,
    CONF_THEME,
    CONF_TIMEOUT,
    CONF_WARN_RADIUS_KM,
    CONF_WRITE_GIF,
    DEFAULT_ALERT_ALPHA,
    DEFAULT_BOX_KM,
    DEFAULT_FLOW_ARROW_DENSITY,
    DEFAULT_OF_PADDING_KM,
    DEFAULT_POLL_SECONDS,
    DEFAULT_SHOW_FLOW_ARROWS,
    DEFAULT_THEME,
    DEFAULT_TIMEOUT,
    DEFAULT_WARN_RADIUS_KM,
    DEFAULT_WRITE_GIF,
    THEME_HASS,
)

CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"


def merged_entry(data: dict, options: dict | None = None) -> dict:
    return {**data, **(options or {})}


def config_from_entry(
    data: dict,
    *,
    outdir: Path,
    options: dict | None = None,
) -> Config:
    """Build a library Config from a config entry (data + options)."""
    merged = merged_entry(data, options)
    return Config(
        lat=float(merged[CONF_LATITUDE]),
        lon=float(merged[CONF_LONGITUDE]),
        box_km=float(merged.get(CONF_BOX_KM, DEFAULT_BOX_KM)),
        of_padding_km=float(merged.get(CONF_OF_PADDING_KM, DEFAULT_OF_PADDING_KM)),
        warn_radius_km=float(merged.get(CONF_WARN_RADIUS_KM, DEFAULT_WARN_RADIUS_KM)),
        outdir=Path(outdir),
        quantity="rr",
        image_formats=("png",),
        cmap=merged.get(CONF_CMAP) or None,
        alert_alpha=float(merged.get(CONF_ALERT_ALPHA, DEFAULT_ALERT_ALPHA)),
        write_gif=bool(merged.get(CONF_WRITE_GIF, DEFAULT_WRITE_GIF)),
        show_flow_arrows=bool(merged.get(CONF_SHOW_FLOW_ARROWS, DEFAULT_SHOW_FLOW_ARROWS)),
        flow_arrow_density=float(
            merged.get(CONF_FLOW_ARROW_DENSITY, DEFAULT_FLOW_ARROW_DENSITY)
        ),
        timeout_sec=float(merged.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        poll_seconds=float(merged.get(CONF_POLL_SECONDS, DEFAULT_POLL_SECONDS)),
        mqtt_host=None,
        skip_images=False,
    )


_DARK_NAME_HINTS = ("dark", "night", "midnight", "black", "oled")
_LIGHT_NAME_HINTS = ("light", "day", "paper", "bright", "clear")


def configured_theme(data: dict, options: dict | None = None) -> str:
    name = str(merged_entry(data, options).get(CONF_THEME, DEFAULT_THEME))
    if name in (THEME_HASS, "dark", "light"):
        return name
    return DEFAULT_THEME


def theme_name(
    data: dict,
    options: dict | None = None,
    *,
    hass_theme: str | None = None,
) -> str:
    """Resolve to ``dark`` or ``light`` for plotting."""
    choice = configured_theme(data, options)
    if choice in ("dark", "light"):
        return choice
    if hass_theme in ("dark", "light"):
        return hass_theme
    return "dark"


def _from_theme_name(name: str | None) -> str | None:
    if not name or name.strip().lower() == "default":
        return None
    low = name.lower().replace("-", " ").replace("_", " ")
    if any(hint in low for hint in _DARK_NAME_HINTS):
        return "dark"
    if any(hint in low for hint in _LIGHT_NAME_HINTS):
        return "light"
    return None


def _parse_rgb(value: str) -> tuple[float, float, float] | None:
    text = value.strip().lower()
    if text.startswith("rgb"):
        inner = text[text.find("(") + 1 : text.rfind(")")]
        parts = [p.strip() for p in inner.split(",")[:3]]
        try:
            r, g, b = (int(p) / 255.0 for p in parts)
            return r, g, b
        except ValueError:
            return None
    if text.startswith("#"):
        hex_color = text[1:]
        if len(hex_color) == 3:
            hex_color = "".join(ch * 2 for ch in hex_color)
        if len(hex_color) >= 6:
            try:
                r = int(hex_color[0:2], 16) / 255.0
                g = int(hex_color[2:4], 16) / 255.0
                b = int(hex_color[4:6], 16) / 255.0
                return r, g, b
            except ValueError:
                return None
    return None


def _color_is_dark(value: str) -> bool | None:
    rgb = _parse_rgb(value)
    if rgb is None:
        return None
    r, g, b = rgb
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luminance < 0.45


def _theme_dict_mode(theme: object) -> str | None:
    if not isinstance(theme, dict):
        return None
    modes = theme.get("modes")
    if isinstance(modes, dict):
        has_dark = "dark" in modes
        has_light = "light" in modes
        if has_dark and not has_light:
            return "dark"
        if has_light and not has_dark:
            return "light"
    for key in (
        "primary-background-color",
        "app-header-background-color",
        "card-background-color",
    ):
        if key in theme:
            dark = _color_is_dark(str(theme[key]))
            if dark is True:
                return "dark"
            if dark is False:
                return "light"
    return None


def infer_ha_light_dark(
    *,
    default_theme: str | None = None,
    default_dark_theme: str | None = None,
    themes: dict | None = None,
    sun_below_horizon: bool | None = None,
) -> str:
    """Best-effort dark/light from HA frontend theme state.

    Client Auto mode is not visible to the backend. We use the backend-selected
    theme name and colors, then ``sun.sun`` if the built-in default theme is in use.
    ``default_dark_theme`` is accepted because HA stores it, but it is not a
    client-mode signal on its own.
    """
    del default_dark_theme
    named = _from_theme_name(default_theme)
    if named:
        return named
    catalog = themes or {}
    from_colors = _theme_dict_mode(catalog.get(default_theme or ""))
    if from_colors:
        return from_colors
    if sun_below_horizon is True:
        return "dark"
    if sun_below_horizon is False:
        return "light"
    return "dark"
