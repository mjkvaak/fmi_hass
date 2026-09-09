"""Poll FMI radar on a timer while this config entry is loaded."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .config import THEMES
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, CONF_SCAN_INTERVAL
from .freshness import StaleRadarError
from .hass_config import config_from_entry
from .ha_theme import resolve_map_theme
from .pipeline import RenderResult, render_latest

_LOGGER = logging.getLogger(__name__)


class FmiRadarCoordinator(DataUpdateCoordinator[RenderResult]):
    """Fetch, nowcast, and render while Home Assistant is running."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        minutes = int(
            {**entry.data, **entry.options}.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=timedelta(minutes=minutes),
        )
        self.png_bytes: bytes | None = None
        self.gif_bytes: bytes | None = None
        slug = entry.entry_id[:8]
        self.outdir = Path(hass.config.path("www", "fmi_radar", slug))
        title = entry.data.get(CONF_NAME) or entry.title or "FMI Radar"
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=title,
            manufacturer="Finnish Meteorological Institute",
            model="CAPPI 600 m reflectivity",
            configuration_url="https://en.ilmatieteenlaitos.fi/open-data",
        )

    def _blocking_render(self, map_theme: str) -> RenderResult:
        self.outdir.mkdir(parents=True, exist_ok=True)
        cfg = config_from_entry(
            self.entry.data, outdir=self.outdir, options=dict(self.entry.options)
        )
        return render_latest(cfg, [THEMES[map_theme]])

    async def _async_update_data(self) -> RenderResult:
        map_theme = resolve_map_theme(self.hass, self.entry.data, dict(self.entry.options))
        _LOGGER.info("Radar poll started (theme=%s)", map_theme)
        cfg = config_from_entry(
            self.entry.data, outdir=self.outdir, options=dict(self.entry.options)
        )
        timeout = cfg.timeout_sec if cfg.timeout_sec > 0 else None
        try:
            result = await asyncio.wait_for(
                self.hass.async_add_executor_job(self._blocking_render, map_theme),
                timeout=timeout,
            )
        except TimeoutError as err:
            _LOGGER.error("Radar fetch timed out after %.0fs", cfg.timeout_sec)
            raise UpdateFailed(f"Radar fetch timed out after {cfg.timeout_sec:.0f}s") from err
        except StaleRadarError as err:
            _LOGGER.error("%s", err)
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            _LOGGER.exception("Radar update failed")
            raise UpdateFailed(str(err)) from err

        png_path = self.outdir / "output.png"
        gif_path = self.outdir / "radar.gif"
        self.png_bytes = png_path.read_bytes() if png_path.exists() else None
        self.gif_bytes = gif_path.read_bytes() if gif_path.exists() else None
        _LOGGER.info(
            "Radar poll finished status=%s mean_rr=%.2f",
            result.alert.status,
            result.alert.mean_rr_mmh,
        )
        return result
