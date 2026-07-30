"""
Shared page registry — single source of truth for st.navigation.

Why this exists: st.page_link("somefile.py", ...) can fail with
KeyError 'url_pathname' under st.navigation, because the link must
reference the exact st.Page object that was registered. Defining the
pages here once lets app.py register them AND lets any page (e.g. the
landing page) link to them safely via PAGES["key"].

Two exports, and the distinction matters:

    PAGES   dict of key -> st.Page. The lookup table. Any page that wants
            to link to another page uses this (see hjem.py). Never iterate
            it for navigation — dict order is not the menu order.
    NAV     what app.py hands to st.navigation. A dict of SECTION -> pages,
            which Streamlit renders as a grouped sidebar with headings.

Why grouped rather than one flat list: 21 flat entries is more than anyone
can scan, and it gives a visitor no clue which pages are the demonstration
and which are deep tooling. The sections below carry that signal — notably
"Model Broker", which is symbol/configuration work that needs a Model
Broker export to run at all (see README §5.5), not stakeholder material.

Section order is the order a demo should walk them in: establish the
format argument first, then analysis, then what it enables.
"""
import streamlit as st

PAGES = {
    "hjem":        st.Page("hjem.py", title="Home", icon="🏠", default=True),
    "dexpi_vs_pdf": st.Page("dexpi_vs_pdf.py", title="DEXPI vs PDF", icon="🆚"),
    "tag":         st.Page("tag_oversikt.py", title="Tag register", icon="🏷️"),
    "topologi":    st.Page("dexpi_graph.py", title="DEXPI topology", icon="🔗"),
    "sys_pdf":     st.Page("system_analysis.py", title="System analysis (PDF)", icon="📄"),
    "sys_dexpi":   st.Page("system_analysis_dexpi.py", title="System analysis (DEXPI)", icon="🧭"),
    "hazop":       st.Page("hazop.py", title="HAZOP preparation", icon="⚠️"),
    "hazop_cmp":   st.Page("hazop_compare.py", title="HAZOP: PDF vs DEXPI", icon="⚖️"),
    "kontrollrom": st.Page("kontrollrom.py", title="Control-room assistant", icon="🎛️"),
    "anlegg":      st.Page("anleggsoversikt.py", title="Plant overview", icon="🏭"),
    "neqsim":      st.Page("neqsim_side.py", title="NeqSim simulation", icon="🧪"),
    "tegning":     st.Page("tegningsanalyse.py", title="Drawing analysis", icon="🔍"),
    "pid_struktur": st.Page("pid_struktur.py", title="PDF → structure", icon="🧩"),
    "graf_qa":     st.Page("graf_qa.py", title="Plant Q&A", icon="💬"),
    "sammendrag":  st.Page("tegning_sammendrag.py", title="30-sec summary", icon="📝"),
    "compliance":  st.Page("compliance_dashboard.py", title="Compliance dashboard", icon="📊"),
    "finn":        st.Page("finn_tegning.py", title="Find the drawing", icon="🔎"),
    "dexpi_egenskaper": st.Page("dexpi_egenskaper.py", title="DEXPI properties", icon="🧬"),
    "broker_konfig":    st.Page("broker_konfig.py",    title="Model Broker config", icon="⚙️"),
    "referansevelger": st.Page("referansevelger.py", title="Reference symbols", icon="🎯"),
    "variantkart": st.Page("variantkart.py", title="Symbol variants", icon="🧩"),
}

# Sidebar sections. Each list is rendered under its heading, in this order.
NAV = {
    # Where a visitor lands and where a demo starts: what this is, the
    # format argument in two minutes, and the plant as one model.
    "Start": [
        PAGES["hjem"],
        PAGES["dexpi_vs_pdf"],
        PAGES["anlegg"],
    ],
    # The same analyses from both sources, plus the structured data they
    # run on. Kept adjacent so "same tools, better data" is one click.
    "System analysis": [
        PAGES["sys_pdf"],
        PAGES["sys_dexpi"],
        PAGES["tag"],
        PAGES["topologi"],
    ],
    # Worksheets and screening — the project-phase deliverables.
    "Safety & quality": [
        PAGES["hazop"],
        PAGES["hazop_cmp"],
        PAGES["compliance"],
    ],
    # What the structured model enables once the plant is running.
    "Operations": [
        PAGES["kontrollrom"],
        PAGES["graf_qa"],
        PAGES["finn"],
        PAGES["sammendrag"],
        PAGES["neqsim"],
    ],
    # Sheet-level work: read a drawing, or rebuild structure from one.
    "Drawings": [
        PAGES["tegning"],
        PAGES["pid_struktur"],
    ],
    # Deep tooling. All four read the DEXPI export or a Model Broker
    # configuration; the last three need data/broker/*.json to run at all
    # and will say so plainly if it is absent.
    "Model Broker": [
        PAGES["dexpi_egenskaper"],
        PAGES["broker_konfig"],
        PAGES["referansevelger"],
        PAGES["variantkart"],
    ],
}

# Flat list of every registered page, in sidebar order. Not used for
# navigation — kept so tests and tooling can enumerate the pages without
# knowing the section layout.
ALL_PAGES = [p for section in NAV.values() for p in section]
