"""
src/dexpi_vs_pdf.py  —  interactive DEXPI-vs-PDF demo embedded in the app

Registered by src/app.py via st.navigation:
    st.Page("dexpi_vs_pdf.py", title="DEXPI vs PDF (demo)", icon="🆚"),

Thin wrapper: the actual demo is the self-contained HTML/JS file in
demos/DEXPI_VS_PDF.html (real topology from C025-V-HO27-P-_E-001-01.DGN.xml,
real per-component PDF extraction status). Keeping it as a standalone HTML
file means it also works without Streamlit — e.g. attached to an e-mail or
opened directly in a browser during the stakeholder presentation.

Note: the page uses Google Fonts from a CDN, so it looks best online; it
degrades gracefully to system fonts offline.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import streamlit.components.v1 as components

HTML_PATH = Path(__file__).resolve().parent.parent / "demos" / "DEXPI_VS_PDF.html"

from ui import page_header
page_header("DEXPI vs PDF — same drawing, two sources",
            "C025-V-HO27-P-_E-001-01 · tags from both, topology only from DEXPI")
st.caption("Interactive demo built on real data from drawing "
           "C025-V-HO27-P-_E-001-01: the left side shows what the text extraction "
           "from the PDF provides (tags, but zero connections — the missing ones are "
           "symbol-only), the right side shows the same drawing reconstructed from "
           "the DEXPI XML. Hover over a component in the DEXPI graph to "
           "trace the loop — the operation that is impossible from the PDF.")

if not HTML_PATH.exists():
    st.error(f"Could not find the demo: {HTML_PATH}. It should be located in the demos/ folder "
             f"in the project root.")
    st.stop()

html = HTML_PATH.read_text(encoding="utf-8")

height = st.sidebar.slider("View height (px)", 800, 2400, 1450, step=50,
                           help="The demo is one long page; adjust if something "
                                "is cut off or there is too much whitespace.")
components.html(html, height=height, scrolling=True)

st.caption("The demo is located as a standalone file in `demos/DEXPI_VS_PDF.html` "
           "and can be opened directly in a browser without the app — practical as an attachment "
           "or backup during the presentation.")