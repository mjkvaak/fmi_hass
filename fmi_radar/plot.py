from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

import contextily as cx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize
from matplotlib.ticker import FixedLocator, FormatStrFormatter
from pyproj import Transformer
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject

from fmi_radar.config import Config, Theme
from fmi_radar.process import RadarCrop, crop_stats

HELSINKI = ZoneInfo("Europe/Helsinki")
WEB_MERCATOR = "EPSG:3857"


def _array_and_norm(data: np.ndarray, config: Config):
    if config.quantity == "dbzh":
        masked = np.ma.masked_invalid(data)
        masked = np.ma.masked_less(masked, config.dbz_vmin)
        return masked, Normalize(vmin=config.dbz_vmin, vmax=config.dbz_vmax), "Reflectivity (dBZ)"
    masked = np.ma.masked_invalid(data)
    masked = np.ma.masked_less(masked, config.rr_vmin)
    return masked, Normalize(vmin=0.0, vmax=config.rr_vmax), "Rain rate (mm/h)"


def _warp_to_web_mercator(values: np.ndarray, crop: RadarCrop, scale: int = 4) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    src_h, src_w = values.shape
    transform, width, height = calculate_default_transform(
        crop.crs,
        WEB_MERCATOR,
        src_w,
        src_h,
        *crop.bounds,
        dst_width=src_w * scale,
        dst_height=src_h * scale,
    )
    dest = np.full((height, width), np.nan, dtype=np.float32)
    reproject(
        source=values.astype(np.float32),
        destination=dest,
        src_transform=crop.transform,
        src_crs=crop.crs,
        dst_transform=transform,
        dst_crs=WEB_MERCATOR,
        resampling=Resampling.bilinear,
    )
    west, south, east, north = array_bounds(height, width, transform)
    return dest, (west, south, east, north)


def _restyle_basemap(img: np.ndarray, theme: Theme) -> np.ndarray:
    """Monochrome dark basemap from OSM tiles when no Carto API key is set."""
    name = str(theme.basemap.get("name", "")).lower()
    if theme.name != "dark" or "carto" in name:
        return img
    rgb = img[..., :3].astype(np.float32)
    gray = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    dark = 14.0 + (255.0 - gray) * 0.40
    out = img.copy()
    out[..., 0] = out[..., 1] = out[..., 2] = np.clip(dark, 0, 255).astype(img.dtype)
    return out


def render_map(
    crop: RadarCrop,
    config: Config,
    theme: Theme,
    outputs: Path | list[Path],
) -> list[Path]:
    paths = [outputs] if isinstance(outputs, Path) else list(outputs)
    if not paths:
        raise ValueError("No output paths")
    paths[0].parent.mkdir(parents=True, exist_ok=True)

    values = crop.dbzh if config.quantity == "dbzh" else crop.rr
    warped, bounds = _warp_to_web_mercator(values, crop)
    west, south, east, north = bounds
    data, norm, cbar_label = _array_and_norm(warped, config)

    to_merc = Transformer.from_crs("EPSG:4326", WEB_MERCATOR, always_xy=True)
    home_x, home_y = to_merc.transform(config.lon, config.lat)
    radar_stamp = crop.timestamp.astimezone(HELSINKI).strftime("%Y-%m-%d %H:%M %Z")
    stats = crop_stats(crop)

    tiles, tile_extent = cx.bounds2img(
        west,
        south,
        east,
        north,
        ll=False,
        source=theme.basemap,
        use_cache=True,
        headers={"User-Agent": config.user_agent},
    )
    tiles = _restyle_basemap(tiles, theme)

    cmap = plt.get_cmap(config.cmap_for(theme)).copy()
    cmap.set_bad(alpha=0.0)
    cmap.set_under(alpha=0.0)

    fig, ax = plt.subplots(
        figsize=(config.figsize, config.figsize),
        dpi=config.dpi,
        facecolor=theme.face,
    )
    ax.set_facecolor(theme.face)
    ax.imshow(tiles, extent=tile_extent, interpolation="lanczos", origin="upper", zorder=1)
    ax.imshow(
        data,
        origin="upper",
        extent=(west, east, south, north),
        cmap=cmap,
        norm=norm,
        interpolation="bilinear",
        alpha=0.78,
        zorder=3,
    )
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect("equal")
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.plot(
        [home_x],
        [home_y],
        marker="+",
        markersize=10,
        markeredgewidth=1.6,
        color=theme.text,
        zorder=4,
    )

    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.03)
    cbar.set_label(cbar_label, color=theme.text, fontsize=9)
    if config.quantity == "rr":
        cbar.ax.yaxis.set_major_locator(FixedLocator(list(config.rr_ticks)))
        cbar.ax.yaxis.set_major_formatter(FormatStrFormatter("%g"))
        cbar.ax.yaxis.set_minor_locator(FixedLocator([]))
    cbar.ax.yaxis.set_tick_params(color=theme.text, labelcolor=theme.text, labelsize=8)
    cbar.outline.set_edgecolor(theme.muted)

    title = "Precipitation radar" if config.quantity == "rr" else "Radar reflectivity"
    ax.set_title(
        f"{title}  ·  {radar_stamp}\n"
        f"{config.lat:.4f}°N  {config.lon:.4f}°E  ·  {config.box_km:.0f}×{config.box_km:.0f} km  ·  "
        f"max {stats['max_rr_mmh']:.2f} mm/h",
        color=theme.text,
        fontsize=10,
        pad=10,
        loc="left",
    )
    fig.text(
        0.012,
        0.012,
        "Radar © FMI (CC BY 4.0)  ·  Map © OpenStreetMap contributors",
        color=theme.muted,
        fontsize=7,
    )
    fig.tight_layout(rect=(0.0, 0.03, 1.0, 1.0))
    radar_epoch = crop.timestamp.timestamp()
    for output in paths:
        save_kw = {
            "format": output.suffix.lstrip(".").lower() or "png",
            "facecolor": fig.get_facecolor(),
            "edgecolor": "none",
            "metadata": {
                "Title": "FMI precipitation radar",
                "Creation Time": crop.timestamp.isoformat(),
            },
        }
        try:
            fig.savefig(output, **save_kw)
        except (TypeError, ValueError, KeyError):
            save_kw.pop("metadata", None)
            fig.savefig(output, **save_kw)
        os.utime(output, (radar_epoch, radar_epoch))
    plt.close(fig)
    return paths
