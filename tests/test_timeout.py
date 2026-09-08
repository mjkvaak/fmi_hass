from __future__ import annotations

from fmi_radar.timeout import RenderTimeout, call_with_timeout


def test_call_with_timeout_disabled_when_non_positive():
    assert call_with_timeout(0, lambda: 42) == 42
    assert call_with_timeout(-1, lambda x: x + 1, 2) == 3


def test_render_timeout_is_timeout_error():
    assert issubclass(RenderTimeout, TimeoutError)
