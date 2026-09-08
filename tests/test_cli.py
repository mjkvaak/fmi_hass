from __future__ import annotations

from datetime import datetime, timezone

from fmi_radar.cli import _formats, build_parser, main
from fmi_radar.config import Config, LIGHT, THEMES


def test_formats_both():
    assert _formats("both") == ("png", "svg")
    assert _formats("png") == ("png",)


def test_parser_disables_arrows_with_zero_density():
    args = build_parser().parse_args(["--flow-arrow-density", "0", "--no-gif"])
    assert args.flow_arrow_density == 0.0
    assert args.gif is False


def test_parser_time_compact_utc():
    args = build_parser().parse_args(["--time", "202609040300"])
    from fmi_radar.s3 import parse_timestamp

    parsed = parse_timestamp(args.time)
    assert parsed == datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)


def test_main_reports_unavailable_on_timeout(tmp_path, monkeypatch):
    from fmi_radar.timeout import RenderTimeout

    monkeypatch.setattr(
        "fmi_radar.cli.call_with_timeout",
        lambda *_a, **_k: (_ for _ in ()).throw(RenderTimeout("Timed out after 1s")),
    )
    code = main(["--outdir", str(tmp_path), "--timeout", "1"])
    assert code == 1
    assert (tmp_path / "status.txt").read_text().strip() == "unavailable"


def test_cmap_for_prefers_theme_override():
    config = Config(cmap="turbo", cmap_light="plasma")
    assert config.cmap_for(LIGHT) == "plasma"
    assert config.cmap_for(THEMES["dark"]) == "turbo"


def test_flow_box_km_adds_padding_both_sides():
    assert Config(box_km=10.0, of_padding_km=20.0).flow_box_km == 50.0
    assert Config(box_km=10.0, of_padding_km=-1.0).flow_box_km == 10.0
