from __future__ import annotations

import io
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
from PIL import Image
from matplotlib.patches import Polygon
from pyproj import Transformer
from rasterio.plot import plotting_extent
from rasterio.transform import array_bounds

from fmi_radar.config import Config, Theme
from fmi_radar.process import RadarCrop, crop_stats

HELSINKI = ZoneInfo("Europe/Helsinki")
WEB_MERCATOR = "EPSG:3857"


def _color_scale(config: Config) -> tuple[Normalize, str]:
    if config.quantity == "dbzh":
        return Normalize(vmin=config.dbz_vmin, vmax=config.dbz_vmax), "Reflectivity (dBZ)"
    return Normalize(vmin=0.0, vmax=config.rr_vmax), "Rain rate (mm/h)"


def _mask_overlay(data: np.ndarray, config: Config) -> np.ma.MaskedArray:
    masked = np.ma.masked_invalid(data)
    floor = config.dbz_vmin if config.quantity == "dbzh" else config.rr_vmin
    return np.ma.masked_less(masked, floor)


def _src_bounds(crop: RadarCrop) -> tuple[float, float, float, float]:
    height, width = crop.rr.shape
    return array_bounds(height, width, crop.transform)


def _mercator_aabb(crop: RadarCrop) -> tuple[float, float, float, float]:
    """Axis-aligned Web Mercator box covering the ETRS-TM35FIN crop (for OSM tile fetch)."""
    west, south, east, north = _src_bounds(crop)
    to_merc = Transformer.from_crs(crop.crs, WEB_MERCATOR, always_xy=True)
    mx, my = to_merc.transform(
        [west, east, east, west],
        [south, south, north, north],
    )
    return float(np.min(mx)), float(np.min(my)), float(np.max(mx)), float(np.max(my))


def _basemap_in_radar_crs(crop: RadarCrop, config: Config, theme: Theme):
    """Download OSM in Web Mercator, then warp onto the radar CRS (ETRS-TM35FIN)."""
    west, south, east, north = _mercator_aabb(crop)
    tiles, extent_3857 = cx.bounds2img(
        west,
        south,
        east,
        north,
        ll=False,
        source=theme.basemap,
        use_cache=True,
        headers={"User-Agent": config.user_agent},
    )
    tiles, extent = cx.warp_tiles(tiles, extent_3857, t_crs=crop.crs)
    tiles = _restyle_basemap(tiles, theme)
    return tiles, extent


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


def _offset_label(offset_min: int) -> str:
    kind = "nowcast" if offset_min > 0 else "observed"
    stamp = "T=0 min" if offset_min == 0 else f"T={offset_min:+d} min"
    return f"{stamp}\n{kind}"


def _alert_zone_ring(lon: float, lat: float, radius_km: float, crop_crs: str) -> np.ndarray:
    """Circle in the radar CRS (same metric as the warning disk)."""
    to_crop = Transformer.from_crs("EPSG:4326", crop_crs, always_xy=True)
    x0, y0 = to_crop.transform(lon, lat)
    theta = np.linspace(0.0, 2.0 * np.pi, 128, endpoint=True)
    radius_m = radius_km * 1000.0
    return np.column_stack((x0 + radius_m * np.cos(theta), y0 + radius_m * np.sin(theta)))


def _draw_radar_figure(
    crop: RadarCrop,
    config: Config,
    theme: Theme,
    *,
    offset_min: int | None = None,
    cached_basemap: tuple | None = None,
):
    values = crop.dbzh if config.quantity == "dbzh" else crop.rr
    west, south, east, north = _src_bounds(crop)
    radar_extent = plotting_extent(values, crop.transform)
    data = _mask_overlay(values, config)
    norm, cbar_label = _color_scale(config)

    radar_stamp = crop.timestamp.astimezone(HELSINKI).strftime("%Y-%m-%d %H:%M %Z")
    stats = crop_stats(crop)

    if cached_basemap is None:
        cached_basemap = _basemap_in_radar_crs(crop, config, theme)
    tiles, tile_extent = cached_basemap

    overlay_cmap = plt.get_cmap(config.cmap_for(theme)).copy()
    overlay_cmap.set_bad(alpha=0.0)
    overlay_cmap.set_under(alpha=0.0)
    cbar_cmap = plt.get_cmap(config.cmap_for(theme))

    fig, ax = plt.subplots(
        figsize=(config.figsize, config.figsize),
        dpi=config.dpi,
        facecolor=theme.face,
    )
    fig.subplots_adjust(left=0.04, right=0.88, top=0.88, bottom=0.06)
    ax.set_facecolor(theme.face)
    ax.imshow(tiles, extent=tile_extent, interpolation="lanczos", origin="upper", zorder=1)
    ax.imshow(
        data,
        origin="upper",
        extent=radar_extent,
        cmap=overlay_cmap,
        norm=norm,
        interpolation="nearest",
        alpha=0.78,
        zorder=3,
    )
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect("equal")
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ring = _alert_zone_ring(config.lon, config.lat, config.warn_radius_km, crop.crs)
    fill_alpha = max(0.0, min(1.0, config.alert_alpha))
    edge_alpha = min(1.0, fill_alpha + 0.25)
    ax.add_patch(
        Polygon(
            ring,
            closed=True,
            facecolor=theme.text,
            edgecolor="none",
            alpha=fill_alpha,
            linewidth=0,
            zorder=4,
        )
    )
    ax.plot(
        ring[:, 0],
        ring[:, 1],
        color=theme.text,
        alpha=edge_alpha,
        linewidth=1.4,
        solid_capstyle="round",
        zorder=5,
    )
    if offset_min is not None:
        ax.text(
            0.03,
            0.97,
            _offset_label(offset_min),
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=14,
            fontweight="bold",
            color=theme.text,
            zorder=5,
            bbox={"boxstyle": "round,pad=0.35", "facecolor": theme.face, "alpha": 0.82, "edgecolor": theme.muted},
        )

    sm = plt.cm.ScalarMappable(norm=norm, cmap=cbar_cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.03)
    cbar.mappable.set_clim(norm.vmin, norm.vmax)
    cbar.set_label(cbar_label, color=theme.text, fontsize=9)
    if config.quantity == "rr":
        cbar.ax.yaxis.set_major_locator(FixedLocator(list(config.rr_ticks)))
        cbar.ax.yaxis.set_major_formatter(FormatStrFormatter("%g"))
        cbar.ax.yaxis.set_minor_locator(FixedLocator([]))
        cbar.ax.set_ylim(norm.vmin, norm.vmax)
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
    return fig, cached_basemap


def render_map(
    crop: RadarCrop,
    config: Config,
    theme: Theme,
    outputs: Path | list[Path],
    *,
    offset_min: int | None = None,
    cached_basemap: tuple | None = None,
) -> tuple[list[Path], tuple]:
    paths = [outputs] if isinstance(outputs, Path) else list(outputs)
    if not paths:
        raise ValueError("No output paths")
    paths[0].parent.mkdir(parents=True, exist_ok=True)

    fig, cached_basemap = _draw_radar_figure(
        crop, config, theme, offset_min=offset_min, cached_basemap=cached_basemap
    )
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
    return paths, cached_basemap


def write_radar_gif(
    frames: list[tuple[int, RadarCrop]],
    config: Config,
    theme: Theme,
    output: Path,
) -> Path:
    """Animate observed past + nowcast future, annotated T=-15 … T=+15."""
    if not frames:
        raise ValueError("No GIF frames")
    output.parent.mkdir(parents=True, exist_ok=True)
    images: list[Image.Image] = []
    cached = None
    for offset, crop in frames:
        fig, cached = _draw_radar_figure(
            crop, config, theme, offset_min=offset, cached_basemap=cached
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        images.append(Image.open(buf).convert("RGB"))
    palette = images[0].quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    quantized = [
        frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in images
    ]
    quantized[0].save(
        output,
        save_all=True,
        append_images=quantized[1:],
        duration=config.gif_duration_ms,
        loop=0,
        optimize=False,
        disposal=2,
    )
    for image in images:
        image.close()
    for image in quantized:
        image.close()
    return output
