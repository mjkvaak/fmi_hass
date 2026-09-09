# Using this with Home Assistant

## Recommended: HACS custom integration

This repository is laid out as a HACS **Integration** ([structure](https://www.hacs.xyz/docs/publish/integration/), [custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/)).

1. In HACS, open the ⋮ menu → **Custom repositories**.
2. URL: `https://github.com/mjkvaak/fmi_hass`
3. Type: **Integration**
4. **Add**, then download **FMI Precipitation Radar**.
5. Restart Home Assistant.
6. Settings → Devices & services → Add integration → **FMI Precipitation Radar**.
7. Confirm **lat / lon** (defaults to the Home Assistant home location if that is inside the FMI Finnish composite, otherwise Helsinki centre), **map box (km)**, **alert zone radius (km)**, and the other setup fields. The composite covers Finland and neighbouring parts of Estonia, Sweden, and Norway. Polling starts with HA and stops when HA stops or you disable the entry.

Lovelace still/GIF:

```yaml
type: picture-entity
entity: camera.fmi_radar_map
show_state: false
```

Files also land under `/config/www/fmi_radar/<entry id prefix>/` (`output.png`, `radar.gif`). Those images include the crop centre; serve `/local/` only on an authenticated Home Assistant instance. Do not commit `output/`.

Live updates fail (entities become unavailable) if the FMI composite is **more than 15 minutes old**, because a wall-clock T=0…+15 nowcast is then impossible.

Logging uses the standard Home Assistant logger (`fmi_radar`). Enable debug with:

```yaml
logger:
  default: info
  logs:
    fmi_radar: debug
```

## Optional: CLI sidecar + MQTT

Use this only if you cannot run the heavy GIS stack inside Home Assistant. Same host as Mosquitto/HASS is simplest.

```bash
sudo useradd --system --home /opt/fmi_radar --shell /usr/sbin/nologin fmiradar || true
sudo mkdir -p /opt/fmi_radar /var/lib/fmi_radar
sudo python3 -m venv /opt/fmi_radar/.venv
sudo /opt/fmi_radar/.venv/bin/pip install -r /opt/fmi_radar/requirements.txt
```

Clone this repo and `pip install -e .` (or copy `custom_components/fmi_radar` onto `PYTHONPATH`). Create `/etc/fmi-radar.env` (mode `0640`, not in git):

```bash
FMI_RADAR_LAT=YOUR_LAT
FMI_RADAR_LON=YOUR_LON
FMI_RADAR_MQTT_HOST=127.0.0.1
FMI_RADAR_MQTT_PORT=1883
FMI_RADAR_MQTT_USER=fmi_radar
FMI_RADAR_MQTT_PASSWORD=change-me
FMI_RADAR_MQTT_PREFIX=fmi_radar
```

### MQTT broker (Mosquitto)

**Debian/Ubuntu:**

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
```

**Home Assistant OS:** Settings → Add-ons → Mosquitto broker. Point `FMI_RADAR_MQTT_HOST` at a hostname the sidecar can reach. Use TLS (typically port 8883) if the broker is not on localhost.

### systemd timer (aligned with S3 publish time)

FMI 5-minute GeoTIFFs usually land **about 4–6 minutes after** the product timestamp. Fire **one minute after each 5-minute mark**.

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

### MQTT entities (sidecar only)

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
```
