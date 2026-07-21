"""
src/anleggsoversikt.py  —  the plant at a glance

Registered via nav_pages.py. The plant model (analysis/plant_model.py) is
the project's most important asset but was invisible — it only powered the
control room. This page makes it visible at DRAWING level, where it is
readable in seconds: 17 nodes, one per sheet, connected where line numbers
prove the sheets share physical piping. The establishing shot before any
plant-wide demo: "first we show that the plant is now ONE model — then we
show what that enables."
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config import PID_DIR
from analysis.plant_model import (build_plant_model, metro_svg, metro_html,
                                  plant_criticality)

RAW_DIR = Path(PID_DIR).parent


@st.cache_resource(show_spinner="Syr sammen anleggsmodellen…")
def load() -> dict:
    return build_plant_model(RAW_DIR)


M = load()
S = M["stats"]

st.title("🏭 Anleggsoversikt")
st.caption("Alle DEXPI-tegningene sydd sammen til én modell. Sømmene er "
           "delte linjenummer: samme rørlinje-tag på to ark ER samme fysiske "
           "linje. Dette kartet er umulig å lage fra PDF-ene — og trivielt "
           "fra strukturerte leveranser.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tegninger", S["drawings"])
c2.metric("Tags totalt", S["tags"])
c3.metric("Linje-sømmer", S["line_stitches"],
          help="Linjenummer som opptrer på to tegninger og dermed beviser "
               "fysisk kobling mellom arkene.")
c4.metric("Koblinger i modellen", S["edges"])

st.subheader("Metrokartet — hvordan arkene henger sammen")
st.caption("Én node per tegning (farge = system), strek = delt linjenummer "
           "(tykkere = flere delte linjer). Interaktivt: scroll for å zoome, "
           "dra bakgrunnen for å panorere, dra en node for å flytte den, "
           "hold musen over en node for å framheve naboene, og klikk et "
           "system i tegnforklaringen for å isolere det.")
components.html(metro_html(M), height=640)

left, right = st.columns(2)

with left:
    st.subheader("Sømmene")
    st.caption("Hver rad er en fysisk linje som krysser en tegningsgrense — "
               "med komponentene som forankrer den på hver side.")
    rows = [{"linje": ln, "tegning A": a[-14:], "tegning B": b[-14:],
             "forankring A": ", ".join(ta), "forankring B": ", ".join(tb)}
            for ln, a, b, ta, tb in M["stitches"]]
    st.dataframe(pd.DataFrame(rows), use_container_width=True,
                 hide_index=True, height=380)

with right:
    st.subheader("Strukturelt mest eksponerte komponenter")
    st.caption("Flest koblinger i hele anlegget — hvor en svikt kan nå "
               "lengst. Eksponering, ikke konsekvens: redundans, bypass og "
               "driftsmodus er ikke i modellen, så listen sier hvor "
               "ingeniøren bør se først, ikke hva som faktisk stopper.")
    st.dataframe(pd.DataFrame(plant_criticality(M, 10)),
                 use_container_width=True, hide_index=True, height=380)

st.divider()
st.caption("Retning over en søm er ikke oppgitt i eksporten (off-page-"
           "connectorene er navnløse), så kryss-kanter legges begge veier — "
           "en dokumentert begrensning, og et direkte innspill til "
           "minimumskravene: navngitte, rettede off-page-referanser og "
           "konsistente linjenummer er det som gjør en anleggsmodell billig. "
           "Prøv modellen i praksis: Kontrollrom-assistenten → "
           "«🏭 Hele anlegget».")