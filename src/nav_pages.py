"""
Shared page registry — single source of truth for st.navigation.

Why this exists: st.page_link("somefile.py", ...) can fail with
KeyError 'url_pathname' under st.navigation, because the link must
reference the exact st.Page object that was registered. Defining the
pages here once lets app.py register them AND lets any page (e.g. the
landing page) link to them safely via PAGES["key"].
"""
import streamlit as st

PAGES = {
    "hjem":        st.Page("hjem.py", title="Hjem", icon="🏠", default=True),
    "dexpi_vs_pdf": st.Page("dexpi_vs_pdf.py", title="DEXPI vs PDF (demo)", icon="🆚"),
    "tag":         st.Page("tag_oversikt.py", title="Tag-oversikt", icon="🏷️"),
    "topologi":    st.Page("dexpi_graph.py", title="DEXPI-topologi", icon="🔗"),
    "sys_pdf":     st.Page("system_analysis.py", title="System-analyse (PDF)", icon="📄"),
    "sys_dexpi":   st.Page("system_analysis_dexpi.py", title="System-analyse (DEXPI)", icon="🧭"),
    "hazop":       st.Page("hazop.py", title="HAZOP-forberedelse", icon="⚠️"),
    "hazop_cmp":   st.Page("hazop_compare.py", title="HAZOP: PDF vs DEXPI", icon="⚖️"),
    "kontrollrom": st.Page("kontrollrom.py", title="Kontrollrom-assistent", icon="🎛️"),
    "anlegg":      st.Page("anleggsoversikt.py", title="Anleggsoversikt", icon="🏭"),
    "neqsim":      st.Page("neqsim_side.py", title="NeqSim-simulering", icon="🧪"),
    "tegning":     st.Page("tegningsanalyse.py", title="Tegningsanalyse", icon="🔍"),
}

NAV = [
    PAGES["hjem"],
    PAGES["sys_pdf"],
    PAGES["sys_dexpi"],
    PAGES["tag"],
    PAGES["topologi"],
    PAGES["dexpi_vs_pdf"],
    PAGES["hazop"],
    PAGES["hazop_cmp"],
    PAGES["anlegg"],
    PAGES["kontrollrom"],
    PAGES["neqsim"],
    PAGES["tegning"],
]