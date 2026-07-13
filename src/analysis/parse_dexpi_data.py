# src/analysis/parse_dexpi_data.py
"""
Hent ut ekte topologi fra DEXPI-XML-eksportene (*.DGN.xml).

I motsetning til main.py (som kun regex-soeker tag-NAVN i PDF-tekst) leser
dette scriptet den semantiske DEXPI-modellen bak DGN-tegningene. Der finnes
instrumenter, ventiler, roerlinjer og utstyr som EKTE objekter med posisjon
OG eksplisitte koblinger til hverandre — dvs. den fysiske og signalmessige
topologien i P&ID-en, ikke bare hvilke tagger som finnes.

Output:
  data/processed/dexpi_tags.csv         — ett plantobjekt per rad
  data/processed/dexpi_connections.csv  — fysiske/signal-koblinger (grafkanter)
  data/processed/dexpi_associations.csv — semantiske relasjoner
                                           (f.eks. "is fulfilled by")
  reports/figures/dexpi_topology_<tegning>.png
                                         — rekonstruert layout av tegningen,
                                           plottet med de EKTE koordinatene
                                           fra XML-en
  reports/figures/dexpi_category_counts.png
                                         — hvilke objekttyper finnes mest av

Krever networkx:  pip install networkx
Kjor fra prosjektroten:  python -m analysis.parse_dexpi_data
(eller:  python analysis/parse_dexpi_data.py  fra src/, se README-notat i main.py
 om hvorfor -m-varianten er tryggere for imports)
"""

import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import seaborn as sns

# Gjoer scriptet koerbart baade som modul og direkte, uavhengig av arbeidsmappe
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extraction.dexpi_parser import find_dexpi_files, parse_dexpi  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"

CATEGORY_COLORS = {
    "instrument": "#E8640F", "instrument_loop": "#B08A2E", "signal_generator": "#E8640F",
    "piping_component": "#16233A", "piping_segment": "#3E6FB0", "piping_system": "#3E6FB0",
    "equipment": "#A93A3A", "nozzle": "#2E7D5B",
    "actuator": "#7A6FB0", "actuating_system": "#7A6FB0", "actuating_function": "#7A6FB0",
    "pipe_off_page": "#9AA0AC", "signal_off_page": "#9AA0AC",
}


# ---------------------------------------------------------------------------
# Innlasting: parse alle filer og slaa sammen
# ---------------------------------------------------------------------------

def load_all(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    files = find_dexpi_files(raw_dir)
    log.info("Fant %d DEXPI-XML-filer under %s", len(files), raw_dir)
    if not files:
        log.error(
            "Ingen '*.DGN.xml'-filer funnet. Ligger de under data/raw/ "
            "med det samme mappeoppsettet som PDF-ene?"
        )

    all_tags, all_conns, all_assocs = [], [], []
    for f in files:
        try:
            tags, conns, assocs = parse_dexpi(f)
        except Exception as exc:
            log.warning("Hopper over %s: %s", f.name, exc)
            continue
        log.info("  %-40s %4d objekter  %4d koblinger  %4d relasjoner",
                  f.name, len(tags), len(conns), len(assocs))
        all_tags.append(tags)
        all_conns.append(conns)
        all_assocs.append(assocs)

    tags_df = pd.concat(all_tags, ignore_index=True) if all_tags else pd.DataFrame()
    conn_df = pd.concat(all_conns, ignore_index=True) if all_conns else pd.DataFrame()
    assoc_df = pd.concat(all_assocs, ignore_index=True) if all_assocs else pd.DataFrame()
    return tags_df, conn_df, assoc_df


# ---------------------------------------------------------------------------
# Graf: bygg en NetworkX-graf per tegning
# ---------------------------------------------------------------------------

def build_graph(tags: pd.DataFrame, conns: pd.DataFrame, assocs: pd.DataFrame,
                 drawing: str) -> nx.Graph:
    """Bygg topologigraf for én tegning. Noder = plantobjekter, kanter =
    baade fysiske/signal-koblinger (Connection) og semantiske relasjoner
    (Association) som knytter to ekte objekter sammen."""
    sub_tags = tags[tags["drawing"] == drawing]
    G = nx.Graph()
    for _, r in sub_tags.iterrows():
        if pd.notna(r["x_mm"]):
            G.add_node(r["id"], category=r["category"], tag_name=r["tag_name"],
                       component_class=r["component_class"], pos=(r["x_mm"], r["y_mm"]))

    sub_conns = conns[conns["drawing"] == drawing].dropna(subset=["from_id", "to_id"])
    for _, r in sub_conns.iterrows():
        if r["from_id"] in G.nodes and r["to_id"] in G.nodes:
            G.add_edge(r["from_id"], r["to_id"], kind=r["kind"])

    sub_assocs = assocs[assocs["drawing"] == drawing].dropna(subset=["source_id", "target_id"])
    for _, r in sub_assocs.iterrows():
        if r["source_id"] in G.nodes and r["target_id"] in G.nodes and \
           not G.has_edge(r["source_id"], r["target_id"]):
            G.add_edge(r["source_id"], r["target_id"], kind=r["assoc_type"])

    return G


# ---------------------------------------------------------------------------
# Visualisering
# ---------------------------------------------------------------------------

def plot_topology(G: nx.Graph, drawing: str) -> None:
    """Plott tegningen rekonstruert fra de ekte XML-koordinatene."""
    pos = nx.get_node_attributes(G, "pos")
    if not pos:
        return
    cats = nx.get_node_attributes(G, "category")
    colors = [CATEGORY_COLORS.get(cats.get(n), "#9AA0AC") for n in G.nodes]

    plt.figure(figsize=(15, 10))
    nx.draw_networkx_edges(G, pos, alpha=0.35, width=0.8, edge_color="#6B7484")
    nx.draw_networkx_nodes(G, pos, node_size=26, node_color=colors, linewidths=0)
    plt.gca().invert_yaxis()  # matcher tegningens visuelle orientering
    plt.gca().set_aspect("equal")
    plt.axis("off")
    plt.title(f"Rekonstruert topologi — {drawing}", fontsize=12)

    handles = [plt.Line2D([], [], marker="o", linestyle="", color=c, label=cat)
               for cat, c in CATEGORY_COLORS.items() if cat in cats.values()]
    plt.legend(handles=handles, loc="upper left", fontsize=8, bbox_to_anchor=(1.0, 1.0))
    plt.tight_layout()
    safe_name = drawing.replace("/", "-")
    plt.savefig(FIG_DIR / f"dexpi_topology_{safe_name}.png", dpi=150)
    plt.close()


def plot_category_counts(tags: pd.DataFrame) -> None:
    counts = tags["category"].value_counts()
    plt.figure(figsize=(9, 6))
    sns.barplot(x=counts.values, y=counts.index, hue=counts.index,
                palette=[CATEGORY_COLORS.get(c, "#9AA0AC") for c in counts.index],
                legend=False)
    plt.title("Plantobjekter funnet i DEXPI-dataene, per kategori")
    plt.xlabel("Antall")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "dexpi_category_counts.png", dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid")

    tags, conns, assocs = load_all(RAW_DIR)
    if tags.empty:
        return

    tags.to_csv(PROCESSED_DIR / "dexpi_tags.csv", index=False)
    conns.to_csv(PROCESSED_DIR / "dexpi_connections.csv", index=False)
    assocs.to_csv(PROCESSED_DIR / "dexpi_associations.csv", index=False)

    print("\n=== DEXPI-UTTREKK " + "=" * 44)
    print(f"Tegninger parset     : {tags['drawing'].nunique()}")
    print(f"Plantobjekter totalt  : {len(tags)}")
    print(f"Koblinger (fysisk/signal) : {len(conns)}")
    print(f"Semantiske relasjoner : {len(assocs)}")
    print("\nObjekter per kategori:")
    print(tags["category"].value_counts().to_string())

    print("\nGraf-sammenheng per tegning:")
    for drawing in sorted(tags["drawing"].unique()):
        G = build_graph(tags, conns, assocs, drawing)
        n_components = nx.number_connected_components(G) if G.number_of_nodes() else 0
        largest = max((len(c) for c in nx.connected_components(G)), default=0)
        print(f"  {drawing:35s}  {G.number_of_nodes():4d} noder  "
              f"{G.number_of_edges():4d} kanter  {n_components:3d} komponenter  "
              f"(stoerste: {largest})")
        plot_topology(G, drawing)

    plot_category_counts(tags)

    print(f"\nCSV-er lagret i    : {PROCESSED_DIR.relative_to(ROOT)}")
    print(f"Figurer lagret i   : {FIG_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()