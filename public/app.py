"""Streamlit Community Cloud entrypoint with its own lightweight requirements."""

import sys
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

runpy.run_path(str(ROOT / "live_app.py"), run_name="__main__")
