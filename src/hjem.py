"""
src/hjem.py  —  landing page

First thing a stakeholder sees: what this is, the honest key numbers, and
three guided paths into the app. Everything else in the app assumes
context; this page provides it.
"""
from __future__ import annotations
import streamlit as st

from nav_pages import PAGES


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

st.caption("Kun offentlig publiserte Huldra-data og syntetiske "
           "alarmer/sensorverdier. Prototype — se README og rapport for "
           "begrensninger, metode og pilotforslag.")