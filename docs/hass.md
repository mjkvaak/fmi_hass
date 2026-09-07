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

## 2. systemd timer (every 5 minutes)

`/etc/systemd/system/fmi-radar.service`:

```ini
[Unit]
Description=FMI precipitation radar snapshot
After=network-online.target

[Service]
Type=oneshot
User=fmiradar
EnvironmentFile=/etc/fmi-radar.env
WorkingDirectory=/opt/fmi_radar
ExecStart=/opt/fmi_radar/.venv/bin/python -m fmi_radar --theme dark --format both --outdir /var/lib/fmi_radar --cmap plasma
```

`/etc/systemd/system/fmi-radar.timer`:

```ini
[Unit]
Description=FMI radar every 5 minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fmi-radar.timer
```

## 3. MQTT entities

Broker: Settings → Devices & services → MQTT (already used by most HASS installs).

`configuration.yaml`:

```yaml
mqtt:
  sensor:
    - name: FMI radar status
      state_topic: fmi_radar/status
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

## 4. Map image on a dashboard

PNG is the reliable Lovelace camera/picture format. SVG is written as `output.svg` for browsers or a Webpage card.

If `--outdir` is `/config/www/fmi_radar`:

```yaml
camera:
  - platform: local_file
    name: FMI radar
    file_path: /config/www/fmi_radar/output.png

# Lovelace
type: picture-entity
entity: camera.fmi_radar
show_state: false
```

Or without a camera:

```yaml
type: picture
image: /local/fmi_radar/output.png
```

Core `local_file` does not refresh SVG well; prefer `output.png` for the card and keep `output.svg` if you embed it elsewhere.

## 5. What HASS receives (minimum vs extra)

| Need | Source |
| --- | --- |
| DRY / RAIN | MQTT `fmi_radar/status` or `status.txt` |
| Mean rain rate in 2 km disk | MQTT `fmi_radar/mean_rr` or `mean_rr.txt` |
| Rain in 5 / 10 / 15 minutes | MQTT `fmi_radar/will_rain_in_X_minutes` (`true`/`false`/`unknown`) |
| Latest picture | `output.png` (and `output.svg`); title is radar product time |
| Max rate, wet pixel count, timestamp, nowcast | MQTT `fmi_radar/state` JSON / `radar.json` |

## 6. HACS later

When you want a first-class integration:

1. Make a **public** GitHub repo (HACS custom repositories generally cannot stay private).
2. Add `custom_components/fmi_radar/` with `manifest.json`, a sensor that calls `render_latest()`, and `hacs.json`.
3. Users would still need network to FMI S3; MQTT would become optional.

Until then, the timer + MQTT path above is the integration.
