"""Run optical-flow nowcast without drawing a map.

  python -m fmi_radar.nowcast
  python -m fmi_radar.nowcast --time 202609040300 --lat YOUR_LAT --lon YOUR_LON
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .cli import _cmap_name
from .config import DEFAULT_BOX_KM, DEFAULT_LAT, DEFAULT_LON, THEMES, Config
from .log import configure_cli_logging, get_logger
from .mqtt import report_unavailable
from .pipeline import render_latest
from .s3 import parse_timestamp
from .timeout import call_with_timeout

LOGGER = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch FMI radar at T=-15…0, advect to T=+5/+10/+15, "
            "print will_rain flags, and write radar.gif."
        )
    )
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=DEFAULT_LON)
    parser.add_argument("--box-km", type=float, default=DEFAULT_BOX_KM)
    parser.add_argument(
        "--of-padding-km",
        type=float,
        default=20.0,
        help="Kilometres of optical-flow context on each side of --box-km (default: 20).",
    )
    parser.add_argument("--warn-radius-km", type=float, default=2.0)
    parser.add_argument(
        "--theme",
        choices=("dark", "light"),
        default="dark",
        help="Map theme for radar.gif.",
    )
    parser.add_argument(
        "--cmap",
        type=_cmap_name,
        default=None,
        help="Matplotlib colormap for rain overlay (overrides theme default).",
    )
    parser.add_argument("--cmap-dark", type=_cmap_name, default=None)
    parser.add_argument("--cmap-light", type=_cmap_name, default=None)
    parser.add_argument(
        "--alert-alpha",
        type=float,
        default=0.05,
        help="Fill opacity of the warning disk (0–1).",
    )
    parser.add_argument("--outdir", type=Path, default=Path("output"))
    parser.add_argument(
        "--gif",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write output/radar.gif (T=0 … T=+15). Use --no-gif to skip.",
    )
    parser.add_argument(
        "--time",
        default=None,
        help="Historic time (compact UTC YYYYMMDDHHMM or ISO). Default: latest.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_cli_logging()
    args = build_parser().parse_args(argv)
    config = Config(
        lat=args.lat,
        lon=args.lon,
        box_km=args.box_km,
        of_padding_km=args.of_padding_km,
        warn_radius_km=args.warn_radius_km,
        cmap=args.cmap,
        cmap_dark=args.cmap_dark,
        cmap_light=args.cmap_light,
        alert_alpha=args.alert_alpha,
        outdir=args.outdir,
        when=parse_timestamp(args.time) if args.time else None,
        skip_images=True,
        write_gif=args.gif,
        image_formats=(),
    )
    try:
        result = call_with_timeout(config.timeout_sec, render_latest, config, [THEMES[args.theme]])
    except Exception as exc:
        LOGGER.exception("Nowcast failed")
        report_unavailable(config, str(exc))
        print(f"unavailable: {exc}")
        return 1
    print(f"radar_time: {result.metadata['timestamp_utc']}")
    print(f"align_min: {result.metadata.get('align_min')}")
    print(f"anim_horizon_min: {result.metadata.get('anim_horizon_min')}")
    print(f"history: {result.metadata['history_offsets']}")
    print(f"flow_available: {result.metadata['flow_available']}")
    print(f"status: {result.alert.status}")
    print(f"mean_rr: {result.alert.mean_rr_mmh:.2f} mm/h")
    for lead, flag in sorted(result.will_rain.items()):
        print(f"will_rain_in_{lead}_minutes: {flag}")
    print(f"meta: {result.metadata_path}")
    if result.gif_path:
        print(f"gif: {result.gif_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
