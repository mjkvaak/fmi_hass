from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from fmi_radar.alert import RainAlert, observed_rain, will_rain_flag
from fmi_radar.config import THEMES, Config, Theme
from fmi_radar.flow import run_nowcast
from fmi_radar.mqtt import publish_result
from fmi_radar.persist import save_crop
from fmi_radar.plot import render_map
from fmi_radar.process import RadarCrop, crop_radar, crop_stats, extract_box
from fmi_radar.s3 import fetch_history, fetch_radar


@dataclass
class RenderResult:
    crop: RadarCrop
    alert: RainAlert
    nowcast_alerts: dict[int, RainAlert]
    will_rain: dict[int, str]
    images: dict[str, Path]
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
    will_rain: dict[int, str],
    history_offsets: list[int],
    flow_available: bool,
) -> dict:
    stats = crop_stats(crop)
    requested = config.when.isoformat() if config.when else None
    return {
        "timestamp_utc": crop.timestamp.isoformat(),
        "requested": requested,
        "s3_key": crop.s3_key,
        "url": crop.url,
        "lat": config.lat,
        "lon": config.lon,
        "box_km": config.box_km,
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
        "alert": alert.as_dict(),
        "nowcast": {str(lead): item.as_dict() for lead, item in nowcast_alerts.items()},
        "history_offsets": history_offsets,
        "flow_available": flow_available,
        **{_will_rain_key(lead): flag for lead, flag in will_rain.items()},
        **stats,
    }


def render_latest(
    config: Config | None = None,
    themes: list[Theme] | None = None,
) -> RenderResult:
    """Fetch a composite, nowcast, persist arrays, and write images + JSON."""
    config = config or Config()
    themes = themes or [THEMES["dark"]]
    config.outdir.mkdir(parents=True, exist_ok=True)

    t0_obj = fetch_radar(config)
    history_objs = fetch_history(config, t0_obj.timestamp)
    history_objs.setdefault(0, t0_obj)

    flow_config = replace(config, box_km=config.flow_box_km)
    history_crops = {
        offset: crop_radar(obj, flow_config) for offset, obj in history_objs.items()
    }
    t0_flow = history_crops[0]
    display = extract_box(t0_flow, config.lat, config.lon, config.box_km)

    alert = observed_rain(t0_flow, config)
    nowcast = run_nowcast(history_crops, config.nowcast_lead_min)
    nowcast_alerts: dict[int, RainAlert] = {}
    will_rain: dict[int, str] = {}
    for lead in config.nowcast_lead_min:
        if nowcast.flow_available and lead in nowcast.leads:
            predicted = observed_rain(nowcast.leads[lead], config)
            nowcast_alerts[lead] = replace(
                predicted, lead_minutes=lead, method="optical_flow"
            )
        will_rain[lead] = will_rain_flag(nowcast_alerts.get(lead))
        (config.outdir / f"{_will_rain_key(lead)}.txt").write_text(will_rain[lead] + "\n")

    array_path, _prev = save_crop(display, config, config.outdir)
    status_path = config.outdir / "status.txt"
    status_path.write_text(alert.payload() + "\n")
    (config.outdir / "mean_rr.txt").write_text(f"{alert.mean_rr_mmh:.4f}\n")

    images: dict[str, Path] = {}
    for theme in themes:
        for path in render_map(display, config, theme, _image_paths(config, theme)):
            images[f"{theme.name}_{path.suffix.lstrip('.')}"] = path

    stable = _write_stable_images(images, config.outdir)
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
    )
    metadata_path = config.outdir / "radar.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    result = RenderResult(
        crop=display,
        alert=alert,
        nowcast_alerts=nowcast_alerts,
        will_rain=will_rain,
        images=images,
        metadata_path=metadata_path,
        status_path=status_path,
        array_path=array_path,
        metadata=metadata,
    )
    publish_result(config, result)
    return result
