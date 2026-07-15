"""
src/neqsim_side.py  —  NeqSim simulation page

Registered by src/app.py via st.navigation:
    st.Page("neqsim_side.py", title="NeqSim-simulering", icon="🧪"),

Two tabs, both grounded in the DEXPI export (data/processed/dexpi_tags.csv
etc., built by analysis/parse_dexpi_data.py — run that first if the CSVs
are missing):

  1. Fluidoversikt   — all fluid codes present in a DEXPI-covered drawing,
                       with NeqSim-computed density/Z-factor/molar mass per
                       fluid type. Reuses analysis/neqsim_system_report.py.
  2. Feilsimulering  — pick a component to "fail", see what gets isolated,
                       and (if it isolates something) the NeqSim hydrate
                       consequence for that segment's fluid. Reuses
                       analysis/simulate_component_failure.py.

NeqSim connectivity is DEXPI-only (see RESULTS.md / project notes): PDF-only
drawings carry no machine-readable fluid identification, so this page only
lists drawings that have a DEXPI XML.

Same pattern as hazop.py / tag_oversikt.py: a clear import-error message
if the modules or Java/NeqSim aren't available, instead of a raw traceback.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st

try:
    from analysis.neqsim_system_report import (
        find_xml_for_drawing, summarize_fluid_codes, compute_neqsim_properties,
        RAW_DIR, PROCESSED_DIR,
    )
    from analysis.simulate_component_failure import (
        load_graph, simulate_failure, lookup_fluid_code,
    )
except Exception as e:  # noqa: BLE001
    st.title("🧪 NeqSim-simulering")
    st.error(
        "Kunne ikke importere NeqSim-analysemodulene "
        f"(analysis.neqsim_system_report / analysis.simulate_component_failure).\n\n"
        f"`{e}`\n\n"
        "Sjekk at disse filene ligger i `src/analysis/`, og at "
        "`neqsim_tools/` (med `fluid_lookup.py`) ligger i `src/`."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Datainnlasting
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Laster DEXPI-tag-register…")
def load_dexpi_tables():
    tags_path = PROCESSED_DIR / "dexpi_tags.csv"
    if not tags_path.exists():
        return None, None, None
    tags = pd.read_csv(tags_path)
    conns_path = PROCESSED_DIR / "dexpi_connections.csv"
    assocs_path = PROCESSED_DIR / "dexpi_associations.csv"
    conns = pd.read_csv(conns_path) if conns_path.exists() else pd.DataFrame()
    assocs = pd.read_csv(assocs_path) if assocs_path.exists() else pd.DataFrame()
    return tags, conns, assocs


@st.cache_data(show_spinner="Beregner fluidegenskaper (NeqSim)…")
def cached_properties(fluid_codes: tuple[str, ...], pressure: float, temperature: float):
    return compute_neqsim_properties(list(fluid_codes), pressure, temperature)


tags_all, conns_all, assocs_all = load_dexpi_tables()

st.title("🧪 NeqSim-simulering")
st.caption(
    "Kobler DEXPI-topologien til fysiske NeqSim-beregninger via "
    "`FluidCodeAssignmentClass`. Kun tegninger med en DEXPI-eksport støttes — "
    "vanlige PDF-tegninger har ingen maskinlesbar fluididentifikasjon."
)

if tags_all is None:
    st.error(
        "Fant ikke `data/processed/dexpi_tags.csv`. Kjør først:\n\n"
        "```\npython -m analysis.parse_dexpi_data\n```\n\nfra `src/`-mappen."
    )
    st.stop()

drawings = sorted(tags_all["drawing"].unique())
if not drawings:
    st.warning("Ingen DEXPI-tegninger funnet i tag-registeret.")
    st.stop()

st.sidebar.title("NeqSim-simulering")
drawing = st.sidebar.selectbox("Tegning (kun DEXPI-dekkede)", drawings)
pressure = st.sidebar.number_input("Representativt trykk [bara]", value=60.0, step=5.0,
                                   help="DEXPI-eksporten inneholder ikke ekte driftstrykk — "
                                        "dette er en antatt verdi du kan justere.")
temperature = st.sidebar.number_input("Representativ temperatur [°C]", value=20.0, step=5.0)

tab1, tab2 = st.tabs(["🧯 Fluidoversikt", "🎯 Feilsimulering + hydratkonsekvens"])


# ---------------------------------------------------------------------------
# Fane 1: fluidoversikt for hele tegningen
# ---------------------------------------------------------------------------

with tab1:
    xml_path = find_xml_for_drawing(drawing)
    if xml_path is None:
        st.error(f"Fant ingen DEXPI-XML-fil for '{drawing}' under {RAW_DIR}.")
        st.stop()

    summary = summarize_fluid_codes(xml_path)
    if summary.empty:
        st.info("Ingen fluidkoder funnet i denne tegningen.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Unike fluidkoder", len(summary))
        c2.metric("Rørsegmenter med fluidkode", int(summary["n_segments"].sum()))

        st.subheader("Fluidkoder i tegningen")
        st.dataframe(summary, use_container_width=True, hide_index=True)
        st.bar_chart(summary.set_index("fluid_code")["n_segments"])

        st.subheader(f"NeqSim-egenskaper ved {pressure:.0f} bara / {temperature:.0f} °C")
        with st.spinner("Kjører NeqSim (JVM kan bruke noen sekunder ved førstegangskall)…"):
            try:
                props = cached_properties(tuple(summary["fluid_code"]), pressure, temperature)
            except Exception as e:  # noqa: BLE001
                props = pd.DataFrame()
                st.error(f"NeqSim/JVM-feil: {e}")

        if not props.empty:
            st.dataframe(props, use_container_width=True, hide_index=True)
            if props["density_kg_m3"].notna().any():
                st.bar_chart(props.set_index("fluid_code")["density_kg_m3"])
            if (~props["matched"]).any():
                ukjente = ", ".join(props[~props["matched"]]["fluid_code"])
                st.warning(f"Fluidkode(r) uten eksplisitt preset (bruker standardgass): {ukjente}")
        st.caption(
            "⚠️ Fluidkode → sammensetning er **antatt** (norsk sokkel-konvensjon), "
            "ikke bekreftet mot en Huldra-spesifikk linjeliste — se "
            "`neqsim_tools/fluid_lookup.py`. Trykk/temperatur er representative "
            "verdier, ikke ekte driftsdata (finnes ikke i DEXPI-eksporten)."
        )


# ---------------------------------------------------------------------------
# Fane 2: feilsimulering + hydratkonsekvens for det paavirkede segmentet
# ---------------------------------------------------------------------------

with tab2:
    G, sub = load_graph(tags_all, conns_all, assocs_all, drawing)
    tag_options = sorted(sub["tag_name"].dropna().unique())
    if not tag_options:
        st.info("Ingen navngitte komponenter på denne tegningen.")
        st.stop()

    fail_tag = st.selectbox("Komponent som skal 'feile'", ["(ingen valgt)"] + tag_options)

    if fail_tag == "(ingen valgt)":
        st.caption("Velg en komponent over for å simulere en feil og se hydratkonsekvensen.")
        st.stop()

    try:
        result = simulate_failure(G, sub, fail_tag)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    egen_grad = G.degree(result["fail_id"])
    n_affected = len(result["affected_ids"])

    if egen_grad <= 1:
        st.error(
            f"📉 **Datakvalitet:** `{fail_tag}` har kun {egen_grad} registrert(e) "
            "kobling(er) i DEXPI-dataen. Et lavt/null-resultat betyr ofte at "
            "koblingen mangler i dataen, ikke at komponenten faktisk henger fritt."
        )
    else:
        st.caption(f"`{fail_tag}` har {egen_grad} registrerte koblinger i datasettet.")

    if n_affected == 0:
        st.info("Ingen andre objekter isoleres av denne feilen ifølge de eksplisitte "
                "DEXPI-koblingene — ingen segment å beregne hydratkonsekvens for.")
        st.stop()

    st.warning(
        f"⚠️ **{n_affected} objekter** isoleres: " +
        ", ".join(f"`{t}`" for t in result["affected_tags"]["tag_name"])
    )

    st.subheader("NeqSim: hydratrisiko ved nedblåsing av det isolerte segmentet")
    xml_path = find_xml_for_drawing(drawing)
    with st.spinner("Slår opp fluidkode og kjører NeqSim…"):
        try:
            fluid_code = lookup_fluid_code(xml_path, sub, result["fail_id"]) if xml_path else None
        except Exception as e:  # noqa: BLE001
            fluid_code = None
            st.caption(f"(Klarte ikke slå opp fluidkode automatisk: {e})")

        try:
            from neqsim_tools.fluid_lookup import get_preset, build_neqsim_fluid
            from neqsim.thermo import hydt

            preset = get_preset(fluid_code)
            rows = []
            for p in (90.0, 30.0, 10.0):
                f = build_neqsim_fluid(preset)
                f.setPressure(p, "bara")
                f.setTemperature(10.0, "C")
                try:
                    hydt(f)
                    rows.append({"Trykk [bara]": p,
                                "Hydrattemperatur [°C]": round(f.getTemperature("C"), 1)})
                except Exception:
                    rows.append({"Trykk [bara]": p, "Hydrattemperatur [°C]": None})

            match_note = (f"fluidkode '{preset['code']}' funnet i DEXPI-data"
                          if preset["matched"] else "ingen fluidkode funnet — bruker standardgass")
            st.caption(f"Fluid: **{preset['description']}**  ({match_note})")
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(
                "Hvis segmentets faktiske temperatur er under verdiene over ved "
                "det gjeldende trykket, er det risiko for hydratdannelse ved "
                "isolering/nedblåsing. Sammensetning er antatt — se forbehold i fane 1."
            )
        except ImportError:
            st.error("NeqSim er ikke installert/tilgjengelig her. Kjør: `pip install neqsim`")
        except Exception as e:  # noqa: BLE001
            st.error(f"NeqSim/JVM-feil: {e}")