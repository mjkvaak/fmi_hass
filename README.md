# FMI precipitation radar for Home Assistant

Standalone Python tool: pull the latest FMI radar GeoTIFF from the public AWS S3 bucket, crop around a location, overlay rain on a map, and emit **DRY/RAIN** plus mean rain rate for Home Assistant over MQTT (or files).

This is **not** a HACS custom component yet. Run it on a machine that can reach S3 and your MQTT broker (the HASS host, a sidecar VM, or the same box as Mosquitto). A HACS integration would need a public GitHub repo; keep this private and use MQTT until you want that.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set FMI_RADAR_LAT / LON to your site
python -m fmi_radar --theme dark --format both
```

Stable Lovelace files (copied from the first rendered theme):

- `output/output.svg`
- `output/output.png`
- `output/status.txt` — `RAIN` or `DRY`
- `output/mean_rr.txt` — spatial mean mm/h inside the 2 km alert disk
- `output/radar.json` — full metadata
- `output/radar.npz` / `radar_prev.npz` — arrays for analysis
- `output/will_rain_in_5_minutes.txt` (also 10 and 15) — `true` / `false` / `unknown`
- `output/radar.gif` — T=−15…0 observed + T=+5/+10/+15 nowcast (on by default; `--no-gif` to skip)

Optical flow uses T=−15, T=−10, T=−5, and T=0 (5-minute FMI slots) on `--box-km` plus `--of-padding-km` on each side (default 10+20+20 = 50 km), then advects rain to T=+5/+10/+15 and crops back to the map. The 2 km alert disk is tested on that nowcast. Map titles and image timestamps use the **radar product time**, not wall-clock render time.

## CLI

| Flag | Default | Meaning |
| --- | --- | --- |
| `--lat` `--lon` | Helsinki example / env | Crop centre (WGS84) |
| `--box-km` | 10 | Map crop size (km) |
| `--of-padding-km` | 20 | Optical-flow margin on each side of the map (km) |
| `--warn-radius-km` | 2 | Alert disk drawn on the map; RAIN if any pixel ≥ 0.1 mm/h |
| `--theme` | both | `dark`, `light`, or `both` |
| `--cmap` | rainbow | Any matplotlib colormap name (`rainbow`, `turbo`, `plasma`, …) |
| `--cmap-dark` `--cmap-light` | | Per-theme cmap |
| `--alert-alpha` | 0.05 | Warning-disk fill opacity (0–1) |
| `--format` | png | `png`, `svg`, or `both` |
| `--time` | latest | Historic UTC compact `YYYYMMDDHHMM` or ISO |
| `--mqtt-host` | env `FMI_RADAR_MQTT_HOST` | Publish retained MQTT messages |
| `--gif` | on | Write `output/radar.gif` with the static maps. `--no-gif` skips it. |
| `--outdir` | output | Destination for images + status |

```bash
python -m fmi_radar --cmap turbo --theme dark --format both
python -m fmi_radar --time 202609040300 --theme dark --format both
```

Optical flow + animation (`output/radar.gif` is written with the static maps; `--no-gif` to skip):

```bash
source .venv/bin/activate
python -m fmi_radar --theme dark --format both --cmap turbo
python -m fmi_radar.nowcast --time 202609040300 --lat YOUR_LAT --lon YOUR_LON
```

Naive `--time` values are Europe/Helsinki; 12-digit compact times are UTC.

## Take into use with Home Assistant

Follow **[docs/hass.md](docs/hass.md)**. Short version:

1. Point `--lat/--lon` (or `.env`) at your site. Do not commit those values.
2. Run every 5 minutes (systemd timer or cron) with `--format both --theme dark` into a directory Home Assistant can read (for example `/config/www/fmi_radar/` or a bind-mounted folder). That writes `output.png` and `radar.gif`.
3. Publish MQTT (`FMI_RADAR_MQTT_HOST` + user/password in the environment, never in git).
4. Add MQTT sensors for `fmi_radar/status` and `fmi_radar/mean_rr`, and pick a Lovelace card on `output.png` (still) or `radar.gif` (animation).

## Data notes

FMI GeoTIFF: `Z[dBZ] = 0.5 * pixel - 32`. Rain rate uses Marshall–Palmer `Z = 200 R^1.6`. The bucket currently has reflectivity, not a separate RR raster. Linear colour scale 0–8 mm/h. Radar © FMI (CC BY 4.0); map © OSM.

Historic objects are only kept for about a week. Older days may use a different S3 key layout.

## Library

```python
from pathlib import Path
from fmi_radar import Config, render_latest
from fmi_radar.config import THEMES

render_latest(
    Config(lat=60.1719, lon=24.9414, outdir=Path("/config/www/fmi_radar"), image_formats=("png", "svg")),
    themes=[THEMES["dark"]],
)
```
