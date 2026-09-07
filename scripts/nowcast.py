#!/usr/bin/env python3
"""Standalone optical-flow nowcast (no map render).

  source .venv/bin/activate
  python scripts/nowcast.py --lat 60.1719 --lon 24.9414
  python scripts/nowcast.py --time 202609040300 --lat YOUR_LAT --lon YOUR_LON
"""

from fmi_radar.nowcast import main

if __name__ == "__main__":
    raise SystemExit(main())
