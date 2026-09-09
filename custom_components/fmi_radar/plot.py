from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
from time import perf_counter
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
from rasterio.crs import CRS
from rasterio.plot import plotting_extent
from rasterio.transform import array_bounds, from_bounds as transform_from_bounds
from rasterio.warp import Resampling, reproject

from fmi_radar.config import Config, Theme
from fmi_radar.log import get_logger
from fmi_radar.process import RadarCrop, crop_stats

LOGGER = get_logger(__name__)

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


def _tile_zoom(box_km: float) -> int:
    """Cap OSM zoom so a 40 km crop does not warp a huge tile mosaic."""
    if box_km >= 35:
        return 10
    if box_km >= 18:
        return 11
    return 12


def _mercator_aabb(crop: RadarCrop) -> tuple[float, float, float, float]:
    """Axis-aligned Web Mercator box covering the ETRS-TM35FIN crop (for OSM tile fetch)."""
    west, south, east, north = _src_bounds(crop)
    to_merc = Transformer.from_crs(crop.crs, WEB_MERCATOR, always_xy=True)
    mx, my = to_merc.transform(
        [west, east, east, west],
        [south, south, north, north],
    )
    return float(np.min(mx)), float(np.min(my)), float(np.max(mx)), float(np.max(my))


def _basemap_source_id(theme: Theme) -> str:
    src = theme.basemap
    if hasattr(src, "get"):
        return str(src.get("name", src))
    return str(src)


def _basemap_out_size(config: Config) -> int:
    """Warp onto a grid sized for stills so matplotlib is not resampling a huge mosaic."""
    return int(max(256, min(1280, round(config.figsize * config.dpi))))


def _basemap_cache_id(crop: RadarCrop, config: Config, theme: Theme) -> str:
    west, south, east, north = _src_bounds(crop)
    payload = {
        "lat": round(config.lat, 4),
        "lon": round(config.lon, 4),
        "box_km": round(config.box_km, 3),
        "theme": theme.name,
        "zoom": _tile_zoom(config.box_km),
        "out": _basemap_out_size(config),
        "crs": crop.crs,
        "bounds_m": [round(west), round(south), round(east), round(north)],
        "source": _basemap_source_id(theme),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _basemap_cache_path(config: Config, cache_id: str) -> Path:
    return config.resolved_cache_dir() / f"basemap-{cache_id}.npz"


def load_basemap_cache(
    crop: RadarCrop, config: Config, theme: Theme
) -> tuple[np.ndarray, tuple[float, float, float, float]] | None:
    path = _basemap_cache_path(config, _basemap_cache_id(crop, config, theme))
    if not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            tiles = data["tiles"]
            extent = tuple(float(v) for v in data["extent"].tolist())
        if tiles.ndim != 3 or len(extent) != 4:
            return None
        LOGGER.info("Basemap disk cache hit %s shape=%sx%s", path.name, tiles.shape[0], tiles.shape[1])
        return tiles, extent  # type: ignore[return-value]
    except (OSError, ValueError, KeyError) as exc:
        LOGGER.warning("Basemap cache unreadable %s (%s); rebuilding", path.name, exc)
        return None


def save_basemap_cache(
    crop: RadarCrop,
    config: Config,
    theme: Theme,
    tiles: np.ndarray,
    extent: tuple[float, float, float, float],
) -> Path:
    cache_dir = config.resolved_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _basemap_cache_path(config, _basemap_cache_id(crop, config, theme))
    np.savez_compressed(
        path,
        tiles=np.asarray(tiles, dtype=np.uint8),
        extent=np.array(extent, dtype=np.float64),
    )
    LOGGER.info("Basemap disk cache wrote %s (%s bytes)", path.name, path.stat().st_size)
    return path


def crop_osm_mosaic(
    img: np.ndarray,
    extent: tuple[float, float, float, float],
    west: float,
    south: float,
    east: float,
    north: float,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Trim extra OSM tile padding to the crop AABB before warping."""
    min_x, max_x, min_y, max_y = extent
    height, width = img.shape[:2]
    if height < 2 or width < 2 or max_x == min_x or max_y == min_y:
        return img, extent
    col0 = int(np.floor((west - min_x) / (max_x - min_x) * width))
    col1 = int(np.ceil((east - min_x) / (max_x - min_x) * width))
    row0 = int(np.floor((max_y - north) / (max_y - min_y) * height))
    row1 = int(np.ceil((max_y - south) / (max_y - min_y) * height))
    col0, col1 = max(0, col0 - 1), min(width, col1 + 1)
    row0, row1 = max(0, row0 - 1), min(height, row1 + 1)
    if col1 - col0 < 2 or row1 - row0 < 2:
        return img, extent
    cropped = img[row0:row1, col0:col1]
    new_min_x = min_x + col0 / width * (max_x - min_x)
    new_max_x = min_x + col1 / width * (max_x - min_x)
    new_max_y = max_y - row0 / height * (max_y - min_y)
    new_min_y = max_y - row1 / height * (max_y - min_y)
    return cropped, (new_min_x, new_max_x, new_min_y, new_max_y)


def _warp_basemap_to_crop(
    tiles: np.ndarray,
    extent_3857: tuple[float, float, float, float],
    crop: RadarCrop,
    out_px: int,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Reproject OSM onto a square covering the radar crop (not the full tile mosaic)."""
    min_x, max_x, min_y, max_y = extent_3857
    height, width, bands = tiles.shape
    src_transform = transform_from_bounds(min_x, min_y, max_x, max_y, width, height)
    west, south, east, north = _src_bounds(crop)
    dst_transform = transform_from_bounds(west, south, east, north, out_px, out_px)
    dst_crs = CRS.from_string(crop.crs)
    dst = np.zeros((bands, out_px, out_px), dtype=np.uint8)
    for band in range(bands):
        reproject(
            source=tiles[:, :, band],
            destination=dst[band],
            src_transform=src_transform,
            src_crs="EPSG:3857",
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )
    return np.transpose(dst, (1, 2, 0)), (west, east, south, north)


def _basemap_in_radar_crs(crop: RadarCrop, config: Config, theme: Theme):
    """Download OSM, crop to the map box, warp onto the radar grid, optionally from disk."""
    cached = load_basemap_cache(crop, config, theme)
    if cached is not None:
        return cached
    west, south, east, north = _mercator_aabb(crop)
    zoom = _tile_zoom(config.box_km)
    t_fetch = perf_counter()
    tiles, extent_3857 = cx.bounds2img(
        west,
        south,
        east,
        north,
        ll=False,
        zoom=zoom,
        source=theme.basemap,
        use_cache=True,
        headers={"User-Agent": config.user_agent},
    )
    LOGGER.info(
        "OSM tiles theme=%s zoom=%s mosaic=%sx%s in %.1fs",
        theme.name,
        zoom,
        tiles.shape[0],
        tiles.shape[1],
        perf_counter() - t_fetch,
    )
    cropped, extent_3857 = crop_osm_mosaic(tiles, extent_3857, west, south, east, north)
    if cropped.shape != tiles.shape:
        LOGGER.info(
            "Cropped OSM mosaic %sx%s → %sx%s before warp",
            tiles.shape[0],
            tiles.shape[1],
            cropped.shape[0],
            cropped.shape[1],
        )
    out_px = _basemap_out_size(config)
    t_warp = perf_counter()
    warped, extent = _warp_basemap_to_crop(cropped, extent_3857, crop, out_px)
    warped = _restyle_basemap(warped, theme)
    LOGGER.info(
        "Warped basemap theme=%s to %sx%s (%s) in %.1fs",
        theme.name,
        warped.shape[0],
        warped.shape[1],
        crop.crs,
        perf_counter() - t_warp,
    )
    save_basemap_cache(crop, config, theme, warped, extent)
    return warped, extent


def get_basemap(crop: RadarCrop, config: Config, theme: Theme):
    """Warped OSM covering the map crop, from disk cache when lat/lon/box match."""
    return _basemap_in_radar_crs(crop, config, theme)


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


def _offset_label(offset_min: float) -> str:
    if abs(offset_min) < 0.05:
        return "T=0 min"
    if abs(offset_min - round(offset_min)) < 0.05:
        return f"T={int(round(offset_min)):+d} min"
    return f"T={offset_min:+g} min"


def _alert_zone_ring(lon: float, lat: float, radius_km: float, crop_crs: str) -> np.ndarray:
    """Circle in the radar CRS (same metric as the warning disk)."""
    to_crop = Transformer.from_crs("EPSG:4326", crop_crs, always_xy=True)
    x0, y0 = to_crop.transform(lon, lat)
    theta = np.linspace(0.0, 2.0 * np.pi, 128, endpoint=True)
    radius_m = radius_km * 1000.0
    return np.column_stack((x0 + radius_m * np.cos(theta), y0 + radius_m * np.sin(theta)))


def _arrow_sites(
    crop: RadarCrop, flow: np.ndarray, config: Config
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Fixed grid + rain mask from one crop (T=0). Reused on every GIF frame."""
    if config.flow_arrow_density <= 0 or not config.show_flow_arrows:
        return None
    if flow is None or flow.shape[:2] != crop.rr.shape:
        return None
    n_max = config.box_km * config.box_km * config.flow_arrow_density
    if n_max < 0.5:
        return None
    n_side = max(1, int(round(math.sqrt(n_max))))
    height, width = crop.rr.shape
    rows = np.unique(
        np.clip(((np.arange(n_side) + 0.5) * height / n_side).astype(int), 0, height - 1)
    )
    cols = np.unique(
        np.clip(((np.arange(n_side) + 0.5) * width / n_side).astype(int), 0, width - 1)
    )
    if rows.size == 0 or cols.size == 0:
        return None
    fx = flow[np.ix_(rows, cols)][..., 0]
    fy = flow[np.ix_(rows, cols)][..., 1]
    rain = np.nan_to_num(crop.rr[np.ix_(rows, cols)], nan=0.0)
    speed = np.hypot(fx, fy)
    keep = (rain >= config.rr_vmin) & (speed >= 0.15)
    if not np.any(keep):
        return None
    return rows, cols, keep


def _draw_flow_arrows(
    ax,
    crop: RadarCrop,
    flow: np.ndarray,
    config: Config,
    theme: Theme,
    sites: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> None:
    """Quiver at frozen T=0 sites so arrows do not flicker as rain advects."""
    if config.flow_arrow_density <= 0:
        return
    if sites is None:
        sites = _arrow_sites(crop, flow, config)
    if sites is None or flow is None or flow.shape[:2] != crop.rr.shape:
        return
    rows, cols, keep = sites
    fx = flow[np.ix_(rows, cols)][..., 0]
    fy = flow[np.ix_(rows, cols)][..., 1]
    a, _, c, _, e, f, *_ = crop.transform
    cc, rr_i = np.meshgrid(cols, rows)
    xs = c + a * (cc + 0.5)
    ys = f + e * (rr_i + 0.5)
    u = fx * a
    v = fy * e
    ax.quiver(
        xs[keep],
        ys[keep],
        u[keep],
        v[keep],
        color=theme.text,
        alpha=0.55,
        scale_units="xy",
        scale=1.0,
        width=0.004,
        headwidth=3.2,
        headlength=4.0,
        zorder=6,
        pivot="tail",
    )


def _draw_radar_figure(
    crop: RadarCrop,
    config: Config,
    theme: Theme,
    *,
    offset_min: float | None = None,
    cached_basemap: tuple | None = None,
    flow: np.ndarray | None = None,
    arrow_sites: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
    dpi: float | None = None,
    basemap_interpolation: str = "lanczos",
):
    values = crop.dbzh if config.quantity == "dbzh" else crop.rr
    west, south, east, north = _src_bounds(crop)
    radar_extent = plotting_extent(values, crop.transform)
    data = _mask_overlay(values, config)
    norm, cbar_label = _color_scale(config)

    radar_stamp = crop.timestamp.astimezone(HELSINKI).strftime("%Y-%m-%d %H:%M %Z")
    stats = crop_stats(crop)

    if cached_basemap is None:
        t_map = perf_counter()
        cached_basemap = _basemap_in_radar_crs(crop, config, theme)
        LOGGER.info("Prepared basemap theme=%s in %.1fs", theme.name, perf_counter() - t_map)
    tiles, tile_extent = cached_basemap

    overlay_cmap = plt.get_cmap(config.cmap_for(theme)).copy()
    overlay_cmap.set_bad(alpha=0.0)
    overlay_cmap.set_under(alpha=0.0)
    cbar_cmap = plt.get_cmap(config.cmap_for(theme))

    fig, ax = plt.subplots(
        figsize=(config.figsize, config.figsize),
        dpi=dpi or config.dpi,
        facecolor=theme.face,
    )
    fig.subplots_adjust(left=0.04, right=0.88, top=0.88, bottom=0.06)
    ax.set_facecolor(theme.face)
    ax.imshow(
        tiles,
        extent=tile_extent,
        interpolation=basemap_interpolation,
        origin="upper",
        zorder=1,
    )
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
    if config.show_flow_arrows and config.flow_arrow_density > 0 and flow is not None:
        _draw_flow_arrows(ax, crop, flow, config, theme, sites=arrow_sites)
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
    offset_min: float | None = None,
    cached_basemap: tuple | None = None,
    flow: np.ndarray | None = None,
    arrow_sites: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> tuple[list[Path], tuple]:
    paths = [outputs] if isinstance(outputs, Path) else list(outputs)
    if not paths:
        raise ValueError("No output paths")
    paths[0].parent.mkdir(parents=True, exist_ok=True)

    fig, cached_basemap = _draw_radar_figure(
        crop,
        config,
        theme,
        offset_min=offset_min,
        cached_basemap=cached_basemap,
        flow=flow,
        arrow_sites=arrow_sites,
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
    frames: list[tuple[float, RadarCrop]],
    config: Config,
    theme: Theme,
    output: Path,
    *,
    flow: np.ndarray | None = None,
    cached_basemap: tuple | None = None,
) -> Path:
    """Animate T=0 → T=+15 with interpolated advection (forward only)."""
    if not frames:
        raise ValueError("No GIF frames")
    output.parent.mkdir(parents=True, exist_ok=True)
    images: list[Image.Image] = []
    cached = cached_basemap
    sites = _arrow_sites(frames[0][1], flow, config) if flow is not None else None
    gif_dpi = config.gif_dpi if config.gif_dpi > 0 else config.dpi
    t_gif = perf_counter()
    for index, (offset, crop) in enumerate(frames):
        t_frame = perf_counter()
        fig, cached = _draw_radar_figure(
            crop,
            config,
            theme,
            offset_min=offset,
            cached_basemap=cached,
            flow=flow,
            arrow_sites=sites,
            dpi=gif_dpi,
            basemap_interpolation="bilinear",
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        images.append(Image.open(buf).convert("RGB"))
        LOGGER.info(
            "GIF frame %s/%s T=%g min matplotlib %.1fs",
            index + 1,
            len(frames),
            offset,
            perf_counter() - t_frame,
        )
    LOGGER.info("GIF matplotlib %s frames in %.1fs", len(frames), perf_counter() - t_gif)
    fps = config.gif_fps if config.gif_fps > 0 else 1000.0 / max(config.gif_duration_ms, 1)
    frame_ms = int(round(1000.0 / fps))
    hold_ms = int(round(frame_ms * max(1.0, config.gif_hold)))
    durations = [frame_ms] * len(images)
    durations[0] = hold_ms
    durations[-1] = hold_ms
    palette = images[0].quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    quantized = [
        frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in images
    ]
    t_enc = perf_counter()
    quantized[0].save(
        output,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        optimize=False,
        disposal=2,
    )
    for image in images:
        image.close()
    for image in quantized:
        image.close()
    LOGGER.info("GIF encode in %.1fs", perf_counter() - t_enc)
    return output
