from __future__ import annotations

import json
from pathlib import Path

from fmi_radar.config import Config
from fmi_radar.mqtt import HEALTH_UNAVAILABLE, report_unavailable


def test_report_unavailable_writes_files_without_mqtt(tmp_path: Path):
    config = Config(outdir=tmp_path, mqtt_host=None, nowcast_lead_min=(5, 10, 15))
    report_unavailable(config, "boom" * 200)
    assert (tmp_path / "status.txt").read_text().strip() == "unavailable"
    for lead in (5, 10, 15):
        assert (tmp_path / f"will_rain_in_{lead}_minutes.txt").read_text().strip() == "null"
    payload = json.loads((tmp_path / "radar.json").read_text())
    assert payload["health"] == HEALTH_UNAVAILABLE
    assert payload["status"] == "unavailable"
    assert payload["error"].startswith("boom")
    assert len(payload["error"]) <= 500
