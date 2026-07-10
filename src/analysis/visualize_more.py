# src/visualize_more.py
"""
Flere maater aa visualisere tag-dataene paa.

Bygger videre paa resultatene fra main.py (og evt. ml_cluster.py):
leser data/processed/tags.csv (og clusters.csv hvis den finnes)
i stedet for aa parse PDF-ene paa nytt. Kjor derfor main.py foerst.

Lager:
  1. Donutdiagram   — tagger gruppert i funksjonskategorier
                      (trykk, temperatur, nivaa, ventiler, ...)
  2. Stablet soyle  — funksjonskategori per system (13, 20, 42, ...)
  3. Samforekomst   — heatmap: hvor ofte opptrer to instrumenttyper
                      paa samme tegning?
  4. Nettverksgraf  — tegninger koblet sammen naar de deler tagger
                      (krever networkx:  pip install networkx)
  5. Tagnummer-strip — hvordan tagnumrene fordeler seg per system
                      (avslorer nummerserier/looper)
  6. Cluster-profil — instrumenttype per ML-cluster
                      (kun hvis ml_cluster.py er kjoert)

Kjor fra prosjektroten:  python src/visualize_more.py
"""

import logging
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"

TAGS_CSV = PROCESSED_DIR / "tags.csv"
CLUSTERS_CSV = PROCESSED_DIR / "clusters.csv"

# Grupper ISA-kodene i overordnede funksjonskategorier
CATEGORIES = {
    "Trykk":       ["PT", "PI", "PDI", "PDT", "PSV", "PX"],
    "Temperatur":  ["TT", "TI"],
    "Mengde":      ["FT", "FI"],
    "Nivaa":       ["LT", "LI", "LSL", "LSH"],
    "Ventiler":    ["ESV", "XV", "HV"],
    "Posisjon":    ["ZSL", "ZSH"],
    "Betjening":   ["HS", "HIC", "US", "XS"],
    "Alarm/logikk": ["XA", "XI", "UZS"],
}
TYPE_TO_CATEGORY = {t: cat for cat, types in CATEGORIES.items() for t in types}


# ---------------------------------------------------------------------------
# Innlasting
# ---------------------------------------------------------------------------

def load_tags() -> pd.DataFrame:
    if not TAGS_CSV.exists():
        raise FileNotFoundError(
            f"Fant ikke {TAGS_CSV.relative_to(ROOT)} — kjoer 'python src/main.py' foerst."
        )
    df = pd.read_csv(TAGS_CSV, dtype={"system": "string"})
    df["category"] = df["tag_type"].map(TYPE_TO_CATEGORY).fillna("Annet")
    # Numerisk del av taggen ("13-PI 2306A" -> 2306)
    df["tag_no"] = (
        df["tag"].str.extract(r"(\d{3,4})[A-Z]?$")[0].astype("float")
    )
    return df


# ---------------------------------------------------------------------------
# 1. Donut: funksjonskategorier
# ---------------------------------------------------------------------------

def plot_category_donut(df: pd.DataFrame) -> None:
    counts = df["category"].value_counts()
    colors = sns.color_palette("viridis", len(counts))

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, _, autotexts = ax.pie(
        counts.values,
        labels=counts.index,
        autopct=lambda p: f"{p:.0f}%" if p > 3 else "",
        pctdistance=0.78,
        colors=colors,
        wedgeprops={"width": 0.42, "edgecolor": "white"},
        startangle=90,
    )
    plt.setp(autotexts, color="white", fontweight="bold")
    ax.text(0, 0, f"{len(df)}\ntagger", ha="center", va="center",
            fontsize=16, fontweight="bold")
    ax.set_title("Tagger fordelt paa funksjonskategori")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "category_donut.png", dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# 2. Stablet soyle: kategori per system
# ---------------------------------------------------------------------------

def plot_category_per_system(df: pd.DataFrame) -> None:
    sub = df.dropna(subset=["system"])
    if sub.empty:
        log.info("Ingen tagger med systemnummer — hopper over systemplot.")
        return

    pivot = (
        sub.pivot_table(index="system", columns="category",
                        aggfunc="size", fill_value=0)
        .sort_index()
    )
    pivot.plot(
        kind="bar", stacked=True, figsize=(11, 6),
        colormap="viridis", width=0.8,
    )
    plt.title("Funksjonskategori per system")
    plt.xlabel("Systemnummer")
    plt.ylabel("Antall tagger")
    plt.legend(title="", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "category_per_system.png", dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# 3. Samforekomst av instrumenttyper
# ---------------------------------------------------------------------------

def plot_cooccurrence(df: pd.DataFrame, top_n: int = 12) -> None:
    """Hvor ofte finnes to instrumenttyper paa SAMME tegning?
    Avslorer faste 'foelgesvenner' som ESV + ZSL/ZSH."""
    top_types = df["tag_type"].value_counts().head(top_n).index.tolist()
    per_drawing = (
        df[df["tag_type"].isin(top_types)]
        .groupby("drawing")["tag_type"].apply(set)
    )

    matrix = pd.DataFrame(0, index=top_types, columns=top_types)
    for types in per_drawing:
        for a, b in combinations(sorted(types), 2):
            matrix.loc[a, b] += 1
            matrix.loc[b, a] += 1
        for t in types:
            matrix.loc[t, t] += 1

    mask = np.triu(np.ones_like(matrix, dtype=bool), k=1)
    plt.figure(figsize=(10, 8))
    sns.heatmap(matrix, mask=mask, annot=True, fmt="d",
                cmap="rocket_r", linewidths=0.5, square=True)
    plt.title("Samforekomst: antall tegninger der begge typene finnes")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "type_cooccurrence.png", dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# 4. Nettverksgraf: tegninger som deler tagger
# ---------------------------------------------------------------------------

def plot_drawing_network(df: pd.DataFrame, min_shared: int = 2) -> None:
    try:
        import networkx as nx
    except ImportError:
        log.warning("networkx ikke installert — hopper over nettverksgraf. "
                    "(pip install networkx)")
        return

    tags_per_drawing = df.groupby("drawing")["tag"].apply(set)
    G = nx.Graph()
    G.add_nodes_from(tags_per_drawing.index)

    for a, b in combinations(tags_per_drawing.index, 2):
        shared = len(tags_per_drawing[a] & tags_per_drawing[b])
        if shared >= min_shared:
            G.add_edge(a, b, weight=shared)

    # Fjern tegninger uten koblinger for et ryddigere plot
    G.remove_nodes_from(list(nx.isolates(G)))
    if G.number_of_edges() == 0:
        log.info("Ingen tegninger deler >= %d tagger — hopper over graf.", min_shared)
        return

    folder_of = df.drop_duplicates("drawing").set_index("drawing")["folder"]
    folders = sorted(folder_of.loc[list(G.nodes)].unique())
    palette = dict(zip(folders, sns.color_palette("tab10", len(folders))))
    node_colors = [palette[folder_of[n]] for n in G.nodes]

    n_tags = df.groupby("drawing").size()
    node_sizes = [40 + 6 * n_tags.get(n, 1) for n in G.nodes]
    edge_widths = [0.4 * G[u][v]["weight"] for u, v in G.edges]

    pos = nx.spring_layout(G, k=0.6, seed=42, weight="weight")
    plt.figure(figsize=(13, 9))
    nx.draw_networkx_edges(G, pos, width=edge_widths, alpha=0.35)
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes,
                           edgecolors="white", linewidths=0.8)
    nx.draw_networkx_labels(G, pos, font_size=6)

    handles = [plt.Line2D([], [], marker="o", linestyle="", color=c, label=f)
               for f, c in palette.items()]
    plt.legend(handles=handles, title="Mappe", fontsize=8, loc="lower right")
    plt.title(f"Tegninger som deler minst {min_shared} tagger "
              "(tykkere strek = flere felles tagger)")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "drawing_network.png", dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# 5. Tagnummer-fordeling per system
# ---------------------------------------------------------------------------

def plot_tag_number_strip(df: pd.DataFrame) -> None:
    sub = df.dropna(subset=["system", "tag_no"])
    if sub.empty:
        return
    order = sorted(sub["system"].unique())

    plt.figure(figsize=(11, 6))
    sns.stripplot(data=sub, x="tag_no", y="system", hue="category",
                  order=order, palette="viridis", size=4, alpha=0.7,
                  jitter=0.25)
    plt.title("Tagnummer per system — avslorer nummerserier og looper")
    plt.xlabel("Tagnummer")
    plt.ylabel("System")
    plt.legend(title="", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "tag_numbers_per_system.png", dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# 6. Cluster-profil (hvis ml_cluster.py er kjoert)
# ---------------------------------------------------------------------------

def plot_cluster_profile(df: pd.DataFrame) -> None:
    if not CLUSTERS_CSV.exists():
        log.info("Fant ikke clusters.csv — kjoer ml_cluster.py for cluster-profil.")
        return

    clusters = pd.read_csv(CLUSTERS_CSV)
    merged = df.merge(clusters[["drawing", "cluster"]], on="drawing", how="inner")
    if merged.empty:
        log.info("Ingen overlapp mellom tags.csv og clusters.csv.")
        return

    top_types = merged["tag_type"].value_counts().head(10).index
    pivot = (
        merged[merged["tag_type"].isin(top_types)]
        .pivot_table(index="cluster", columns="tag_type",
                     aggfunc="size", fill_value=0)
    )
    # Normaliser per cluster slik at store og smaa clustere kan sammenlignes
    share = pivot.div(pivot.sum(axis=1), axis=0)

    plt.figure(figsize=(10, 5))
    sns.heatmap(share, annot=True, fmt=".0%", cmap="mako",
                linewidths=0.5, cbar_kws={"label": "Andel av taggene i clusteret"})
    plt.title("Instrumentprofil per ML-cluster")
    plt.xlabel("Instrumenttype")
    plt.ylabel("Cluster")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "cluster_instrument_profile.png", dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid")

    df = load_tags()
    log.info("Lastet %d tagger fra %s", len(df), TAGS_CSV.relative_to(ROOT))

    plot_category_donut(df)
    plot_category_per_system(df)
    plot_cooccurrence(df)
    plot_drawing_network(df)
    plot_tag_number_strip(df)
    plot_cluster_profile(df)

    print("\n=== NYE VISUALISERINGER " + "=" * 40)
    print(f"Figurer lagret i: {FIG_DIR.relative_to(ROOT)}")
    for name in ["category_donut", "category_per_system", "type_cooccurrence",
                 "drawing_network", "tag_numbers_per_system",
                 "cluster_instrument_profile"]:
        path = FIG_DIR / f"{name}.png"
        status = "OK " if path.exists() else "  -"
        print(f"  [{status}] {name}.png")


if __name__ == "__main__":
    main()