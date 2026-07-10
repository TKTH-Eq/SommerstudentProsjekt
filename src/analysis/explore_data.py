# src/explore_data.py
"""
Utforsk innholdet i data/raw/ etter ny mappestruktur.

Lager en komplett filoversikt (inventar) over alle PDF- og DGN-filer,
proever tekstuttrekk paa PDF-ene, og visualiserer:

  1. Antall filer per mappe og filtype
  2. Stoerrelsesfordeling per mappe
  3. Hvor mye tekst som kan trekkes ut av hver PDF (lesbarhet)

Eksporterer inventaret til data/processed/file_inventory.csv.

Kjor fra prosjektroten:  python src/explore_data.py
"""

import logging
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import fitz  # PyMuPDF

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"


# ---------------------------------------------------------------------------
# Inventar
# ---------------------------------------------------------------------------

def pdf_info(path: Path) -> dict:
    """Aapne PDF-en og hent sider + lengde paa uttrekkbar tekst."""
    try:
        with fitz.open(path) as doc:
            n_pages = len(doc)
            text_len = sum(len(page.get_text()) for page in doc)
        return {"pages": n_pages, "text_chars": text_len, "readable": True}
    except Exception as exc:
        log.warning("Kunne ikke lese %s: %s", path.name, exc)
        return {"pages": None, "text_chars": None, "readable": False}


def build_inventory(raw_dir: Path) -> pd.DataFrame:
    rows = []
    files = sorted(p for p in raw_dir.rglob("*") if p.is_file())
    log.info("Fant %d filer under %s", len(files), raw_dir)

    for f in files:
        ext = f.suffix.lower().lstrip(".")
        row = {
            "name": f.name,
            "folder": f.parent.relative_to(raw_dir).as_posix() or "(rot)",
            "type": ext if ext else "(ingen)",
            "size_kb": round(f.stat().st_size / 1024, 1),
        }
        if ext == "pdf":
            row.update(pdf_info(f))
        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Visualisering
# ---------------------------------------------------------------------------

def plot_counts(df: pd.DataFrame) -> None:
    counts = (
        df.groupby(["folder", "type"]).size().reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    plt.figure(figsize=(10, 6))
    sns.barplot(data=counts, x="n", y="folder", hue="type", palette="viridis")
    plt.title("Antall filer per mappe og filtype")
    plt.xlabel("Antall filer")
    plt.ylabel("")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "file_counts.png", dpi=150)
    plt.close()


def plot_sizes(df: pd.DataFrame) -> None:
    plt.figure(figsize=(10, 6))
    sns.boxplot(data=df, x="size_kb", y="folder", hue="type", palette="mako")
    plt.title("Filstoerrelser per mappe")
    plt.xlabel("Stoerrelse (kB)")
    plt.ylabel("")
    plt.xscale("log")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "file_sizes.png", dpi=150)
    plt.close()


def plot_pdf_text(df: pd.DataFrame) -> None:
    pdfs = df[(df["type"] == "pdf") & df["text_chars"].notna()]
    if pdfs.empty:
        return
    plt.figure(figsize=(10, 6))
    sns.histplot(data=pdfs, x="text_chars", hue="folder", bins=30, multiple="stack")
    plt.title("Uttrekkbar tekst per PDF (antall tegn)")
    plt.xlabel("Antall tegn tekst")
    plt.ylabel("Antall PDF-er")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "pdf_text_length.png", dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    df = build_inventory(RAW_DIR)
    if df.empty:
        log.error("Fant ingen filer i %s", RAW_DIR)
        return

    csv_path = PROCESSED_DIR / "file_inventory.csv"
    df.to_csv(csv_path, index=False)

    # --- Oppsummering i terminalen -----------------------------------------
    print("\n=== FILINVENTAR " + "=" * 50)
    print(f"Totalt antall filer : {len(df)}")
    print(f"Total stoerrelse    : {df['size_kb'].sum() / 1024:.1f} MB")
    print(f"CSV lagret til      : {csv_path.relative_to(ROOT)}\n")

    print("Per mappe:")
    summary = (
        df.groupby("folder")
        .agg(filer=("name", "count"),
             typer=("type", lambda s: ", ".join(sorted(s.unique()))),
             mb=("size_kb", lambda s: round(s.sum() / 1024, 1)))
        .sort_values("filer", ascending=False)
    )
    print(summary.to_string())

    pdfs = df[df["type"] == "pdf"]
    if not pdfs.empty:
        unreadable = pdfs[pdfs["readable"] == False]  # noqa: E712
        empty_text = pdfs[(pdfs["readable"] == True) & (pdfs["text_chars"] < 100)]  # noqa: E712
        print(f"\nPDF-er totalt       : {len(pdfs)}")
        print(f"  ulesbare          : {len(unreadable)}")
        print(f"  nesten uten tekst : {len(empty_text)}  (< 100 tegn — trolig skannet/raster)")
        if not empty_text.empty:
            print("  Eksempler:", ", ".join(empty_text["name"].head(5)))

    dgns = df[df["type"] == "dgn"]
    if not dgns.empty:
        print(f"\nDGN-filer           : {len(dgns)}  "
              f"({dgns['size_kb'].sum() / 1024:.1f} MB)")
        print("  NB: DGN kan ikke leses direkte i Python — "
              "konverter til DXF (ODA File Converter) eller PDF foerst.")

    # --- Figurer ------------------------------------------------------------
    sns.set_theme(style="whitegrid")
    plot_counts(df)
    plot_sizes(df)
    plot_pdf_text(df)
    print(f"\nFigurer lagret i    : {FIG_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
