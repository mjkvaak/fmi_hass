# Using this with Home Assistant

Recommended path: **this script on a timer + MQTT + files on disk**. That does not need HACS or a public GitHub repo.

A later HACS custom integration would wrap the same `render_latest()` call inside Home Assistant. The HACS default store and most custom-repo installs expect a **public** GitHub repository. Keep this project private until you are ready to publish.

## 1. Install on the machine that will poll FMI

Same host as Mosquitto/HASS is simplest.

```bash
sudo useradd --system --home /opt/fmi_radar --shell /usr/sbin/nologin fmiradar || true
sudo mkdir -p /opt/fmi_radar /var/lib/fmi_radar
sudo python3 -m venv /opt/fmi_radar/.venv
sudo /opt/fmi_radar/.venv/bin/pip install -r /opt/fmi_radar/requirements.txt
```

Copy the `fmi_radar` package into `/opt/fmi_radar/`. Create `/etc/fmi-radar.env` (mode `0640`, not in git):

```bash
FMI_RADAR_LAT=YOUR_LAT
FMI_RADAR_LON=YOUR_LON
FMI_RADAR_MQTT_HOST=127.0.0.1
FMI_RADAR_MQTT_PORT=1883
FMI_RADAR_MQTT_USER=fmi_radar
FMI_RADAR_MQTT_PASSWORD=change-me
FMI_RADAR_MQTT_PREFIX=fmi_radar
```

If Home Assistant is in Docker/HAOS, mount a shared folder (example: `/config/www/fmi_radar`) as `--outdir` so Lovelace can serve `/local/fmi_radar/output.png`.

## 2. MQTT broker (Mosquitto)

The sidecar publishes retained messages. Install a broker if you do not already have one (Home Assistant OS / Supervised usually already runs the Mosquitto add-on).

**Debian/Ubuntu (same host as the script):**

```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

Create a user (do not put this password in git):

```bash
sudo mosquitto_passwd -c /etc/mosquitto/passwd fmi_radar
sudo chown mosquitto:mosquitto /etc/mosquitto/passwd
sudo chmod 640 /etc/mosquitto/passwd
```

`/etc/mosquitto/conf.d/fmi-radar.conf`:

```conf
listener 1883 127.0.0.1
allow_anonymous false
password_file /etc/mosquitto/passwd
```

```bash
sudo systemctl restart mosquitto
mosquitto_sub -h 127.0.0.1 -u fmi_radar -P 'your-password' -t 'fmi_radar/#' -v
```

**Home Assistant OS:** Settings → Add-ons → Mosquitto broker → Install → Start. Create a user under Settings → People → **MQTT** user (or the add-on local users). Point `FMI_RADAR_MQTT_HOST` at the broker hostname the sidecar can reach (`core-mosquitto` on HAOS, or the HA host IP from a VM).

Then in Home Assistant: Settings → Devices & services → **MQTT** → configure the same broker.

## 3. systemd timer (aligned with S3 publish time)

FMI 5-minute GeoTIFFs usually land **about 4–6 minutes after** the product timestamp (at 11:14 UTC the 11:10 slot was still missing; 11:05 was latest). A timer on `:00,:05,:10` often runs before the new file exists, so you keep the previous slot and T=+15 is only ~5 minutes of real lead.

Fire **one minute after each 5-minute mark** (`:01,:06,:11,…`) — about 6 minutes after valid time, when the object is usually present. The script also skips a slot younger than `publish_lag_min` (default 5) and waits up to `--poll-seconds` (default 60) for it.

`/etc/systemd/system/fmi-radar.service`:

```ini
[Unit]
Description=FMI precipitation radar snapshot
After=network-online.target mosquitto.service

[Service]
Type=oneshot
User=fmiradar
EnvironmentFile=/etc/fmi-radar.env
WorkingDirectory=/opt/fmi_radar
ExecStart=/opt/fmi_radar/.venv/bin/python -m fmi_radar --theme dark --format both --outdir /var/lib/fmi_radar
```

That writes `output.png`, `output.svg`, and `radar.gif`. Use `--no-gif` only if you want stills.

`/etc/systemd/system/fmi-radar.timer`:

```ini
[Unit]
Description=FMI radar after each 5-minute composite is published

[Timer]
OnBootSec=30s
OnCalendar=*-*-* *:01,06,11,16,21,26,31,36,41,46,51,56:00
AccuracySec=5s
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fmi-radar.timer
```

## 4. MQTT entities

Broker: Settings → Devices & services → MQTT (already used by most HASS installs).

`configuration.yaml`:

```yaml
mqtt:
  sensor:
    - name: FMI radar health
      state_topic: fmi_radar/health
      icon: mdi:heart-pulse
    - name: FMI radar status
      state_topic: fmi_radar/status
      availability:
        - topic: fmi_radar/health
          payload_available: ok
          payload_not_available: unavailable
      icon: mdi:weather-rainy
    - name: FMI radar mean rain rate
      state_topic: fmi_radar/mean_rr
      unit_of_measurement: mm/h
      device_class: precipitation_intensity
      state_class: measurement
      icon: mdi:weather-pouring
    - name: FMI radar max rain rate
      state_topic: fmi_radar/max_rr
      unit_of_measurement: mm/h
      device_class: precipitation_intensity
      state_class: measurement
    - name: FMI radar timestamp
      state_topic: fmi_radar/timestamp
    - name: FMI radar rain in 5 minutes
      state_topic: fmi_radar/will_rain_in_5_minutes
    - name: FMI radar rain in 10 minutes
      state_topic: fmi_radar/will_rain_in_10_minutes
    - name: FMI radar rain in 15 minutes
      state_topic: fmi_radar/will_rain_in_15_minutes
    - name: FMI radar JSON
      state_topic: fmi_radar/state
      value_template: "{{ value_json.status }}"
      json_attributes_topic: fmi_radar/state
```

Retained messages mean HASS picks up the last RAIN/DRY after a restart.

If you cannot use MQTT, `command_line` sensors can `cat` `status.txt` and `mean_rr.txt` from a path listed in `homeassistant.allowlist_external_dirs`.

## 5. Map image on a dashboard

Each run writes a still (`output.png`) and an animation (`radar.gif`). Use whichever card you prefer; both files update every 5 minutes.

PNG is the reliable Lovelace **camera** format. GIF plays in a **picture** card in the browser. SVG is written as `output.svg` for browsers or a Webpage card.

If `--outdir` is `/config/www/fmi_radar`:

```yaml
camera:
  - platform: local_file
    name: FMI radar
    file_path: /config/www/fmi_radar/output.png

# Lovelace — still
type: picture-entity
entity: camera.fmi_radar
show_state: false

# Lovelace — T=0 … T=+15 nowcast animation
type: picture
image: /local/fmi_radar/radar.gif
```

Or the still without a camera:

```yaml
type: picture
image: /local/fmi_radar/output.png
```

Core `local_file` does not refresh SVG well and is a poor fit for GIF; prefer `output.png` for the camera entity and `radar.gif` on a picture card.

## 6. What HASS receives (minimum vs extra)

| Need | Source |
| --- | --- |
| DRY / RAIN / unavailable | MQTT `fmi_radar/status` or `status.txt` |
| Sidecar health | MQTT `fmi_radar/health` (`ok` / `unavailable`) |
| Mean rain rate in 2 km disk | MQTT `fmi_radar/mean_rr` or `mean_rr.txt` |
| Rain in 5 / 10 / 15 minutes | MQTT `fmi_radar/will_rain_in_X_minutes` (`true`/`false`/`unknown`) |
| Latest still | `output.png` (and `output.svg`); title is radar product time |
| Past + nowcast animation | `radar.gif` (T=0…+15, forward) |
| Max rate, wet pixel count, timestamp, nowcast | MQTT `fmi_radar/state` JSON / `radar.json` |

## 7. HACS later

When you want a first-class integration:

1. Make a **public** GitHub repo (HACS custom repositories generally cannot stay private).
2. Add `custom_components/fmi_radar/` with `manifest.json`, a sensor that calls `render_latest()`, and `hacs.json`.
3. Users would still need network to FMI S3; MQTT would become optional.

Until then, the timer + MQTT path above is the integration.
