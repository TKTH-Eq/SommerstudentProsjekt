# src/analysis/count_fluid_codes.py
"""
Teller opp FluidCodeAssignmentClass over ALLE DEXPI-XML-filer under data/raw,
ikke bare én tegning om gangen (se neqsim_system_report.py for det).

Gir baade en total oversikt (hvilke fluidkoder finnes i hele prosjektet, og
hvor mange rørsegmenter har hver) og en per-tegning-oppdeling, saa man ser om
enkelte tegninger domineres av én fluidtype (som HA24: kun "PL") eller har
flere samtidig (som HO27: PV/VF/PL/DC).

Kjor fra prosjektroten:  python -m analysis.count_fluid_codes
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"


def find_dexpi_files(raw_dir: Path) -> list[Path]:
    """Samme fleksible mønster-matching som dexpi_parser.py — fanger baade
    '..._DGN.xml' og '....DGN.xml' navneformater, uansett store/smaa bokstaver."""
    return sorted(f for f in raw_dir.rglob("*.xml") if "dgn" in f.stem.lower())


def drawing_name(xml_path: Path) -> str:
    return re.sub(r"[._]DGN$", "", xml_path.stem, flags=re.IGNORECASE)


def count_fluid_codes_in_file(xml_path: Path) -> Counter:
    """Antall PipingNetworkSegment-elementer per fluidkode i én fil."""
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as e:
        print(f"  ! Kunne ikke lese {xml_path.name}: {e}")
        return Counter()

    codes = Counter()
    for el in root.iter("PipingNetworkSegment"):
        for ga in el.findall("./GenericAttributes/GenericAttribute"):
            if ga.get("Name") == "FluidCodeAssignmentClass" and ga.get("Value"):
                codes[ga.get("Value")] += 1
                break
    return codes


def main() -> None:
    files = find_dexpi_files(RAW_DIR)
    print(f"Fant {len(files)} DEXPI-XML-fil(er) under {RAW_DIR}\n")
    if not files:
        print("Ingen filer funnet — sjekk at DEXPI-XML-ene faktisk ligger under data/raw/.")
        return

    per_drawing: dict[str, Counter] = {}
    total = Counter()

    for f in files:
        codes = count_fluid_codes_in_file(f)
        name = drawing_name(f)
        per_drawing[name] = codes
        total.update(codes)
        if codes:
            top = ", ".join(f"{c}×{n}" for c, n in codes.most_common())
            print(f"  {name:35s} {top}")
        else:
            print(f"  {name:35s} (ingen fluidkoder funnet)")

    print(f"\n=== TOTALT over alle {len(files)} tegninger ===")
    for code, n in total.most_common():
        print(f"  {code:6s} {n:4d} rørsegmenter")
    print(f"  {'SUM':6s} {sum(total.values()):4d}")

    # --- Lagre som CSV: én rad per (tegning, fluidkode) ---
    rows = [{"drawing": d, "fluid_code": c, "n_segments": n}
            for d, codes in per_drawing.items() for c, n in codes.items()]
    df = pd.DataFrame(rows)
    if not df.empty:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        out_csv = PROCESSED_DIR / "fluid_codes_all_drawings.csv"
        df.to_csv(out_csv, index=False)
        print(f"\nCSV lagret til: {out_csv.relative_to(ROOT)}")

        # --- To figurer: total fordeling + per tegning ---
        FIG_DIR.mkdir(parents=True, exist_ok=True)
        sns.set_theme(style="whitegrid")

        fig, axes = plt.subplots(1, 2, figsize=(14, max(5, len(per_drawing) * 0.35)))

        total_series = pd.Series(total).sort_values(ascending=False)
        axes[0].barh(total_series.index, total_series.values, color="#16233A")
        axes[0].invert_yaxis()
        axes[0].set_xlabel("Number of piping segments (all drawings)")
        axes[0].set_title("Fluid codes across the project")

        pivot = df.pivot_table(index="drawing", columns="fluid_code",
                               values="n_segments", fill_value=0)
        pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
        pivot.plot(kind="barh", stacked=True, ax=axes[1], colormap="viridis", width=0.8)
        axes[1].invert_yaxis()
        axes[1].set_xlabel("Number of piping segments")
        axes[1].set_title("Fluid codes by drawing")
        axes[1].legend(title="", fontsize=8, loc="lower right")

        plt.tight_layout()
        out_fig = FIG_DIR / "fluid_codes_overview.png"
        plt.savefig(out_fig, dpi=150)
        print(f"Figur lagret til: {out_fig.relative_to(ROOT)}")


if __name__ == "__main__":
    main()