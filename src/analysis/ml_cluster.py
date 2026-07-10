# src/ml_cluster.py
"""
Kjapp ML paa tegningene: grupper PDF-er etter tekstinnhold.

Pipeline:
  1. Trekk ut tekst fra alle lesbare PDF-er under data/raw/
  2. TF-IDF-vektorisering (hver tegning blir en tallvektor)
  3. KMeans-clustering — finn grupper av "like" tegninger
  4. PCA ned til 2D for aa kunne plotte resultatet
  5. Skriv ut de mest karakteristiske ordene per cluster

Krever scikit-learn:  pip install scikit-learn

Kjor fra prosjektroten:  python src/ml_cluster.py
"""

import logging
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

from extraction.pdf_parser import extract_text

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"

MIN_TEXT_CHARS = 200   # hopp over raster-PDF-er uten tekstlag
K_RANGE = range(2, 9)  # antall clustere vi proever


# ---------------------------------------------------------------------------
# 1. Last inn tekst
# ---------------------------------------------------------------------------

def load_corpus() -> pd.DataFrame:
    rows = []
    pdfs = sorted(p for p in RAW_DIR.rglob("*") if p.suffix.lower() == ".pdf")
    log.info("Leser %d PDF-er ...", len(pdfs))

    for pdf in pdfs:
        try:
            text = extract_text(str(pdf))
        except Exception as exc:
            log.warning("Hopper over %s: %s", pdf.name, exc)
            continue
        if len(text) < MIN_TEXT_CHARS:
            continue  # raster/skannet — ingenting aa lage vektor av
        rows.append({
            "drawing": pdf.stem,
            "folder": pdf.parent.relative_to(RAW_DIR).as_posix(),
            "text": text,
        })

    df = pd.DataFrame(rows)
    log.info("%d tegninger har nok tekst til aa vaere med", len(df))
    return df


# ---------------------------------------------------------------------------
# 2-3. Vektoriser og cluster
# ---------------------------------------------------------------------------

def vectorize(texts: pd.Series):
    """TF-IDF: vekter ord hoyt hvis de er vanlige i EN tegning,
    men sjeldne paa tvers av alle tegninger."""
    vectorizer = TfidfVectorizer(
        lowercase=True,
        token_pattern=r"[A-Za-z]{2,}",  # kun ord, ikke tall/tagnummer
        max_df=0.8,    # dropp ord som finnes i naer alle tegninger
        min_df=3,      # dropp ord som finnes i faerre enn 3
        max_features=2000,
    )
    X = vectorizer.fit_transform(texts)
    log.info("TF-IDF-matrise: %d tegninger x %d ord", *X.shape)
    return X, vectorizer


def choose_k(X) -> int:
    """Velg antall clustere med silhouette-score (hoyere = bedre separasjon)."""
    best_k, best_score = 2, -1.0
    for k in K_RANGE:
        labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(X)
        score = silhouette_score(X, labels)
        log.info("  k=%d  silhouette=%.3f", k, score)
        if score > best_score:
            best_k, best_score = k, score
    log.info("Velger k=%d", best_k)
    return best_k


# ---------------------------------------------------------------------------
# 4-5. Visualiser og forklar
# ---------------------------------------------------------------------------

def plot_clusters(df: pd.DataFrame, X) -> None:
    coords = PCA(n_components=2, random_state=42).fit_transform(X.toarray())
    df = df.assign(pc1=coords[:, 0], pc2=coords[:, 1])

    plt.figure(figsize=(11, 7))
    sns.scatterplot(
        data=df, x="pc1", y="pc2",
        hue="cluster", style="folder",
        palette="tab10", s=90,
    )
    plt.title("Tegninger gruppert etter tekstinnhold (TF-IDF + KMeans, PCA-projeksjon)")
    plt.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "ml_clusters.png", dpi=150)
    plt.close()


def top_terms_per_cluster(model: KMeans, vectorizer: TfidfVectorizer, n: int = 8):
    terms = vectorizer.get_feature_names_out()
    print("\nMest karakteristiske ord per cluster:")
    for i, center in enumerate(model.cluster_centers_):
        top = center.argsort()[::-1][:n]
        print(f"  Cluster {i}: " + ", ".join(terms[j] for j in top))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    df = load_corpus()
    if len(df) < 10:
        log.error("For faa tegninger med tekst til aa cluster'e noe fornuftig.")
        return

    X, vectorizer = vectorize(df["text"])
    k = choose_k(X)

    model = KMeans(n_clusters=k, n_init=10, random_state=42)
    df["cluster"] = model.fit_predict(X)

    # Resultater
    out = df[["drawing", "folder", "cluster"]].sort_values(["cluster", "drawing"])
    csv_path = PROCESSED_DIR / "clusters.csv"
    out.to_csv(csv_path, index=False)

    print("\n=== CLUSTER-RESULTAT " + "=" * 42)
    print(f"Tegninger clustret : {len(df)}")
    print(f"Antall clustere    : {k}")
    print(f"CSV lagret til     : {csv_path.relative_to(ROOT)}\n")

    print("Fordeling (cluster x mappe):")
    print(pd.crosstab(df["cluster"], df["folder"]).to_string())

    top_terms_per_cluster(model, vectorizer)

    sns.set_theme(style="whitegrid")
    plot_clusters(df, X)
    print(f"\nFigur lagret i     : {FIG_DIR.relative_to(ROOT)}\\ml_clusters.png")


if __name__ == "__main__":
    main()
