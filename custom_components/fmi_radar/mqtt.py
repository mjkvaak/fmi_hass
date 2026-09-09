"""Optional MQTT publish for Home Assistant.

Credentials come from environment / Config — never from the repo.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fmi_radar.alert import STATUS_UNAVAILABLE
from fmi_radar.log import get_logger

if TYPE_CHECKING:
    from fmi_radar.alert import RainAlert
    from fmi_radar.config import Config
    from fmi_radar.pipeline import RenderResult

HEALTH_OK = "ok"
HEALTH_UNAVAILABLE = "unavailable"
LOGGER = get_logger(__name__)


def _client(config: "Config"):
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fmi_radar")
    if config.mqtt_username:
        client.username_pw_set(config.mqtt_username, config.mqtt_password or None)
    client.connect(config.mqtt_host, config.mqtt_port, keepalive=20)
    client.loop_start()
    return client


def _publish_map(client, prefix: str, messages: dict[str, str], qos: int = 1) -> None:
    handles = [
        client.publish(f"{prefix}/{topic}", payload, qos=qos, retain=True)
        for topic, payload in messages.items()
    ]
    for handle in handles:
        handle.wait_for_publish(timeout=5)


def publish_result(config: "Config", result: "RenderResult") -> None:
    if not config.mqtt_host:
        return

    alert: RainAlert = result.alert
    prefix = config.mqtt_prefix.rstrip("/")
    state = {
        "health": HEALTH_OK,
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
        "published_utc": result.metadata.get("published_utc"),
        "output_svg": str(config.outdir / "output.svg"),
        "output_png": str(config.outdir / "output.png"),
        "output_gif": str(config.outdir / "radar.gif"),
        "flow_available": result.metadata.get("flow_available"),
        "will_rain": {str(k): v for k, v in result.will_rain.items()},
        **{f"will_rain_in_{lead}_minutes": flag for lead, flag in result.will_rain.items()},
    }
    messages = {
        "health": HEALTH_OK,
        "status": alert.status,
        "mean_rr": f"{alert.mean_rr_mmh:.4f}",
        "max_rr": f"{alert.max_rr_mmh:.4f}",
        "timestamp": str(state["timestamp_utc"] or ""),
        "state": json.dumps(state),
    }
    for lead, flag in result.will_rain.items():
        messages[f"will_rain_in_{lead}_minutes"] = flag

    client = _client(config)
    try:
        _publish_map(client, prefix, messages)
        LOGGER.info("Published MQTT state to %s/*", prefix)
    finally:
        client.loop_stop()
        client.disconnect()


def report_unavailable(config: "Config", error: str) -> None:
    """Mark HASS entities unavailable after a fetch/render failure."""
    LOGGER.warning("Marking output unavailable: %s", error[:200])
    config.outdir.mkdir(parents=True, exist_ok=True)
    (config.outdir / "status.txt").write_text(STATUS_UNAVAILABLE + "\n")
    for lead in config.nowcast_lead_min:
        (config.outdir / f"will_rain_in_{lead}_minutes.txt").write_text("unknown\n")
    payload = {
        "health": HEALTH_UNAVAILABLE,
        "status": STATUS_UNAVAILABLE,
        "error": error[:500],
        **{f"will_rain_in_{lead}_minutes": "unknown" for lead in config.nowcast_lead_min},
    }
    (config.outdir / "radar.json").write_text(json.dumps(payload, indent=2) + "\n")
    if not config.mqtt_host:
        return
    prefix = config.mqtt_prefix.rstrip("/")
    messages = {
        "health": HEALTH_UNAVAILABLE,
        "status": STATUS_UNAVAILABLE,
        "state": json.dumps(payload),
        **{f"will_rain_in_{lead}_minutes": "unknown" for lead in config.nowcast_lead_min},
    }
    try:
        client = _client(config)
        try:
            _publish_map(client, prefix, messages)
        finally:
            client.loop_stop()
            client.disconnect()
    except Exception:
        LOGGER.exception("Failed to publish MQTT unavailable state")
        return
