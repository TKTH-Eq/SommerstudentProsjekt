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
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy.spatial import cKDTree

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
# Komponenttype-klassifisering — grupperer DEXPI-objekter i meningsfulle
# feilscenario-kategorier, saa brukeren velger TYPE foerst og bare ser
# relevante komponenter i nedtrekksmenyen etterpaa (i stedet for aa velge
# fritt blant instrumenter, ventiler, pumper, roersegmenter osv. om
# hverandre).
# ---------------------------------------------------------------------------

_VALVE_CLASSES = {"GateValve", "GlobeValve", "BallValve", "AngleValve",
                   "CheckValve", "PlugValve", "ButterflyValve", "NeedleValve"}


def classify_component_type(category: str, component_class: str) -> str:
    if category == "piping_component":
        if component_class in _VALVE_CLASSES:
            return "Ventiler"
        if component_class in {"Flange", "FlangedConnection", "PipeTee", "PipeReducer"}:
            return "Rørkomponenter (flens/reduksjon/gren)"
        if component_class == "FlowMeasuringElement":
            return "Strømningsmåleelementer"
        return "Andre rørkomponenter"
    if category == "piping_segment":
        return "Rørsegmenter"
    if category == "equipment":
        if component_class == "Pump":
            return "Pumper"
        if component_class == "Compressor":
            return "Kompressorer"
        return "Annet utstyr"
    if category in {"actuator", "actuating_system", "actuating_function"}:
        return "Aktuatorer"
    if category in {"instrument", "instrument_loop", "signal_generator"}:
        return "Instrumenter"
    if category == "nozzle":
        return "Dyser (nozzles)"
    if category in {"pipe_off_page", "signal_off_page"}:
        return "Off-page-referanser"
    return "Annet"


# Forklarer hva konsekvens-tallet FAKTISK betyr for hver type — siden en
# ventil som stenger fysisk isolerer et segment (hydratkonsekvens er direkte
# relevant), mens f.eks. et instrument som feiler normalt IKKE fysisk
# isolerer noe rørsegment i seg selv.
_TYPE_GUIDANCE = {
    "Ventiler": (
        "✅ **Mest fysisk relevant type.** En ventil som stenger isolerer "
        "direkte et rørsegment — hydratkonsekvensen under representerer "
        "en reell nedblåsingssituasjon."
    ),
    "Rørsegmenter": (
        "✅ **Fysisk relevant.** Et rørsegment som 'feiler' (f.eks. brudd) "
        "kan isolere resten av linjen på samme måte som en stengt ventil."
    ),
    "Pumper": (
        "⚠️ **Annen fysikk enn hydratmodellen antar.** En pumpe som stopper "
        "gir normalt tap av trykkstøtte/gjennomstrømning, ikke nødvendigvis "
        "en isolert, innestengt gassmengde. Isolasjonstallet under viser "
        "hva som grafmessig kuttes av, men hydratberegningen er mindre "
        "direkte anvendelig enn for en ventil."
    ),
    "Kompressorer": (
        "⚠️ **Annen fysikk enn hydratmodellen antar** — samme forbehold "
        "som for pumper."
    ),
    "Instrumenter": (
        "⚠️ **Sannsynligvis IKKE fysisk relevant.** Et instrument (måler/"
        "transmitter) som feiler stopper normalt ikke fysisk gjennomstrømning "
        "av seg selv — konsekvensen under er en strukturell isolasjon i "
        "DATA-grafen, ikke nødvendigvis en reell prosesskonsekvens, med "
        "mindre instrumentet er del av en interlock som faktisk stenger en "
        "ventil."
    ),
    "Aktuatorer": (
        "◐ **Delvis relevant.** En aktuator styrer typisk en ventil — hvis "
        "den feiler kan ventilen den betjener henge seg fast åpen/lukket, "
        "som igjen kan isolere et segment."
    ),
}
_DEFAULT_GUIDANCE = (
    "ℹ️ Fysisk relevans for hydratberegningen er ikke vurdert for denne "
    "komponenttypen — tolk konsekvenstallet med forsiktighet."
)


# ---------------------------------------------------------------------------
# Fluidfamilier — grupperer de 25 fluidkodene i intuitive kategorier, saa
# oversikten blir skannbar i stedet for en flat liste av tobokstavskoder.
# Tillitsniva gjenspeiler samme vurdering som i rapportens kildetabell
# (Table~\ref{tab:fluid_codes}) — ikke re-utledet her, kun gjengitt.
# ---------------------------------------------------------------------------
_FLUID_FAMILY = {
    "PV": ("🔥 Gass", "Moderat"), "VF": ("🔥 Gass", "Moderat"),
    "VA": ("🔥 Gass", "Moderat"), "OF": ("🔥 Gass", "Lav"),
    "GI": ("🔥 Gass", "Lav–moderat"), "GF": ("🔥 Gass", "Lav–moderat"),
    "GE": ("🔥 Gass", "Moderat"), "PT": ("🔥 Gass", "Lav"),
    "PI": ("🔥 Gass", "Svært lav"),
    "PL": ("💧 Væske/olje", "Moderat"), "OL": ("💧 Væske/olje", "Lav–moderat"),
    "OH": ("💧 Væske/olje", "Lav–moderat"), "CG": ("💧 Væske/olje", "Lav"),
    "WS": ("🌊 Vann", "Lav–moderat"), "WD": ("🌊 Vann", "Lav–moderat"),
    "WF": ("🌊 Vann", "Lav–moderat"), "WI": ("🌊 Vann", "Moderat"),
    "WC": ("🌊 Vann", "Lav–moderat"),
    "AI": ("💨 Luft", "Moderat"), "AP": ("💨 Luft", "Lav–moderat"),
    "CA": ("💨 Luft", "Moderat"),
    "CC": ("🧪 Kjemikalie", "Lav"), "MK": ("🧪 Kjemikalie", "Lav–moderat"),
    "DC": ("🚰 Drenering", "Moderat"), "DO": ("🚰 Drenering", "Moderat"),
}


@st.cache_data(show_spinner="Kobler komponenter til fluidkoder…")
def bulk_assign_fluid_codes(_xml_path: str, sub: pd.DataFrame) -> pd.DataFrame:
    """
    Rask versjon av lookup_fluid_code(): i stedet for aa parse XML-en paa
    nytt for HVER komponent (121ms per kall — for tregt for 100+ objekter),
    parses filen KUN ÉN gang, og alle navngitte komponenter kobles til
    naermeste roersegment i én samlet geometrisk sok (typisk <100ms totalt,
    testet mot ekte data).

    Returnerer sub-kopien med to nye kolonner: 'nearest_fluid_code' og
    'dist_to_segment_mm'. Komponenter uten noe roersegment i naerheten (eller
    paa tegninger uten segment-posisjoner) faar NaN.
    """
    root = ET.parse(_xml_path).getroot()

    def attr(el, name):
        for ga in el.findall("./GenericAttributes/GenericAttribute"):
            if ga.get("Name") == name:
                return ga.get("Value")
        return None

    seg_fluid_code = {}
    for el in root.iter("PipingNetworkSegment"):
        code = attr(el, "FluidCodeAssignmentClass")
        if code:
            seg_fluid_code[el.get("ID")] = code

    out = sub.copy()
    out["nearest_fluid_code"] = None
    out["dist_to_segment_mm"] = np.nan
    if not seg_fluid_code:
        return out

    positioned = out.dropna(subset=["x_mm", "y_mm"])
    segs = positioned[positioned["id"].isin(seg_fluid_code.keys())].copy()
    if segs.empty:
        return out
    segs["fluid_code"] = segs["id"].map(seg_fluid_code)
    # segmentene har sin EGEN kjente kode (avstand 0 — ikke avledet/naermeste-nabo)
    out.loc[segs.index, "nearest_fluid_code"] = segs["fluid_code"].values
    out.loc[segs.index, "dist_to_segment_mm"] = 0.0

    tree = cKDTree(segs[["x_mm", "y_mm"]].values)
    named = positioned[positioned["tag_name"].notna() & ~positioned["id"].isin(seg_fluid_code.keys())]
    if named.empty:
        return out
    dists, idxs = tree.query(named[["x_mm", "y_mm"]].values, k=1)
    codes = segs.iloc[idxs]["fluid_code"].values

    out.loc[named.index, "nearest_fluid_code"] = codes
    out.loc[named.index, "dist_to_segment_mm"] = dists
    return out


# Faste farger per fluidkode, konsistent per familie (samme visuelle logikk
# som CATEGORY_COLORS i app_failure_explorer.py — hver kode faar en egen
# nyanse innenfor familiens fargepalett).
_CODE_COLORS = {
    "PV": "#E8640F", "VF": "#F2984D", "VA": "#F7B87A", "OF": "#C94F00",
    "GI": "#D9773A", "GF": "#C25E1F", "GE": "#A84A0F", "PT": "#FFAD6B", "PI": "#FFCBA0",
    "PL": "#16233A", "OL": "#3E5A8C", "OH": "#2C4269", "CG": "#5C79A8",
    "WS": "#2E7D5B", "WD": "#4FA37F", "WF": "#7BC4A3", "WI": "#1E5E42", "WC": "#3F8F68",
    "AI": "#9AA0AC", "AP": "#BFC4CC", "CA": "#7B8290",
    "CC": "#7A3FB0", "MK": "#A375CC",
    "DC": "#A93A3A", "DO": "#C96666",
}


def plot_fluid_map(sub_full: pd.DataFrame, assigned: pd.DataFrame,
                   highlight_code: str | None = None) -> go.Figure:
    """
    Heltegnings-kart: hvert punkt paa tegningen fargelagt etter fluidkoden
    det (eller naermeste roersegment) har. Svarer paa "hvor i systemet
    skjer dette" — samme grunnprinsipp som topologiplottene i
    app_failure_explorer.py / DEXPI-topologi-siden, bare fargelagt etter
    fluidkode i stedet for objektkategori.

    highlight_code: hvis satt, tones alt UNNTATT denne koden ned, saa den
    valgte fluidkoden springer tydelig fram paa heltegningen.
    """
    pos = {row["id"]: (row["x_mm"], row["y_mm"]) for _, row in sub_full.iterrows()
           if pd.notna(row.get("x_mm"))}

    traces = []
    coded = assigned.dropna(subset=["nearest_fluid_code", "x_mm", "y_mm"])
    uncoded = assigned[assigned["nearest_fluid_code"].isna() & assigned["x_mm"].notna()]

    if not uncoded.empty:
        traces.append(go.Scatter(
            x=uncoded["x_mm"], y=uncoded["y_mm"], mode="markers",
            name="Ukjent/uten fluidkode",
            marker=dict(size=4, color="#3A3F4B"),
            hovertext=uncoded["tag_name"].fillna(uncoded["category"]), hoverinfo="text",
            opacity=0.35,
        ))

    for code, grp in coded.groupby("nearest_fluid_code"):
        dimmed = highlight_code is not None and code != highlight_code
        traces.append(go.Scatter(
            x=grp["x_mm"], y=grp["y_mm"], mode="markers",
            name=str(code),
            marker=dict(size=7 if not dimmed else 5,
                       color=_CODE_COLORS.get(code, "#9AA0AC"),
                       line=dict(width=0.5, color="white")),
            hovertext=grp["tag_name"].fillna(grp["category"]) + " · " + grp["nearest_fluid_code"],
            hoverinfo="text",
            opacity=1.0 if not dimmed else 0.15,
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        height=480, hovermode="closest", plot_bgcolor="#FAFAF7",
        xaxis=dict(visible=False), yaxis=dict(visible=False, autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=10)),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


@st.cache_data(show_spinner="Beregner konsekvens for alle komponenter på tegningen…")
def rank_failure_impacts(_G, sub: pd.DataFrame, drawing: str) -> pd.DataFrame:
    """
    Kjører simulate_failure() for HVER navngitte komponent paa tegningen, og
    rangerer dem etter hvor mange objekter som isoleres. Rask (typisk <1s
    for en hel tegning, ~3ms per komponent) siden hver simulering kun
    kopierer og fjerner én node fra en allerede innlest graf.

    Losningen paa at "tilfeldig valgte komponenter oftest gir 0 paavirket":
    typisk gir under HALVPARTEN av komponentene en synlig konsekvens (resten
    har 0 registrerte koblinger i DEXPI-dataen, se datakvalitet-forbeholdet
    andre steder paa siden). Ved aa rangere paa forhaand og vise de mest
    kritiske foerst, unngaar brukeren aa "gjette blindt" og treffe de
    kjedelige tilfellene gjentatte ganger.
    """
    named = sub[sub["tag_name"].notna()].copy()
    named["type_group"] = named.apply(
        lambda r: classify_component_type(r["category"], r["component_class"]), axis=1
    )
    rows = []
    for _, row in named.iterrows():
        tag = row["tag_name"]
        try:
            r = simulate_failure(_G, sub, tag)
        except ValueError:
            continue
        rows.append({
            "tag_name": tag,
            "type_group": row["type_group"],
            "n_affected": len(r["affected_ids"]),
            "own_degree": _G.degree(r["fail_id"]),
        })
    return pd.DataFrame(rows).sort_values("n_affected", ascending=False).reset_index(drop=True)


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

        # --- Bulk-kobling: hvilke NAVNGITTE komponenter (ventiler, instrumenter...)
        #     hoerer til hver fluidkode? Rask (<100ms), i motsetning til
        #     lookup_fluid_code() som parser XML per komponent. ---
        G_dummy, sub_full = load_graph(tags_all, conns_all, assocs_all, drawing)
        assigned = bulk_assign_fluid_codes(str(xml_path), sub_full)
        assigned["type_group"] = assigned.apply(
            lambda r: classify_component_type(r["category"], r["component_class"])
            if pd.notna(r.get("category")) else None, axis=1
        )

        st.divider()
        st.subheader("🗺️ Hvor i systemet finnes de ulike fluidkodene?")
        st.caption(
            "Hele tegningen, hvert punkt fargelagt etter naermeste fluidkode. "
            "Rørsegmenter har sin egen registrerte kode; andre komponenter "
            "(ventiler, instrumenter) er farget etter naermeste rørsegment."
        )
        st.plotly_chart(plot_fluid_map(sub_full, assigned), use_container_width=True)

        st.subheader("🧭 Fluidkoder i tegningen — hva de er, og hvor de finnes")
        st.caption(
            "Hver boks er én fluidkode funnet i DEXPI-dataen. Utvid for å se "
            "beskrivelse, tillitsnivå på tolkningen, hvilke navngitte "
            "komponenter som ligger nærmest, og hvor akkurat DENNE koden "
            "befinner seg på tegningen (resten er tonet ned)."
        )

        try:
            from neqsim_tools.fluid_lookup import get_preset
        except Exception:
            get_preset = None

        for _, row in summary.iterrows():
            code = row["fluid_code"]
            family, confidence = _FLUID_FAMILY.get(code, ("❓ Ukjent familie", "Ukjent"))
            preset = get_preset(code) if get_preset else None
            desc = preset["description"] if preset else "(beskrivelse utilgjengelig)"

            nearby = assigned[assigned["nearest_fluid_code"] == code]
            nearby_close = nearby[nearby["dist_to_segment_mm"] < 50]  # kun rimelig naere treff

            header = (f"{family}   **{code}**   ·   {row['n_segments']} segmenter, "
                     f"{row['n_unique_lines']} linje(r)   ·   Tillit: {confidence}")
            with st.expander(header):
                st.markdown(f"**Antatt betydning:** {desc}")
                colA, colB, colC = st.columns(3)
                colA.metric("Rørsegmenter", int(row["n_segments"]))
                colB.metric("Typisk diameter", f"{row['typical_diameter']}\"")
                colC.metric("Rørklasse(r)", row["piping_classes"])

                if not nearby_close.empty:
                    st.markdown("**Nærliggende navngitte komponenter** (gruppert per type):")
                    for tg, grp in nearby_close.groupby("type_group"):
                        chips = ", ".join(f"`{t}`" for t in sorted(grp["tag_name"].dropna().unique())[:12])
                        extra = "" if grp["tag_name"].nunique() <= 12 else f" … (+{grp['tag_name'].nunique()-12} til)"
                        st.markdown(f"- **{tg}** ({grp['tag_name'].nunique()} stk): {chips}{extra}")
                else:
                    st.caption("Ingen navngitte komponenter funnet geometrisk nær et "
                              "segment med denne fluidkoden (kan skyldes samme "
                              "koblingshull som er beskrevet i DEXPI-forbeholdet).")

                st.markdown(f"**Hvor på tegningen `{code}` befinner seg:**")
                st.plotly_chart(plot_fluid_map(sub_full, assigned, highlight_code=code),
                                use_container_width=True, key=f"map_{code}")

        st.divider()
        st.subheader("Fordeling av rørsegmenter per fluidkode")
        chart_df = summary.copy()
        chart_df["Familie"] = chart_df["fluid_code"].map(lambda c: _FLUID_FAMILY.get(c, ("❓",""))[0])
        st.bar_chart(chart_df.set_index("fluid_code")["n_segments"])

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
    named = sub[sub["tag_name"].notna()].copy()
    if named.empty:
        st.info("Ingen navngitte komponenter på denne tegningen.")
        st.stop()

    # --- Forhaandsberegnet rangering: de mest kritiske komponentene foerst,
    #     saa brukeren slipper aa klikke seg gjennom kjedelige "0 paavirket"
    #     tilfeller for aa finne noe interessant. ---
    ranking = rank_failure_impacts(G, sub, drawing)
    n_critical = (ranking["n_affected"] > 0).sum()

    st.subheader("🏆 Mest kritiske komponenter på denne tegningen")
    st.caption(
        f"{n_critical} av {len(ranking)} komponenter isolerer minst ett annet "
        f"objekt hvis de feiler. Forhåndsberegnet for hele tegningen — "
        f"velg en av dem under for full detalj og hydratkonsekvens."
    )
    top10 = ranking[ranking["n_affected"] > 0].head(10)
    if not top10.empty:
        col_chart, col_table = st.columns([2, 1])
        with col_chart:
            st.bar_chart(top10.set_index("tag_name")["n_affected"])
        with col_table:
            st.dataframe(
                top10[["tag_name", "type_group", "n_affected"]],
                use_container_width=True, hide_index=True, height=380,
            )
    else:
        st.info("Ingen komponenter på denne tegningen isolerer noe ifølge de "
                "eksplisitte DEXPI-koblingene — se datakvalitet-forbeholdet nederst.")

    st.divider()

    named["type_group"] = named.apply(
        lambda r: classify_component_type(r["category"], r["component_class"]), axis=1
    )
    impact_by_tag = dict(zip(ranking["tag_name"], ranking["n_affected"]))
    type_max_impact = named["type_group"].map(
        lambda t: ranking[ranking["type_group"] == t]["n_affected"].max()
    )
    counts = named["type_group"].value_counts()
    max_by_type = ranking.groupby("type_group")["n_affected"].max()
    type_options = [
        f"{t} ({counts[t]} stk, opptil {int(max_by_type.get(t, 0))} påvirket)"
        for t in counts.index
    ]
    type_display_to_raw = {opt: t for opt, t in zip(type_options, counts.index)}

    chosen_display = st.selectbox(
        "1️⃣ Type komponent som skal feile",
        type_options,
        help="Velg foerst HVILKEN TYPE komponent — nedtrekksmenyen under "
             "filtreres deretter til kun aa vise komponenter av denne typen, "
             "sortert med de mest kritiske foerst."
    )
    chosen_type = type_display_to_raw[chosen_display]
    st.caption(_TYPE_GUIDANCE.get(chosen_type, _DEFAULT_GUIDANCE))

    # sorter etter FAKTISK konsekvens (mest kritisk foerst), ikke alfabetisk
    group_tags = named[named["type_group"] == chosen_type]["tag_name"].unique()
    sorted_tags = sorted(group_tags, key=lambda t: -impact_by_tag.get(t, 0))
    tag_options = [f"{t} ({impact_by_tag.get(t, 0)} påvirket)" for t in sorted_tags]
    tag_display_to_raw = {opt: t for opt, t in zip(tag_options, sorted_tags)}

    chosen_tag_display = st.selectbox("2️⃣ Komponent", ["(ingen valgt)"] + tag_options)

    if chosen_tag_display == "(ingen valgt)":
        st.caption("Velg en komponent over for å simulere en feil og se hydratkonsekvensen.")
        st.stop()
    fail_tag = tag_display_to_raw[chosen_tag_display]

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

    with st.expander("ℹ️ For hvilke fluidkoder gir hydratberegningen faktisk et resultat?"):
        try:
            from neqsim_tools.fluid_lookup import FLUID_PRESETS
            oversikt = []
            for code, preset in FLUID_PRESETS.items():
                comps = {c for c, _ in preset["components"]}
                has_water = "water" in comps
                has_hc = any(c in comps for c in
                            ["methane", "ethane", "propane", "i-butane", "n-butane"])
                oversikt.append({
                    "Fluidkode": code,
                    "Hydratberegning mulig?": "✅ Ja" if (has_water and has_hc) else "❌ Nei",
                    "Hvorfor": ("Har både vann og hydrokarbongass" if (has_water and has_hc)
                               else "Mangler vann" if not has_water
                               else "Mangler hydrokarbongass (f.eks. ren luft/olje)"),
                })
            st.dataframe(pd.DataFrame(oversikt), use_container_width=True, hide_index=True)
            st.caption(
                "Hydratdannelse krever BÅDE vann OG lette hydrokarboner til stede "
                "samtidig. Rene vannsystemer (WS/WD/WF/WI/WC/MK) og ren luft "
                "(AI/AP/CA) gir derfor riktig nok 'Nei' — det er ikke en feil, "
                "det er fysisk forventet."
            )
        except Exception:
            st.caption("(Kunne ikke laste fluidkode-oversikten)")

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