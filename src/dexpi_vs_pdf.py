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

st.title("🆚 DEXPI vs PDF — samme tegning, to kilder")
st.caption("Interaktiv demo bygget på ekte data fra tegning "
           "C025-V-HO27-P-_E-001-01: venstre side viser hva tekstuttrekket "
           "fra PDF-en gir (tags, men null koblinger — de som mangler er "
           "symbol-only), høyre side viser samme tegning rekonstruert fra "
           "DEXPI-XML-en. Hold musen over en komponent i DEXPI-grafen for å "
           "spore sløyfen — operasjonen som er umulig fra PDF.")

if not HTML_PATH.exists():
    st.error(f"Fant ikke demoen: {HTML_PATH}. Den skal ligge i demos/-mappen "
             f"i prosjektroten.")
    st.stop()

html = HTML_PATH.read_text(encoding="utf-8")

height = st.sidebar.slider("Visningshøyde (px)", 800, 2400, 1450, step=50,
                           help="Demoen er én lang side; juster om noe "
                                "kuttes eller det blir mye luft.")
components.html(html, height=height, scrolling=True)

st.caption("Demoen ligger som frittstående fil i `demos/DEXPI_VS_PDF.html` "
           "og kan åpnes rett i nettleser uten appen — praktisk som vedlegg "
           "eller reserve under presentasjonen.")