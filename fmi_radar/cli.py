from __future__ import annotations

import argparse
from pathlib import Path

from matplotlib import colormaps

from fmi_radar.config import DEFAULT_BOX_KM, DEFAULT_LAT, DEFAULT_LON, THEMES, Config
from fmi_radar.mqtt import report_unavailable
from fmi_radar.pipeline import render_latest
from fmi_radar.timeout import call_with_timeout


def _cmap_name(value: str) -> str:
    name = value.strip()
    if name not in colormaps:
        known = ", ".join(sorted(colormaps)[:12])
        raise argparse.ArgumentTypeError(
            f"Unknown matplotlib cmap {value!r}. Examples: {known}, ..."
        )
    return name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch FMI precip radar, crop a local box, and render a map overlay."
    )
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=DEFAULT_LON)
    parser.add_argument(
        "--box-km",
        type=float,
        default=DEFAULT_BOX_KM,
        help="Square crop size in kilometres (default: 10).",
    )
    parser.add_argument(
        "--of-padding-km",
        type=float,
        default=20.0,
        help="Kilometres of optical-flow context on each side of --box-km (default: 20).",
    )
    parser.add_argument(
        "--theme",
        choices=("dark", "light", "both"),
        default="both",
        help="Map theme. 'both' writes radar_dark and radar_light.",
    )
    parser.add_argument(
        "--cmap",
        type=_cmap_name,
        default=None,
        help="Matplotlib colormap for rain overlay (overrides theme defaults).",
    )
    parser.add_argument("--cmap-dark", type=_cmap_name, default=None)
    parser.add_argument("--cmap-light", type=_cmap_name, default=None)
    parser.add_argument(
        "--alert-alpha",
        type=float,
        default=0.05,
        help="Fill opacity of the warning disk (0–1). The outline is slightly stronger.",
    )
    parser.add_argument(
        "--quantity",
        choices=("rr", "dbzh"),
        default="rr",
        help="rr = rain rate from Marshall–Palmer Z-R; dbzh = reflectivity.",
    )
    parser.add_argument("--outdir", type=Path, default=Path("output"))
    parser.add_argument(
        "--warn-radius-km",
        type=float,
        default=2.0,
        help="Circular warning cell around lat/lon (default: 2 km). RAIN if any pixel inside rains.",
    )
    parser.add_argument(
        "--time",
        default=None,
        help=(
            "Historic timestamp; nearest 5-minute S3 object is used. "
            "Naive values are Europe/Helsinki. Examples: "
            "2026-09-01T15:00, 2026-09-01T12:00Z, 202609011200."
        ),
    )
    parser.add_argument(
        "--format",
        dest="image_format",
        choices=("png", "svg", "both"),
        default="png",
        help="Image format. SVG embeds the map as a raster (good for HASS scaling).",
    )
    parser.add_argument(
        "--mqtt-host",
        default=None,
        help="If set (or FMI_RADAR_MQTT_HOST), publish status/mean_rr to this broker.",
    )
    parser.add_argument("--mqtt-port", type=int, default=None)
    parser.add_argument(
        "--mqtt-prefix",
        default=None,
        help="MQTT topic prefix (default: fmi_radar).",
    )
    parser.add_argument(
        "--gif",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write output/radar.gif (T=0 … T=+15) along with static maps. Use --no-gif to skip.",
    )
    parser.add_argument(
        "--gif-fps",
        type=float,
        default=3.0,
        help="Animation frame rate (default: 3).",
    )
    parser.add_argument(
        "--gif-step-min",
        type=float,
        default=2.5,
        help="Minutes between interpolated nowcast frames (default: 2.5).",
    )
    parser.add_argument(
        "--flow-arrows",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Draw optical-flow arrows on maps and the GIF. Use --no-flow-arrows to hide.",
    )
    parser.add_argument(
        "--flow-arrow-density",
        type=float,
        default=0.01,
        help="Arrows per km² of --box-km (default: 0.01). Use 0 or a negative value to hide arrows.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=240.0,
        help="Abort download+render after this many seconds (default: 240).",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=60.0,
        help="Wait this long for the expected S3 slot before falling back (default: 60).",
    )
    parser.add_argument(
        "--product",
        default=None,
        help="S3 filename suffix after the timestamp (advanced).",
    )
    return parser


def _formats(choice: str) -> tuple[str, ...]:
    if choice == "both":
        return ("png", "svg")
    return (choice,)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config(
        lat=args.lat,
        lon=args.lon,
        box_km=args.box_km,
        of_padding_km=args.of_padding_km,
        quantity=args.quantity,
        outdir=args.outdir,
        warn_radius_km=args.warn_radius_km,
        when=parse_timestamp(args.time) if args.time else None,
        image_formats=_formats(args.image_format),
        cmap=args.cmap,
        cmap_dark=args.cmap_dark,
        cmap_light=args.cmap_light,
        alert_alpha=args.alert_alpha,
        write_gif=args.gif,
        gif_fps=args.gif_fps,
        gif_step_min=args.gif_step_min,
        show_flow_arrows=args.flow_arrows,
        flow_arrow_density=args.flow_arrow_density,
        poll_seconds=args.poll_seconds,
        timeout_sec=args.timeout,
    )
    if args.product:
        config.product = args.product
    if args.mqtt_host:
        config.mqtt_host = args.mqtt_host
    if args.mqtt_port is not None:
        config.mqtt_port = args.mqtt_port
    if args.mqtt_prefix:
        config.mqtt_prefix = args.mqtt_prefix
    if args.theme == "both":
        themes = [THEMES["dark"], THEMES["light"]]
    else:
        themes = [THEMES[args.theme]]
    try:
        result = call_with_timeout(config.timeout_sec, render_latest, config, themes)
    except Exception as exc:
        report_unavailable(config, str(exc))
        print(f"unavailable: {exc}")
        return 1
    for name, path in result.images.items():
        print(f"{name}: {path}")
    print(f"meta: {result.metadata_path}")
    print(f"array: {result.array_path}")
    print(f"status: {result.alert.status} ({result.status_path})")
    for lead, flag in sorted(result.will_rain.items()):
        print(f"will_rain_in_{lead}_minutes: {flag}")
    print(
        f"radar_time: {result.metadata['timestamp_utc']}  "
        f"mean_rr: {result.alert.mean_rr_mmh:.2f} mm/h  "
        f"max_rr: {result.alert.max_rr_mmh:.2f} mm/h"
    )
    if result.gif_path:
        print(f"gif: {result.gif_path}")
    return 0
