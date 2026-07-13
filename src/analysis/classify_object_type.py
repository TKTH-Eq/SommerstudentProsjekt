# src/analysis/classify_object_type.py
"""
ML-eksperiment: kan man predikere HVA slags plantobjekt noe er — instrument,
roer, aktuator, utstyr — kun ut fra HVOR det ligger paa tegningen og hvor
mange ting det er koblet til? Ingen tekst, ingen tag-navn, kun geometri og
grafstruktur fra DEXPI-dataene (dexpi_tags.csv / connections / associations).

Hvorfor dette er interessant: hvis modellen faktisk laerer noe fra ren
posisjon+konnektivitet, bekrefter det at P&ID-er ikke er tilfeldig
plassert — instrumenter, roer og utstyr grupperer seg systematisk i
prosessflyten. Det aapner ogsaa for aa GJETTE objekttype paa tegninger der
tekstuttrekket feiler (skannet PDF uten tekstlag), saa lenge symbolenes
posisjon og koblinger er kjent.

Metodikk — VIKTIG, les foer du stoler paa tallene:
  To CV-strategier sammenlignes bevisst:

  1. GROUPED (leave-one-drawing-out): trener paa noen tegninger, tester paa
     tegninger modellen ALDRI har sett. Dette er den AERLIGE testen — den
     eneste som sier noe om hvordan modellen vil oppfoere seg paa en NY
     tegning dere legger til senere.

  2. STRATIFIED K-fold: blander alle tegninger sammen foer splitting. Gir
     nesten alltid hoyere score, men er MISVISENDE optimistisk her, fordi
     punkter fra samme tegning ligger naer hverandre baade i trenings- og
     testsettet (datalekkasje via layout-mønster spesifikt for den ene
     tegningen). Tas med KUN for aa vise forskjellen — ikke som fasit.

  Begge sammenlignes mot en DUMMY-baseline (gjett alltid mest vanlige
  klasse) — uten den vet vi ikke om modellen faktisk laerer noe, eller bare
  utnytter at "piping" er den vanligste kategorien uansett.

Krever scikit-learn og scipy:  pip install scikit-learn scipy
Kjor fra prosjektroten (etter aa ha kjoert parse_dexpi_data.py foerst,
saa dexpi_tags.csv/connections/associations finnes):
    python -m analysis.classify_object_type
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.spatial import cKDTree
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, classification_report,
                              confusion_matrix, f1_score)
from sklearn.model_selection import GroupKFold, StratifiedKFold, cross_val_predict

ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"

# Slaa sammen de 13 DEXPI-kategoriene til 5 grovere, mer balanserte grupper
GROUP_MAP = {
    "instrument": "instrument", "instrument_loop": "instrument", "signal_generator": "instrument",
    "piping_component": "piping", "piping_segment": "piping", "piping_system": "piping",
    "actuator": "actuator", "actuating_system": "actuator", "actuating_function": "actuator",
    "equipment": "equipment", "nozzle": "equipment",
    "pipe_off_page": "off_page", "signal_off_page": "off_page",
}
FEATURES = ["x_norm", "y_norm", "degree", "n_neighbors_30mm"]


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def build_features(tags: pd.DataFrame, conns: pd.DataFrame, assocs: pd.DataFrame) -> pd.DataFrame:
    df = tags.dropna(subset=["x_mm", "y_mm"]).copy()
    df["group"] = df["category"].map(GROUP_MAP)
    df = df.dropna(subset=["group"])

    # Graf-grad: antall fysiske/signal-koblinger + semantiske relasjoner per objekt
    degree: dict[str, int] = {}
    for edges, cols in ((conns, ("from_id", "to_id")), (assocs, ("source_id", "target_id"))):
        if edges.empty:
            continue
        for _, r in edges.dropna(subset=list(cols)).iterrows():
            degree[r[cols[0]]] = degree.get(r[cols[0]], 0) + 1
            degree[r[cols[1]]] = degree.get(r[cols[1]], 0) + 1
    df["degree"] = df["id"].map(degree).fillna(0)

    # Normaliser posisjon 0-1 INNAD i hver tegning (tegninger har ulik stoerrelse/skala)
    def norm(g: pd.DataFrame) -> pd.DataFrame:
        g = g.copy()
        g["x_norm"] = (g["x_mm"] - g["x_mm"].min()) / (g["x_mm"].max() - g["x_mm"].min() + 1e-9)
        g["y_norm"] = (g["y_mm"] - g["y_mm"].min()) / (g["y_mm"].max() - g["y_mm"].min() + 1e-9)
        return g
    df = df.groupby("drawing", group_keys=False)[df.columns].apply(norm)

    # Lokal tetthet: hvor mange andre objekter innen 30mm (avsloerer klynger som
    # instrumentbobler-med-loop vs. spredte enkeltventiler paa en roerlinje)
    df["n_neighbors_30mm"] = 0
    for _, g in df.groupby("drawing"):
        pts = g[["x_mm", "y_mm"]].values
        counts = cKDTree(pts).query_ball_point(pts, r=30, return_length=True) - 1
        df.loc[g.index, "n_neighbors_30mm"] = counts

    return df


# ---------------------------------------------------------------------------
# Evaluering
# ---------------------------------------------------------------------------

def run_evaluation(df: pd.DataFrame) -> None:
    X = df[FEATURES].to_numpy(dtype=float)
    y = df["group"].astype(str).to_numpy()
    groups = df["drawing"].astype(str).to_numpy()
    n_drawings = df["drawing"].nunique()

    rf = RandomForestClassifier(n_estimators=200, random_state=42, class_weight="balanced")

    print("=== Baseline: gjett alltid mest vanlige klasse ===")
    dummy_pred = DummyClassifier(strategy="most_frequent").fit(X, y).predict(X)
    base_acc = accuracy_score(y, dummy_pred)
    base_f1 = f1_score(y, dummy_pred, average="macro", zero_division=0)
    print(f"Accuracy: {base_acc:.1%}   Macro F1: {base_f1:.1%}\n")

    if n_drawings >= 2:
        print("=== AERLIG TEST: leave-one-drawing-out (GroupKFold) ===")
        n_splits = min(n_drawings, 5)
        gkf = GroupKFold(n_splits=n_splits)
        y_pred_grouped = cross_val_predict(rf, X, y, cv=gkf, groups=groups)
        print(classification_report(y, y_pred_grouped, zero_division=0))
        grouped_acc = accuracy_score(y, y_pred_grouped)
        grouped_f1 = f1_score(y, y_pred_grouped, average="macro")
        print(f"Accuracy: {grouped_acc:.1%}   Macro F1: {grouped_f1:.1%}")
        print(f"(vs. baseline: {base_acc:.1%} / {base_f1:.1%} — "
              f"{'modellen laerer noe reelt' if grouped_f1 > base_f1 else 'IKKE bedre enn aa gjette'})\n")

        plot_confusion(y, y_pred_grouped, sorted(set(y)),
                       "Confusion matrix — leave-one-drawing-out\n(aerlig: testet paa usett tegning)")
    else:
        print("Kun 1 tegning med data — leave-one-drawing-out krever minst 2. "
              "Legg til flere *.DGN.xml for en meningsfull test.\n")
        y_pred_grouped = None

    print("=== Til sammenligning: 5-fold stratifisert CV (tegninger blandes) ===")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_pred_strat = cross_val_predict(rf, X, y, cv=skf)
    strat_acc = accuracy_score(y, y_pred_strat)
    strat_f1 = f1_score(y, y_pred_strat, average="macro")
    print(f"Accuracy: {strat_acc:.1%}   Macro F1: {strat_f1:.1%}")
    if y_pred_grouped is not None:
        print(f"(Legg merke til hvor mye hoyere dette er enn leave-one-drawing-out — "
              f"det er datalekkasje-effekten, ikke ekte generaliseringsevne.)\n")

    # Feature importance paa modell trent paa alt
    rf.fit(X, y)
    print("Feature importance (hva driver modellen mest):")
    for f, imp in sorted(zip(FEATURES, rf.feature_importances_), key=lambda x: -x[1]):
        print(f"  {f:20s} {imp:.3f}")


def plot_confusion(y_true, y_pred, labels, title) -> None:
    cm = confusion_matrix(y_true, y_pred, labels=labels, normalize="true")
    plt.figure(figsize=(7, 6))
    sns.heatmap(cm, annot=True, fmt=".0%", cmap="rocket_r",
                xticklabels=labels, yticklabels=labels,
                cbar_kws={"label": "Andel av ekte klasse"})
    plt.xlabel("Predikert")
    plt.ylabel("Ekte")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "object_type_confusion_matrix.png", dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid")

    tags_path = PROCESSED_DIR / "dexpi_tags.csv"
    if not tags_path.exists():
        print(f"Fant ikke {tags_path.relative_to(ROOT)} — kjoer "
              "'python -m analysis.parse_dexpi_data' foerst.")
        return

    tags = pd.read_csv(tags_path)
    conns = pd.read_csv(PROCESSED_DIR / "dexpi_connections.csv") \
        if (PROCESSED_DIR / "dexpi_connections.csv").exists() else pd.DataFrame()
    assocs = pd.read_csv(PROCESSED_DIR / "dexpi_associations.csv") \
        if (PROCESSED_DIR / "dexpi_associations.csv").exists() else pd.DataFrame()

    df = build_features(tags, conns, assocs)
    print(f"{len(df)} objekter over {df['drawing'].nunique()} tegning(er)\n")
    print(df["group"].value_counts().to_string())
    print()

    run_evaluation(df)
    print(f"\nFigur lagret til: {(FIG_DIR / 'object_type_confusion_matrix.png').relative_to(ROOT)}")


if __name__ == "__main__":
    main()