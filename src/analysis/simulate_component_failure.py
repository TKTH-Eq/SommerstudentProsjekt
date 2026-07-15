# src/analysis/simulate_component_failure.py
"""
Bruker DEXPI-topologien til aa 1) finne strukturelle avvik i tegningene, og
2) simulere hva som skjer STRUKTURELT naar en komponent feiler (f.eks. en
ventil som stenger uventet) — hvilke andre objekter blir isolert fra resten
av systemet som konsekvens? Til slutt: bruk NeqSim til aa beregne den
FYSISKE konsekvensen (trykk/temperatur/hydratrisiko) i det isolerte
segmentet.

Tre deler:

  1. find_structural_issues()
     Kvalitetssjekk PAA GRAFEN: objekter med null koblinger (isolerte),
     og de stoerste "oeyene" av smaa, frittstaaende klynger. IKKE ta dette
     som en fasit-liste over tegningsfeil — se advarselen i funksjonen.

  2. simulate_failure()
     Fjerner én komponent fra grafen (simulerer "denne feiler helt av/til",
     f.eks. en ventil som stenger og isolerer alt nedstroems) og
     sammenligner sammenhengs-komponentene FOER og ETTER. Det som splittes
     ut i en ny, mindre gruppe er det som "rammes" av feilen.

  3. neqsim_consequence()
     For det isolerte segmentet: bruk NeqSim til aa anslaa hydratrisiko
     dersom segmentet blaases ned (samme metodikk som
     neqsim_hydrate_viz.py). Dette er en FORENKLET illustrasjon, ikke en
     presis prosessberegning — se forbehold der.

Kjor fra prosjektroten:
    python -m analysis.simulate_component_failure <tegningsnavn> <tag-navn>

Eksempel:
    python -m analysis.simulate_component_failure C025-V-HO27-P-_E-001-01 27-4510PV
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"


# ---------------------------------------------------------------------------
# Grafbygging (gjenbruker samme logikk som parse_dexpi_data.py)
# ---------------------------------------------------------------------------

def load_graph(tags: pd.DataFrame, conns: pd.DataFrame, assocs: pd.DataFrame,
                drawing: str) -> tuple[nx.Graph, pd.DataFrame]:
    sub = tags[tags["drawing"] == drawing]
    G = nx.Graph()
    for _, r in sub.dropna(subset=["x_mm", "y_mm"]).iterrows():
        G.add_node(r["id"], category=r["category"], tag_name=r["tag_name"],
                   component_class=r["component_class"], pos=(r["x_mm"], r["y_mm"]))
    for edges, cols in ((conns, ("from_id", "to_id")), (assocs, ("source_id", "target_id"))):
        sub_e = edges[edges["drawing"] == drawing].dropna(subset=list(cols))
        for _, r in sub_e.iterrows():
            if r[cols[0]] in G.nodes and r[cols[1]] in G.nodes:
                G.add_edge(r[cols[0]], r[cols[1]])
    return G, sub


# ---------------------------------------------------------------------------
# 1. Strukturelle avvik
# ---------------------------------------------------------------------------

def find_structural_issues(G: nx.Graph, tags: pd.DataFrame) -> None:
    """
    VIKTIG FORBEHOLD: DEXPI-dataen fanger kun EKSPLISITTE <Connection>- og
    <Association>-elementer. Roerlinje-etiketter og enkelte symboler kan
    mangle disse selv om de er geometrisk koblet paa tegningen (implisitt
    via linjetegning, ikke eksplisitt i XML-en). Isolerte objekter er derfor
    en BLANDING av ekte avvik OG kjente hull i DEXPI-eksporten — bruk dette
    som en prioritert sjekkliste for manuell gjennomgang, ikke en fasit.
    """
    isolated = [n for n in G.nodes if G.degree(n) == 0]
    isolated_tags = tags[tags["id"].isin(isolated) & tags["tag_name"].notna()]

    print(f"Isolerte objekter (grad 0): {len(isolated)} totalt, "
          f"{len(isolated_tags)} med tag-navn")
    if len(isolated_tags):
        print("  Eksempler:", ", ".join(isolated_tags["tag_name"].head(8)))

    components = sorted(nx.connected_components(G), key=len, reverse=True)
    small = [c for c in components if 1 < len(c) <= 3]
    print(f"\nSmaa frittstaaende klynger (2-3 objekter, kan vaere ufullstendig "
          f"koblet): {len(small)} stk")


# ---------------------------------------------------------------------------
# 2. Feilsimulering: fjern en komponent, se hva som isoleres
# ---------------------------------------------------------------------------

def simulate_failure(G: nx.Graph, tags: pd.DataFrame, fail_tag: str) -> dict:
    row = tags[tags["tag_name"] == fail_tag]
    if row.empty:
        raise ValueError(f"Fant ingen komponent med tag-navn '{fail_tag}' paa denne tegningen.")
    fail_id = row["id"].iloc[0]
    if fail_id not in G.nodes:
        raise ValueError(f"'{fail_tag}' har ingen posisjon/kobling i grafen.")

    neighbors = list(G.neighbors(fail_id))
    before_component = nx.node_connected_component(G, fail_id)

    G2 = G.copy()
    G2.remove_node(fail_id)

    after_components = list(nx.connected_components(G2))
    comp_of = {n: i for i, c in enumerate(after_components) for n in c}

    # grupper naboene etter hvilken (nye) komponent de havnet i
    groups: dict[int, list[str]] = {}
    for nb in neighbors:
        groups.setdefault(comp_of.get(nb, -1), []).append(nb)

    # "hovedgruppen" er den som beholder FLEST objekter totalt (faktisk
    # komponentstoerrelse etter fjerning) — ikke den med flest direkte
    # naboer til den feilende komponenten, som ga feil svar foerste forsoek
    group_component_size = {
        gid: len(after_components[gid]) for gid in groups if gid != -1
    }
    main_gid = max(group_component_size, key=group_component_size.get) if group_component_size else None

    affected_ids: set[str] = set()
    for gid in groups:
        if gid != main_gid:
            affected_ids |= after_components[gid] if gid != -1 else set(groups[gid])

    affected_tags = tags[tags["id"].isin(affected_ids) & tags["tag_name"].notna()]

    print(f"\nFeiler: {fail_tag} ({row['component_class'].iloc[0]})")
    print(f"Foer feil: samlet i én gruppe paa {len(before_component)} objekter")
    print(f"Etter feil: splittes i {len(groups)} grupper")
    print(f"Antall objekter som isoleres/paavirkes: {len(affected_ids)} "
          f"({len(affected_tags)} med tag-navn)")
    if len(affected_tags):
        print("  Paavirkede tagger:", ", ".join(affected_tags["tag_name"].head(15)))

    return {"fail_id": fail_id, "fail_tag": fail_tag, "affected_ids": affected_ids,
            "affected_tags": affected_tags}


def plot_failure(G: nx.Graph, tags: pd.DataFrame, result: dict, drawing: str) -> None:
    pos = nx.get_node_attributes(G, "pos")
    colors = []
    sizes = []
    for n in G.nodes:
        if n == result["fail_id"]:
            colors.append("#E8640F"); sizes.append(120)   # den som feiler: oransje, stor
        elif n in result["affected_ids"]:
            colors.append("#A93A3A"); sizes.append(50)    # paavirket: roed
        else:
            colors.append("#9AA0AC"); sizes.append(20)    # upaavirket: graa

    plt.figure(figsize=(14, 10))
    nx.draw_networkx_edges(G, pos, alpha=0.3, width=0.7, edge_color="#6B7484")
    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=sizes, linewidths=0)
    plt.gca().invert_yaxis()
    plt.gca().set_aspect("equal")
    plt.axis("off")
    plt.title(f"Feilsimulering: {result['fail_tag']} feiler — {drawing}\n"
              f"oransje = feilende komponent, roedt = paavirkede objekter ({len(result['affected_ids'])} stk)")
    plt.tight_layout()
    out = FIG_DIR / f"failure_simulation_{result['fail_tag'].replace('/', '-')}.png"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"\nFigur lagret: {out.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# 3. NeqSim: fysisk konsekvens i det paavirkede segmentet
# ---------------------------------------------------------------------------

def lookup_fluid_code(xml_path: Path, sub: pd.DataFrame, fail_id: str, k: int = 8):
    """
    Finn den mest sannsynlige fluidkoden for segmentet rundt den feilende
    komponenten. DEXPI sin eksplisitte koblingsgraf naar sjelden helt fram
    til et PipingNetworkSegment-objekt (samme begrensning som gjorde mange
    objekter "isolerte" tidligere) — derfor brukes geometrisk naerhet HER,
    kun for aa slaa opp fluidkoden, IKKE for aa endre selve feil-topologien.

    Soeker blant de k naermeste roersegmentene til den feilende komponenten
    og bruker den foerste som faktisk har en utfylt FluidCodeAssignmentClass
    (kun 85% av segmentene har denne attributten i testdataene, saa naermeste
    segment alene er ikke alltid nok).
    """
    import xml.etree.ElementTree as ET
    import numpy as np
    from scipy.spatial import cKDTree

    root = ET.parse(xml_path).getroot()

    def attr(el, name):
        for ga in el.findall("./GenericAttributes/GenericAttribute"):
            if ga.get("Name") == name:
                return ga.get("Value")
        return None

    id_to_el = {el.get("ID"): el for el in root.iter() if el.get("ID")}

    fail_row = sub[sub["id"] == fail_id]
    if fail_row.empty or pd.isna(fail_row.iloc[0]["x_mm"]):
        return None
    fail_pos = np.array([fail_row.iloc[0]["x_mm"], fail_row.iloc[0]["y_mm"]])

    segs = sub[sub["category"].isin(["piping_segment", "piping_system"])
               & sub["x_mm"].notna()].reset_index(drop=True)
    if segs.empty:
        return None

    tree = cKDTree(segs[["x_mm", "y_mm"]].values)
    k_use = min(k, len(segs))
    dists, idxs = tree.query(fail_pos, k=k_use)
    dists, idxs = np.atleast_1d(dists), np.atleast_1d(idxs)
    for seg_idx in idxs:
        el = id_to_el.get(segs.iloc[seg_idx]["id"])
        if el is not None:
            code = attr(el, "FluidCodeAssignmentClass")
            if code:
                return code
    return None


def neqsim_consequence(affected_count: int, xml_path: Path | None = None,
                       sub: pd.DataFrame | None = None, fail_id: str | None = None) -> None:
    """
    Anslaa hydratrisiko i det isolerte segmentet ved nedblaasing, med
    fluidsammensetning hentet fra DEXPI sin FluidCodeAssignmentClass naar
    mulig (via fluid_lookup.py), i stedet for alltid samme generiske gass.

    FORBEHOLD (se ogsaa neqsim/fluid_lookup.py): fluidkode -> sammensetning
    -mappingen er BEGRUNNEDE GJETNINGER, ikke bekreftet mot "P&ID Legend
    Huldra". Trykk/temperatur er fortsatt IKKE i DEXPI-dataen og maa komme
    fra prosessdatablad — brukes her kun som eksempelverdier (90/30/10 bara).
    """
    try:
        from neqsim.thermo import hydt
        sys.path.insert(0, str(ROOT / "src"))
        from neqsim_tools.fluid_lookup import get_preset, build_neqsim_fluid
    except ImportError:
        print("\n(NeqSim ikke installert her — hopper over fysisk konsekvensberegning. "
              "Kjor 'pip install neqsim' for aa faa denne delen.)")
        return
    except Exception as e:
        print(f"\n(NeqSim/JVM-feil — hopper over fysisk konsekvensberegning: {e})")
        return

    fluid_code = None
    if xml_path is not None and sub is not None and fail_id is not None:
        try:
            fluid_code = lookup_fluid_code(xml_path, sub, fail_id)
        except Exception as e:
            print(f"(Klarte ikke slaa opp fluidkode: {e})")

    preset = get_preset(fluid_code)
    match_note = (f"fluidkode '{preset['code']}' funnet i DEXPI-data" if preset["matched"]
                  else f"INGEN fluidkode funnet naer feilpunktet — bruker standard "
                       f"({DEFAULT_PRESET if 'DEFAULT_PRESET' in dir() else preset['code']})")

    print(f"\n=== NeqSim: hydratrisiko ved nedblaasing av det isolerte segmentet "
          f"({affected_count} objekter) ===")
    print(f"  Fluid: {preset['description']}  [{match_note}]")

    f = build_neqsim_fluid(preset)
    for p in (90.0, 30.0, 10.0):
        f.setPressure(p, "bara")
        f.setTemperature(10.0, "C")
        try:
            hydt(f)
            print(f"  Ved {p:5.0f} bara: hydrattemperatur ≈ {f.getTemperature('C'):.1f} °C")
        except Exception:
            print(f"  Ved {p:5.0f} bara: hydratberegning feilet (fase = {preset['phase']}"
                  " — hydratberegning er kun meningsfull for gass/kondensat)")
    print("  -> Hvis segmentets faktiske temperatur er under disse verdiene ved "
          "trykkfallet, er det risiko for hydratdannelse ved isolering/nedblaasing.")
    if not preset["matched"]:
        print("  ⚠ Fluidtype IKKE bekreftet for dette segmentet — tallene over "
              "gjelder kun hvis det faktisk fører prosessgass, verifiser manuelt.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 3:
        print("Bruk: python -m analysis.simulate_component_failure <tegningsnavn> <tag-navn>")
        print("Eksempel: python -m analysis.simulate_component_failure "
              "C025-V-HO27-P-_E-001-01 27-4510PV")
        return
    drawing, fail_tag = sys.argv[1], sys.argv[2]

    tags = pd.read_csv(PROCESSED_DIR / "dexpi_tags.csv")
    conns = pd.read_csv(PROCESSED_DIR / "dexpi_connections.csv")
    assocs = pd.read_csv(PROCESSED_DIR / "dexpi_associations.csv")

    if drawing not in tags["drawing"].unique():
        print(f"Fant ikke tegningen '{drawing}'. Tilgjengelige tegninger:")
        for d in sorted(tags["drawing"].unique()):
            print(f"  {d}")
        return

    G, sub = load_graph(tags, conns, assocs, drawing)
    print(f"=== {drawing}: {G.number_of_nodes()} noder, {G.number_of_edges()} kanter ===\n")

    find_structural_issues(G, sub)

    try:
        result = simulate_failure(G, sub, fail_tag)
    except ValueError as e:
        print(f"\nFEIL: {e}")
        candidates = sub["tag_name"].dropna().unique()
        print(f"Noen tilgjengelige tag-navn paa denne tegningen: "
              f"{', '.join(sorted(candidates)[:15])}")
        return

    plot_failure(G, sub, result, drawing)
    xml_path = next((f for f in RAW_DIR.rglob("*.xml") if drawing in f.stem), None)
    neqsim_consequence(len(result["affected_ids"]), xml_path=xml_path,
                       sub=sub, fail_id=result["fail_id"])


if __name__ == "__main__":
    main()