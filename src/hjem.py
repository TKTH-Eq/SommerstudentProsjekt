"""
src/hjem.py  —  landing page

First thing a stakeholder sees: what this is, the honest key numbers, and
three guided paths into the app. Everything else in the app assumes
context; this page provides it.
"""
from __future__ import annotations
import json
from pathlib import Path

import streamlit as st

from nav_pages import PAGES

_EVAL_JSON = Path(__file__).resolve().parents[1] / "reports" / "eval_root_cause.json"


def _load_eval() -> dict | None:
    """Result written by eval/eval_root_cause.py, if it has been run against
    the real plant model. Synthetic-fallback results are not shown here —
    the number on this page must mean 'measured on the real topology'."""
    try:
        d = json.loads(_EVAL_JSON.read_text(encoding="utf-8"))
        return d if "real" in d.get("source", "") else None
    except Exception:  # noqa: BLE001  (missing/invalid file -> just hide it)
        return None


def _go(page, label: str, key: str):
    """Robust navigasjon: knapp + st.switch_page. Brukes i stedet for
    st.page_link, som er upålitelig sammen med st.navigation i enkelte
    Streamlit-versjoner."""
    if st.button(label, key=key, use_container_width=True):
        st.switch_page(page)

st.title("AI-muligheter for P&ID og SCD")
st.caption("Sommerstudentprosjekt · Huldra-data (offentlige) · prototype "
           "bygget som beslutningsunderlag for Wisting-digitaliseringen")

st.markdown(
    "P&ID-er og SCD-er konsumeres i dag som tegninger og dokumenter. Denne "
    "appen demonstrerer hva som blir mulig når de i stedet behandles som "
    "**strukturert ingeniørdata**: automatisk uttrekk, konsistenssjekk, "
    "HAZOP-forberedelse, og beslutningsstøtte i kontrollrom — på ekte "
    "tegninger, med målt nøyaktighet.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Presisjon (PDF-uttrekk)", "87 %", help="Målt mot uavhengig "
          "DEXPI-fasit over 16 tegninger. Se Results.md for metode.")
c2.metric("Recall (PDF-uttrekk)", "55 %", help="Resten er i hovedsak tags "
          "tegnet som symboler — informasjon tekstuttrekk aldri kan nå. "
          "Det er selve argumentet for maskinlesbare leveranser.")
c3.metric("Tegninger i anleggsmodellen", "17", help="Alle DEXPI-filene sydd "
          "sammen til én graf via delte linjenummer.")
c4.metric("Tags i anleggsmodellen", "885")

_ev = _load_eval()
if _ev and _ev.get("conditions"):
    def _cond(name):
        return next((c for c in _ev["conditions"] if c["name"] == name), None)
    ideal = _cond("ideal")
    drop20 = _cond("20 % tapte alarmer")
    hard = _cond("dobbel feil + 20 % tap") or _cond("dobbel feil")
    e1, e2, e3, e4 = st.columns(4)
    if drop20:
        e1.metric("Rotårsak på plass 1", f"{drop20['hit1_pct']:.0f} %",
                  help=f"Målt med 20 % tapte alarmer over "
                       f"{drop20['scenarios']} syntetiske feilscenarioer i "
                       f"den ekte Huldra-topologien (kjørt {_ev['date']}, "
                       f"reproduserbart med eval/eval_root_cause.py). "
                       f"Under ideelle forhold (én feil, alle alarmer "
                       f"ringer) er treffraten "
                       f"{ideal['hit1_pct']:.0f} % — forventet av "
                       f"konstruksjon; tallet her er den reelle testen.")
        e2.metric("Rotårsak i topp 3", f"{drop20['hit3_pct']:.0f} %",
                  help="Samme betingelse (20 % tapte alarmer): andel "
                       "scenarioer der roten er blant de tre øverste "
                       "kandidatene.")
    if hard:
        e3.metric("Hardeste betingelse", f"{hard['hit1_pct']:.0f} %",
                  help=f"«{hard['name']}»: {hard['desc']}. "
                       f"hit3: {hard['hit3_pct']:.0f} %.")
    e4.metric("Scenarioer målt",
              f"{sum(c['scenarios'] for c in _ev['conditions'])}",
              help="Totalt over alle betingelser: ideal, 20/40 % tapte "
                   "alarmer, dobbel feil, dobbel feil + tap.")

st.info("**Lesenøkkel:** All AI-output i appen er førsteutkast med målt "
        "feilrate — aldri en fasit. Hver AI-generert påstand verifiseres "
        "mot det strukturerte tag-registeret, og alt deterministisk "
        "(uttrekk, grafer, arbeidsark) fungerer uten AI-nøkkel.")

st.subheader("Tre stier inn")
a, b, c = st.columns(3)
with a:
    st.markdown("**🆚 Formatargumentet på to minutter**  \n"
                "Samme tegning fra PDF og fra DEXPI, side om side: tags er "
                "tekst — topologi er det ikke.")
    _go(PAGES["dexpi_vs_pdf"], "🆚 Åpne DEXPI vs PDF", "go_dexpi")
with b:
    st.markdown("**⚠️ AI-assistert HAZOP**  \n"
                "Ferdig utfylt arbeidsark forankret i uttrekte tags, "
                "vision-lesing av selve tegningen, redigering og "
                "Excel-eksport.")
    _go(PAGES["hazop"], "⚠️ Åpne HAZOP-forberedelse", "go_hazop")
with c:
    st.markdown("**🎛️ Alarmdusj i kontrollrommet**  \n"
                "En skjult feil gir 100+ samtidige alarmer på tvers av "
                "tegninger — finn kilden med assistentens hjelp.")
    _go(PAGES["kontrollrom"], "🎛️ Åpne kontrollrom-scenariet", "go_kr")

st.markdown("Gjennomgående mønster: *samme verktøy, bedre data, bedre svar* "
            "— og *AI foreslår, strukturert register verifiserer*.")

with st.expander("🩺 Demo-beredskap (sjekk før presentasjon)"):
    import os
    from pathlib import Path as _P
    from config import PID_DIR

    def _row(ok, label, hint):
        st.write(("✅ " if ok else "⚠️ ") + label + ("" if ok else f" — {hint}"))

    _raw = _P(PID_DIR).parent
    _dexpi = list(_raw.rglob("*.DGN.xml"))
    _row(len(_dexpi) >= 1, f"DEXPI-filer funnet: {len(_dexpi)}",
         "legg XML-ene under data/raw/")
    _pdfs = list(_P(PID_DIR).glob("*.PDF")) + list(_P(PID_DIR).glob("*.pdf"))
    _row(len(_pdfs) >= 1, f"P&ID-PDF-er funnet: {len(_pdfs)}",
         "legg PDF-ene i data/raw/P&ID/")
    _row(bool(os.getenv("GEMINI_API_KEY")), "GEMINI_API_KEY satt",
         "AI-flatene vises ikke uten; alt deterministisk virker likevel")
    try:
        import pypdfium2  # noqa: F401
        _row(True, "pypdfium2 (rasterisering) installert", "")
    except Exception:  # noqa: BLE001
        _row(False, "pypdfium2 mangler", "vision/markører trenger den: uv sync")
    _vc = list(_P("reports/vision_cache").glob("*.json"))
    _row(len(_vc) >= 1, f"Vision-cache: {len(_vc)} tegning(er) varme",
         "kjør python src/ai/warm_vision_cache.py <pdf> kvelden før")
    _ac = list(_P("reports/ai_cache").glob("*.json"))
    _row(len(_ac) >= 1, f"AI-cache (omskrivinger/Q&A): {len(_ac)} innslag",
         "generer i appen med demo-modus på, så er demoen offline-trygg")
    _pc = _P("data/processed/dexpi_tags.csv")
    _row(_pc.exists(), "data/processed generert (NeqSim-koblingen)",
         "kjør analysis/parse_dexpi_data.py")

st.caption("Kun offentlig publiserte Huldra-data og syntetiske "
           "alarmer/sensorverdier. Prototype — se README og rapport for "
           "begrensninger, metode og pilotforslag.")