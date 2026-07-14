"""
src/app.py  —  entrypoint (navigation only)
=====================================================================
Registers the app's pages with st.navigation so they show up in the
sidebar with clean names/icons and no "app" label. Run as before:

    streamlit run src/app.py

Requires Streamlit >= 1.36 (st.navigation / st.Page).

Page files live next to this one in src/ (NOT in a pages/ folder — with
st.navigation, a pages/ folder would create a second, duplicate nav).
Delete the old src/pages/ folder after switching.
"""
import streamlit as st

# set_page_config must live ONLY in the entrypoint when using st.navigation.
st.set_page_config(page_title="Huldra P&ID/SCD analysis", layout="wide")

pages = [
    st.Page("system_analysis.py", title="System-analyse (PDF)", icon="🏠", default=True),
    st.Page("system_analysis_dexpi.py", title="System-analyse (DEXPI)", icon="🧭"),
    st.Page("tag_oversikt.py", title="Tag-oversikt", icon="🏷️"),
    st.Page("dexpi_graph.py", title="DEXPI-topologi", icon="🔗"),
    st.Page("dexpi_vs_pdf.py", title="DEXPI vs PDF", icon="🆚"),
    st.Page("hazop.py", title="HAZOP-forberedelse", icon="⚠️"),
    st.Page("hazop_compare.py", title="HAZOP: PDF vs DEXPI", icon="⚖️"),
]
st.navigation(pages).run()