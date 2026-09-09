from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from datetime import datetime, timezone
from time import perf_counter

from .alert import RainAlert, observed_rain, will_rain_flag
from .config import THEMES, Config, Theme
from .flow import advect_crop, run_nowcast
from .freshness import ensure_live_product_fresh
from .log import get_logger
from .mqtt import publish_result
from .persist import save_crop
from .plot import get_basemap, render_map, write_radar_gif
from .process import RadarCrop, crop_radar, crop_stats, extract_box, extract_flow
from .s3 import fetch_history, fetch_radar

LOGGER = get_logger(__name__)


class _Steps:
    def __init__(self) -> None:
        self.t0 = perf_counter()
        self.mark = self.t0

    def info(self, msg: str, *args) -> None:
        now = perf_counter()
        LOGGER.info(
            "+%.1fs  Δ%.1fs  " + msg,
            now - self.t0,
            now - self.mark,
            *args,
        )
        self.mark = now


@dataclass
class RenderResult:
    crop: RadarCrop
    alert: RainAlert
    nowcast_alerts: dict[int, RainAlert]
    will_rain: dict[int, bool | None]
    images: dict[str, Path]
    gif_path: Path | None
    metadata_path: Path
    status_path: Path
    array_path: Path
    metadata: dict


def _image_paths(config: Config, theme: Theme) -> list[Path]:
    return [config.outdir / f"radar_{theme.name}.{fmt}" for fmt in config.image_formats]


def _images_meta(images: dict[str, Path]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    for path in images.values():
        theme = path.stem.removeprefix("radar_")
        grouped.setdefault(theme, {})[path.suffix.lstrip(".")] = str(path)
    return grouped


def _write_stable_images(images: dict[str, Path], outdir: Path) -> dict[str, str]:
    """Copy the first rendered theme to stable HASS paths output.svg / output.png."""
    stable: dict[str, str] = {}
    for fmt in ("svg", "png"):
        matches = [path for path in images.values() if path.suffix.lower() == f".{fmt}"]
        if not matches:
            continue
        dest = outdir / f"output.{fmt}"
        shutil.copyfile(matches[0], dest)
        stable[fmt] = str(dest)
    return stable


def _will_rain_key(lead: int) -> str:
    return f"will_rain_in_{lead}_minutes"


def _metadata(
    crop: RadarCrop,
    config: Config,
    images: dict[str, Path],
    alert: RainAlert,
    array_path: Path,
    status_path: Path,
    stable: dict[str, str],
    nowcast_alerts: dict[int, RainAlert],
    will_rain: dict[int, bool | None],
    history_offsets: list[int],
    flow_available: bool,
    gif_path: Path | None,
) -> dict:
    stats = crop_stats(crop)
    requested = config.when.isoformat() if config.when else None
    return {
        "timestamp_utc": crop.timestamp.isoformat(),
        "requested": requested,
        "s3_key": crop.s3_key,
        "url": crop.url,
        "published_utc": None,
        "lat": config.lat,
        "lon": config.lon,
        "box_km": config.box_km,
        "of_padding_km": config.of_padding_km,
        "flow_box_km": config.flow_box_km,
        "warn_radius_km": config.warn_radius_km,
        "crs": crop.crs,
        "quantity": config.quantity,
        "product": config.product,
        "formats": list(config.image_formats),
        "images": _images_meta(images),
        "array": str(array_path),
        "status_file": str(status_path),
        "output_svg": stable.get("svg"),
        "output_png": stable.get("png"),
        "gif": str(gif_path) if gif_path else None,
        "alert": alert.as_dict(),
        "nowcast": {str(lead): item.as_dict() for lead, item in nowcast_alerts.items()},
        "history_offsets": history_offsets,
        "flow_available": flow_available,
        **{_will_rain_key(lead): flag for lead, flag in will_rain.items()},
        **stats,
    }


def _gif_offsets(config: Config, max_lead: float) -> list[float]:
    max_lead = max(0.0, float(max_lead))
    if max_lead < 1e-6:
        return [0.0]
    step = max(0.5, float(config.gif_step_min))
    offsets = [0.0]
    t = 0.0
    while t + step < max_lead - 1e-6:
        t += step
        offsets.append(round(t, 4))
    if offsets[-1] < max_lead - 1e-6:
        offsets.append(round(max_lead, 4))
    return offsets


def _align_lead_min(product_time: datetime, config: Config) -> float:
    """Minutes to advect so T=0 matches wall clock. Historic `--time` stays at the product."""
    if config.when is not None:
        return 0.0
    now = datetime.now(timezone.utc)
    lag = (now - product_time.astimezone(timezone.utc)).total_seconds() / 60.0
    if lag <= 0:
        return 0.0
    step = max(0.5, float(config.gif_step_min))
    aligned = round(lag / step) * step
    return float(min(max(aligned, 0.0), config.max_advect_min))


def render_latest(
    config: Config | None = None,
    themes: list[Theme] | None = None,
) -> RenderResult:
    """Fetch a composite, nowcast, persist arrays, and write images + JSON."""
    config = config or Config()
    themes = themes or [THEMES["dark"]]
    config.outdir.mkdir(parents=True, exist_ok=True)
    steps = _Steps()
    LOGGER.info(
        "Starting radar update lat=%.4f lon=%.4f box=%.1f km alert=%.1f km historic=%s",
        config.lat,
        config.lon,
        config.box_km,
        config.warn_radius_km,
        config.when is not None,
    )

    t0_obj = fetch_radar(config)
    steps.info("Using FMI object %s (product %s)", t0_obj.key, t0_obj.timestamp.isoformat())
    ensure_live_product_fresh(t0_obj.timestamp, config)
    history_objs = fetch_history(config, t0_obj.timestamp)
    history_objs.setdefault(0, t0_obj)
    steps.info("History offsets present: %s", sorted(history_objs))

    flow_km = config.flow_box_km
    flow_config = replace(config, box_km=flow_km, of_padding_km=0.0)
    history_crops = {}
    for offset, obj in sorted(history_objs.items()):
        history_crops[offset] = crop_radar(obj, flow_config)
        steps.info(
            "Cropped T=%s min flow window %sx%s",
            offset,
            history_crops[offset].rr.shape[0],
            history_crops[offset].rr.shape[1],
        )
    t0_flow = history_crops[0]
    nowcast = run_nowcast(history_crops, config.nowcast_lead_min)
    if not nowcast.flow_available:
        LOGGER.warning("Optical flow unavailable; will_rain flags will be unknown")
    align_min = _align_lead_min(t0_flow.timestamp, config) if nowcast.flow is not None else 0.0
    anim_horizon = min(float(max(config.nowcast_lead_min)), config.max_advect_min - align_min)
    anim_horizon = max(0.0, anim_horizon)
    steps.info(
        "Nowcast flow=%s align=%.1f min anim_horizon=%.1f min",
        nowcast.flow_available,
        align_min,
        anim_horizon,
    )

    if align_min > 0 and nowcast.flow is not None:
        aligned_flow = advect_crop(t0_flow, nowcast.flow, align_min)
    else:
        aligned_flow = t0_flow
    display = extract_box(aligned_flow, config.lat, config.lon, config.box_km)
    display_flow = None
    if nowcast.flow is not None:
        display_flow = extract_flow(
            nowcast.flow, t0_flow, config.lat, config.lon, config.box_km
        )
    steps.info(
        "Display crop %sx%s (map box %.1f km; flow was %.1f km)",
        display.rr.shape[0],
        display.rr.shape[1],
        config.box_km,
        flow_km,
    )

    alert = observed_rain(aligned_flow, config)
    nowcast_alerts: dict[int, RainAlert] = {}
    will_rain: dict[int, bool | None] = {}
    for lead in config.nowcast_lead_min:
        product_lead = align_min + lead
        if (
            nowcast.flow is not None
            and product_lead <= config.max_advect_min + 1e-6
        ):
            predicted = observed_rain(
                advect_crop(t0_flow, nowcast.flow, product_lead), config
            )
            nowcast_alerts[lead] = replace(
                predicted, lead_minutes=lead, method="optical_flow"
            )
        will_rain[lead] = will_rain_flag(nowcast_alerts.get(lead))
        (config.outdir / f"{_will_rain_key(lead)}.txt").write_text(
            json.dumps(will_rain[lead]) + "\n"
        )
    steps.info("Alerts and will_rain flags written")

    array_path, _prev = save_crop(display, config, config.outdir)
    status_path = config.outdir / "status.txt"
    status_path.write_text(alert.payload() + "\n")
    (config.outdir / "mean_rr.txt").write_text(f"{alert.mean_rr_mmh:.4f}\n")
    steps.info("Persisted radar.npz and status files")

    images: dict[str, Path] = {}
    gif_path: Path | None = None
    gif_theme = themes[0] if themes else THEMES["dark"]
    basemap_by_theme: dict[str, tuple] = {}
    if not config.skip_images:
        for theme in themes:
            basemap_by_theme[theme.name] = get_basemap(display, config, theme)
            steps.info("Basemap ready theme=%s", theme.name)
            paths, _cached = render_map(
                display,
                config,
                theme,
                _image_paths(config, theme),
                flow=display_flow,
                cached_basemap=basemap_by_theme[theme.name],
            )
            for path in paths:
                images[f"{theme.name}_{path.suffix.lstrip('.')}"] = path
            steps.info("Rendered still theme=%s", theme.name)
        stable = _write_stable_images(images, config.outdir)
    else:
        stable = {}
        if config.write_gif:
            basemap_by_theme[gif_theme.name] = get_basemap(display, config, gif_theme)
            steps.info("Prepared GIF basemap theme=%s (no stills)", gif_theme.name)

    if config.write_gif:
        sequence: list[tuple[float, RadarCrop]] = []
        for offset in _gif_offsets(config, anim_horizon):
            product_lead = align_min + offset
            if offset <= 0:
                sequence.append((0.0, display))
            elif nowcast.flow is not None and product_lead <= config.max_advect_min + 1e-6:
                advected = advect_crop(t0_flow, nowcast.flow, product_lead)
                sequence.append(
                    (
                        offset,
                        extract_box(advected, config.lat, config.lon, config.box_km),
                    )
                )
        if sequence:
            steps.info("Built %s GIF frame crop(s)", len(sequence))
            gif_path = write_radar_gif(
                sequence,
                config,
                gif_theme,
                config.outdir / "radar.gif",
                flow=display_flow,
                cached_basemap=basemap_by_theme.get(gif_theme.name),
            )
            steps.info("Wrote GIF (%s frames) %s", len(sequence), gif_path)
            images["gif"] = gif_path

    metadata = _metadata(
        display,
        config,
        images,
        alert,
        array_path,
        status_path,
        stable,
        nowcast_alerts,
        will_rain,
        nowcast.history_offsets,
        nowcast.flow_available,
        gif_path,
    )
    if t0_obj.published is not None:
        metadata["published_utc"] = t0_obj.published.isoformat()
    metadata["product_timestamp_utc"] = t0_flow.timestamp.isoformat()
    metadata["align_min"] = align_min
    metadata["anim_horizon_min"] = anim_horizon
    metadata_path = config.outdir / "radar.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    result = RenderResult(
        crop=display,
        alert=alert,
        nowcast_alerts=nowcast_alerts,
        will_rain=will_rain,
        images=images,
        gif_path=gif_path,
        metadata_path=metadata_path,
        status_path=status_path,
        array_path=array_path,
        metadata=metadata,
    )
    publish_result(config, result)
    steps.info(
        "Update done status=%s mean_rr=%.2f mm/h gif=%s",
        alert.status,
        alert.mean_rr_mmh,
        gif_path,
    )
    return result
