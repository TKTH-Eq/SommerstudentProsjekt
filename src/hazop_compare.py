"""
src/hazop_compare.py  —  PDF vs DEXPI, same HAZOP module, side by side

Registered by src/app.py via st.navigation:
    st.Page("hazop_compare.py", title="HAZOP: PDF vs DEXPI", icon="⚖️"),

The single most persuasive format argument in the project, made concrete:
the SAME worksheet machinery (analysis/hazop_prep.build_worksheet) is run
twice on the SAME drawing —

  LEFT   input = PDF text-layer extraction
         nodes = functional loops (shared tag number — connectivity guessed)
  RIGHT  input = Semantum DEXPI XML
         nodes = equipment-anchored process sections (connectivity stated)

Only the drawings that exist in BOTH forms are offered, so every difference
on screen is attributable to the input format, not the drawing.
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st

from config import PID_DIR
from extraction.tag_extractor import extract_tags, create_objects
from analysis.build_dependency_graph import build_graph
from analysis.hazop_prep import build_worksheet, write_worksheet_csv
from analysis.hazop_dexpi import load_dexpi_model

RAW_DIR = Path(PID_DIR).parent


# ---- pairing: drawings that exist as both PDF and DEXPI XML ----------------
def find_pairs() -> dict[str, tuple[Path, Path]]:
    """{drawing stem: (pdf_path, xml_path)} for drawings with both forms."""
    xmls = {x.stem.replace(".DGN", ""): x for x in RAW_DIR.rglob("*.DGN.xml")}
    pairs = {}
    for pdf in sorted(list(PID_DIR.glob("*.PDF")) + list(PID_DIR.glob("*.pdf"))):
        if pdf.stem in xmls:
            pairs[pdf.stem] = (pdf, xmls[pdf.stem])
    return pairs


@st.cache_resource(show_spinner="Kjører begge pipelinene…")
def run_both(stem: str, pdf: str, xml: str) -> dict:
    # PDF side: text-layer extraction, loop-based nodes
    objs = sorted(set(create_objects(extract_tags(pdf), "P&ID")),
                  key=lambda o: o.tag)
    g_pdf = build_graph(objs)
    rows_pdf = build_worksheet(g_pdf, objs)
    # DEXPI side: stated connectivity, equipment-anchored sections. If a
    # drawing yields no sections (no tagged equipment, signal-only sheet),
    # fall back to loop-based nodes on the DEXPI objects — still better
    # consequences than the PDF side, since the tag graph is real.
    m = load_dexpi_model(Path(xml))
    fallback = not m["sections"]
    rows_dx = build_worksheet(m["tag_graph"], m["objects"],
                              nodes=m["sections"] or None)
    return {"pdf_objs": objs, "pdf_rows": rows_pdf, "pdf_edges": g_pdf.number_of_edges(),
            "dx": m, "dx_rows": rows_dx, "dx_fallback": fallback}


def _stats(rows, n_tags, n_edges) -> dict:
    with_sg = sum(1 for r in rows if not r["safeguards"].startswith("(none"))
    share = f"{with_sg}/{len(rows)} ({with_sg / len(rows):.0%})" if rows else "–"
    return {"tags": n_tags, "noder": len({r["node"] for r in rows}),
            "avviksrader": len(rows),
            "andel rader med funnet barriere": share,
            "koblinger i graf": n_edges}


def _show(rows, key: str, stem: str):
    if not rows:
        st.warning("Ingen noder med prosessparametre.")
        return
    df = pd.DataFrame(rows)[["node", "deviation", "causes",
                             "consequences", "safeguards"]]
    node = st.selectbox("Node", ["(alle)"] + sorted(df.node.unique()), key=key)
    if node != "(alle)":
        df = df[df.node == node]
    st.dataframe(df, use_container_width=True, hide_index=True, height=420)
    out = Path(f"reports/hazop_{key}_{re.sub(r'[^A-Za-z0-9]+', '_', stem)}.csv")
    out.parent.mkdir(exist_ok=True)
    write_worksheet_csv(rows, out)
    st.download_button("Last ned (CSV)", out.read_bytes(),
                       file_name=out.name, mime="text/csv", key=f"dl_{key}")


# ---- page -------------------------------------------------------------------
st.title("⚖️ HAZOP-forberedelse: PDF vs DEXPI")
st.caption("Samme arbeidsark-maskineri, samme tegning, to inputformater. "
           "Alle forskjeller under skyldes formatet: PDF-siden må gjette "
           "grupperinger fra tag-nummer, DEXPI-siden leser koblingene "
           "eksplisitt og kan forankre noder i utstyr. Forberedelsesmateriale "
           "for HAZOP-team — ikke en fullført studie.")

pairs = find_pairs()
if not pairs:
    st.error("Fant ingen tegning som finnes både som PDF (data/raw/P&ID) og "
             "DEXPI-XML (Semantum-mappen).")
    st.stop()

stem = st.sidebar.selectbox("Tegning", sorted(pairs))
pdf_path, xml_path = pairs[stem]
R = run_both(stem, str(pdf_path), str(xml_path))

s_pdf = _stats(R["pdf_rows"], len(R["pdf_objs"]), R["pdf_edges"])
s_dx = _stats(R["dx_rows"], R["dx"]["stats"]["tagged_elements"],
              R["dx"]["stats"]["tag_edges"])

st.subheader("Nøkkeltall")
mdf = pd.DataFrame({"PDF (tekstlag, løkke-noder)": s_pdf,
                    "DEXPI (koblinger, utstyrsseksjoner)": s_dx})
st.dataframe(mdf, use_container_width=True)
st.caption("«Andel rader med funnet barriere»: avviksrader der minst én ekte, "
           "uttrekt safeguard-tag ble identifisert — som andel, siden "
           "PDF-siden lager mange flere, mindre noder og ellers ville vunnet "
           "på volum. Merk også nodenavnene: PDF-siden KAN bare navngi noder "
           "etter løkkenummer; DEXPI-siden kan forankre dem i utstyr.")

left, right = st.columns(2)
with left:
    st.subheader("PDF — funksjonelle løkker")
    st.caption("Noder = tags som deler løkkenummer. Konnektivitet gjettes; "
               "konsekvenser kan ikke krysse løkkegrenser.")
    _show(R["pdf_rows"], "pdf", stem)
with right:
    st.subheader("DEXPI — utstyrsforankrede seksjoner")
    st.caption("Noder = alt prosess-koblet rundt hvert utstyr (nozzle-, "
               "segment- og containment-relasjoner fra XML). Konsekvenser "
               "følger reelle rettede koblinger.")
    if R.get("dx_fallback"):
        st.info("Denne tegningen ga ingen utstyrsseksjoner (ingen taggede "
                "utstyrsenheter i prosessnettet) — viser løkke-noder på "
                "DEXPI-data i stedet. Konsekvensene bruker fortsatt ekte "
                "koblinger.")
    _show(R["dx_rows"], "dexpi", stem)

st.divider()
st.caption("Ærlige grenser: DEXPI-seksjonene er grafbaserte tilnærminger til "
           "en HAZOP-leders nodekutt — på tegninger med få taggede "
           "utstyrsenheter blir seksjonene grove, og elementer mellom to "
           "utstyr kan tilhøre begge seksjoner. PDF-siden arver "
           "tekstlagets recall-tak (se Results.md).")