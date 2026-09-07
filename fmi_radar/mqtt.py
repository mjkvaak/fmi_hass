"""Optional MQTT publish for Home Assistant.

Credentials come from environment / Config — never from the repo.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fmi_radar.alert import RainAlert
    from fmi_radar.config import Config
    from fmi_radar.pipeline import RenderResult


def publish_result(config: "Config", result: "RenderResult") -> None:
    if not config.mqtt_host:
        return

    import paho.mqtt.client as mqtt

    alert: RainAlert = result.alert
    prefix = config.mqtt_prefix.rstrip("/")
    qos = 1
    state = {
        "status": alert.status,
        "mean_rr_mmh": round(alert.mean_rr_mmh, 4),
        "max_rr_mmh": round(alert.max_rr_mmh, 4),
        "threshold_mmh": alert.threshold_mmh,
        "radius_km": alert.radius_km,
        "lead_minutes": alert.lead_minutes,
        "method": alert.method,
        "wet_pixels": alert.wet_pixels,
        "pixels_in_disk": alert.pixels_in_disk,
        "timestamp_utc": result.metadata.get("timestamp_utc"),
        "output_svg": str(config.outdir / "output.svg"),
        "output_png": str(config.outdir / "output.png"),
    }

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fmi_radar")
    if config.mqtt_username:
        client.username_pw_set(config.mqtt_username, config.mqtt_password or None)
    client.connect(config.mqtt_host, config.mqtt_port, keepalive=20)
    client.loop_start()
    try:
        publishes = [
            client.publish(f"{prefix}/status", alert.status, qos=qos, retain=True),
            client.publish(
                f"{prefix}/mean_rr", f"{alert.mean_rr_mmh:.4f}", qos=qos, retain=True
            ),
            client.publish(
                f"{prefix}/max_rr", f"{alert.max_rr_mmh:.4f}", qos=qos, retain=True
            ),
            client.publish(
                f"{prefix}/timestamp",
                str(state["timestamp_utc"] or ""),
                qos=qos,
                retain=True,
            ),
            client.publish(f"{prefix}/state", json.dumps(state), qos=qos, retain=True),
        ]
        for msg in publishes:
            msg.wait_for_publish(timeout=5)
    finally:
        client.loop_stop()
        client.disconnect()
