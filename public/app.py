"""Streamlit Community Cloud entrypoint with its own lightweight requirements."""

import sys
import runpy
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
st.session_state["_mockmate_public_mode"] = True

runpy.run_path(str(ROOT / "live_app.py"), run_name="__main__")
