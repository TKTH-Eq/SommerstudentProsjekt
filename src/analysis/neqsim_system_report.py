# src/analysis/neqsim_system_report.py
"""
Systemomfattende kobling mellom ekstrahert P&ID-topologi og NeqSim —
svarer direkte paa noekkelspoersmaalet "Can extracted system information
be connected to simulation/calculation tools such as NeqSim?"

I motsetning til simulate_component_failure.py (som kun beregner
konsekvens for ETT feilpunkt om gangen), tar dette scriptet for seg en
HEL tegning: finner alle unike fluidkoder som faktisk forekommer
(FluidCodeAssignmentClass fra DEXPI), hvor mange roersegmenter/objekter
hver av dem dekker, og beregner grunnleggende fysiske egenskaper
(tetthet, Z-faktor, viskositet) for hver fluidtype via NeqSim.

Dette viser at koblingen DEXPI -> NeqSim skalerer til et helt system,
ikke bare et enkelt scenario — det sterkeste svaret vi har paa
noekkelspoersmaalet saa langt.

FORBEHOLD (samme som fluid_lookup.py):
  - Fluidkode -> sammensetning er ANTATT, ikke bekreftet mot "P&ID
    Legend Huldra". Sjekk FLUID_PRESETS i neqsim_tools/fluid_lookup.py.
  - Trykk/temperatur er IKKE i DEXPI-dataen. Brukes her som representative
    eksempelverdier (kan overstyres med --pressure/--temperature).
  - DEXPI-eksporten dekker kun 17 av 141 tegninger (~12%) — dette scriptet
    kan derfor kun kjoeres paa den delmengden.

Kjor fra prosjektroten:
    python -m analysis.neqsim_system_report <tegningsnavn> [--pressure 60] [--temperature 20]

Eksempel:
    python -m analysis.neqsim_system_report C025-V-HO27-P-_E-001-01
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
FIG_DIR = ROOT / "reports" / "figures"
PROCESSED_DIR = ROOT / "data" / "processed"


# ---------------------------------------------------------------------------
# 1. Hent ut ALLE fluidkoder + tilhoerende segmentinfo fra DEXPI
# ---------------------------------------------------------------------------

def find_xml_for_drawing(drawing: str) -> Path | None:
    for f in RAW_DIR.rglob("*.xml"):
        stem = f.stem.replace("_DGN", "").replace(".DGN", "")
        if drawing in stem or stem in drawing:
            return f
    return None


def summarize_fluid_codes(xml_path: Path) -> pd.DataFrame:
    """Ett rad per unike fluidkode: antall segmenter, roerdiametre, linjenumre."""
    root = ET.parse(xml_path).getroot()

    def attr(el, name):
        for ga in el.findall("./GenericAttributes/GenericAttribute"):
            if ga.get("Name") == name:
                return ga.get("Value")
        return None

    rows = []
    for el in root.iter("PipingNetworkSegment"):
        code = attr(el, "FluidCodeAssignmentClass")
        if not code:
            continue
        rows.append({
            "fluid_code": code,
            "line_number": attr(el, "LineNumberAssignmentClass") or el.get("TagName"),
            "diameter_in": attr(el, "NominalDiameterNumericalValueRepresentationAssignmentClass"),
            "piping_class": attr(el, "PipingClassCodeAssignmentClass"),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    summary = df.groupby("fluid_code").agg(
        n_segments=("line_number", "count"),
        n_unique_lines=("line_number", "nunique"),
        typical_diameter=("diameter_in", lambda s: s.mode().iloc[0] if not s.mode().empty else None),
        piping_classes=("piping_class", lambda s: ", ".join(sorted(s.dropna().unique()))),
    ).reset_index().sort_values("n_segments", ascending=False)
    return summary


# ---------------------------------------------------------------------------
# 2. NeqSim: fysiske egenskaper per fluidtype
# ---------------------------------------------------------------------------

def compute_neqsim_properties(fluid_codes: list[str], pressure_bara: float,
                              temperature_c: float) -> pd.DataFrame:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from neqsim_tools.fluid_lookup import get_preset, build_neqsim_fluid
        from neqsim.thermo import TPflash
    except ImportError as e:
        print(f"(NeqSim/fluid_lookup ikke tilgjengelig her: {e})")
        return pd.DataFrame()
    except Exception as e:
        print(f"(NeqSim/JVM-feil: {e})")
        return pd.DataFrame()

    rows = []
    for code in fluid_codes:
        preset = get_preset(code)
        f = build_neqsim_fluid(preset)
        f.setTemperature(temperature_c, "C")
        f.setPressure(pressure_bara, "bara")
        try:
            TPflash(f)
            f.initProperties()
            n_phases = f.getNumberOfPhases()
            density = f.getPhase(0).getDensity("kg/m3")
            try:
                z = f.getPhase(0).getZ()
            except Exception:
                z = None
            rows.append({
                "fluid_code": code, "matched": preset["matched"],
                "description": preset["description"], "n_phases": n_phases,
                "density_kg_m3": round(density, 1),
                "z_factor": round(z, 3) if z is not None else None,
                "molar_mass_g_mol": round(f.getMolarMass("gr/mol"), 2),
            })
        except Exception as e:
            rows.append({"fluid_code": code, "matched": preset["matched"],
                        "description": preset["description"], "n_phases": None,
                        "density_kg_m3": None, "z_factor": None,
                        "molar_mass_g_mol": None, "error": str(e)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Visualisering
# ---------------------------------------------------------------------------

def plot_summary(summary: pd.DataFrame, props: pd.DataFrame, drawing: str) -> None:
    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(1, 2 if not props.empty else 1, figsize=(13 if not props.empty else 7, 5))
    if props.empty:
        axes = [axes]

    axes[0].barh(summary["fluid_code"], summary["n_segments"], color="#16233A")
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Antall roersegmenter")
    axes[0].set_title(f"Fluidkoder i {drawing}")

    if not props.empty and props["density_kg_m3"].notna().any():
        axes[1].bar(props["fluid_code"], props["density_kg_m3"], color="#E8640F")
        axes[1].set_ylabel("Tetthet [kg/m³]")
        axes[1].set_title("NeqSim-beregnet tetthet per fluidtype")

    plt.tight_layout()
    out = FIG_DIR / f"neqsim_system_report_{drawing}.png"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"\nFigur lagret: {out.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("drawing")
    ap.add_argument("--pressure", type=float, default=60.0,
                    help="Representativt trykk i bara (DEXPI har ikke ekte driftstrykk)")
    ap.add_argument("--temperature", type=float, default=20.0,
                    help="Representativ temperatur i C")
    args = ap.parse_args()

    xml_path = find_xml_for_drawing(args.drawing)
    if xml_path is None:
        print(f"Fant ingen DEXPI-XML for '{args.drawing}' under {RAW_DIR}")
        return

    summary = summarize_fluid_codes(xml_path)
    if summary.empty:
        print("Ingen fluidkoder funnet i denne tegningen.")
        return

    print(f"=== Fluidoversikt: {args.drawing} ===\n")
    print(summary.to_string(index=False))

    print(f"\n=== NeqSim-egenskaper ved {args.pressure} bara / {args.temperature}°C ===")
    print("(representative verdier — DEXPI har ikke ekte driftsbetingelser, se docstring)\n")
    props = compute_neqsim_properties(summary["fluid_code"].tolist(), args.pressure, args.temperature)
    if not props.empty:
        print(props.to_string(index=False))
        FIG_DIR.mkdir(parents=True, exist_ok=True)
        plot_summary(summary, props, args.drawing)
    else:
        plot_summary(summary, pd.DataFrame(), args.drawing)


if __name__ == "__main__":
    main()