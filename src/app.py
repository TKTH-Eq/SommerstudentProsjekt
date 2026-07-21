"""
src/app.py  —  entrypoint (navigation + global theme)
=====================================================================
Run from the REPO ROOT:

    streamlit run src/app.py

Requires Streamlit >= 1.36 (st.navigation / st.Page).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

# set_page_config must live ONLY in the entrypoint when using st.navigation.
st.set_page_config(page_title="Huldra Insight", layout="wide")

# ---- global design system (EDS-style light theme) --------------------------
# Loud on failure: if ui.py is missing or broken we show a red banner instead
# of silently rendering the default look.
try:
    from ui import inject_css
    inject_css()
except Exception as _e:  # noqa: BLE001
    st.error(f"⚠️ Designsystemet ble ikke lastet (src/ui.py): {_e} — "
             f"appen kjører med standardutseende.")

from nav_pages import NAV

st.navigation(NAV).run()