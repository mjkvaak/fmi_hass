from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from fmi_radar.alert import RainAlert, nowcast_rain
from fmi_radar.config import THEMES, Config, Theme
from fmi_radar.mqtt import publish_result
from fmi_radar.persist import save_crop
from fmi_radar.plot import render_map
from fmi_radar.process import RadarCrop, crop_radar, crop_stats
from fmi_radar.s3 import fetch_radar


@dataclass
class RenderResult:
    crop: RadarCrop
    alert: RainAlert
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


def _metadata(
    crop: RadarCrop,
    config: Config,
    images: dict[str, Path],
    alert: RainAlert,
    array_path: Path,
    status_path: Path,
    stable: dict[str, str],
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
        **stats,
    }


def render_latest(
    config: Config | None = None,
    themes: list[Theme] | None = None,
) -> RenderResult:
    """Fetch a composite, crop, warn, persist arrays, and write images + JSON.

    This is the function a future Home Assistant integration should call.
    """
    config = config or Config()
    themes = themes or [THEMES["dark"]]
    config.outdir.mkdir(parents=True, exist_ok=True)

    obj = fetch_radar(config)
    crop = crop_radar(obj, config)
    alert = nowcast_rain(crop, config, lead_minutes=0)
    array_path, _prev = save_crop(crop, config, config.outdir)
    status_path = config.outdir / "status.txt"
    status_path.write_text(alert.payload() + "\n")
    mean_path = config.outdir / "mean_rr.txt"
    mean_path.write_text(f"{alert.mean_rr_mmh:.4f}\n")

    images: dict[str, Path] = {}
    for theme in themes:
        for path in render_map(crop, config, theme, _image_paths(config, theme)):
            images[f"{theme.name}_{path.suffix.lstrip('.')}"] = path

    stable = _write_stable_images(images, config.outdir)
    metadata = _metadata(crop, config, images, alert, array_path, status_path, stable)
    metadata_path = config.outdir / "radar.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    result = RenderResult(
        crop=crop,
        alert=alert,
        images=images,
        metadata_path=metadata_path,
        status_path=status_path,
        array_path=array_path,
        metadata=metadata,
    )
    publish_result(config, result)
    return result
