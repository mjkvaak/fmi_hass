from __future__ import annotations

import json
from pathlib import Path


def test_ha_manifest_omits_gdal_opencv():
    """Home Assistant Container is Alpine; rasterio/OpenCV have no musllinux wheels."""
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "custom_components/fmi_radar/manifest.json").read_text()
    )
    joined = " ".join(manifest["requirements"]).lower()
    assert "rasterio" not in joined
    assert "opencv" not in joined
    assert "contextily" not in joined
    assert any(item.startswith("matplotlib") for item in manifest["requirements"])
    assert any(item.startswith("pyproj") for item in manifest["requirements"])
