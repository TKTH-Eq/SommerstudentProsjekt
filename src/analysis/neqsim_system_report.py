# src/analysis/neqsim_system_report.py
"""
Plant-wide link between extracted P&ID topology and NeqSim — the direct
answer to the key question "Can extracted system information be connected
to simulation/calculation tools such as NeqSim?"

Unlike simulate_component_failure.py, which computes the consequence of ONE
failure point at a time, this script takes a WHOLE drawing: it finds every
fluid code that actually occurs (FluidCodeAssignmentClass from DEXPI), how
many piping segments and objects each covers, and computes basic physical
properties (density, Z-factor, viscosity) per fluid type via NeqSim.

This is what shows the DEXPI to NeqSim link scaling to a whole system rather
than a single scenario.

CAVEATS (the same as fluid_lookup.py):
  - Fluid code to composition is ASSUMED, not confirmed against the "P&ID
    Legend Huldra" sheets. See FLUID_PRESETS in neqsim_tools/fluid_lookup.py.
  - Pressure and temperature are NOT in the DEXPI data. Representative
    example values are used here (override with --pressure/--temperature).
  - The DEXPI export covers 17 of 141 drawings, so this script can only run
    on that subset.

Run from the project root:
    python -m analysis.neqsim_system_report <drawing> [--pressure 60] [--temperature 20]

Example:
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
# 1. Every fluid code plus its segment information, from DEXPI
# ---------------------------------------------------------------------------

def find_xml_for_drawing(drawing: str) -> Path | None:
    for f in RAW_DIR.rglob("*.xml"):
        stem = f.stem.replace("_DGN", "").replace(".DGN", "")
        if drawing in stem or stem in drawing:
            return f
    return None


def summarize_fluid_codes(xml_path: Path) -> pd.DataFrame:
    """One row per unique fluid code: segment count, diameters, line numbers."""
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
# 2. NeqSim: physical properties per fluid type
# ---------------------------------------------------------------------------

def compute_neqsim_properties(fluid_codes: list[str], pressure_bara: float,
                              temperature_c: float) -> pd.DataFrame:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from neqsim_tools.fluid_lookup import get_preset, build_neqsim_fluid
        from neqsim.thermo import TPflash
    except ImportError as e:
        print(f"(NeqSim/fluid_lookup unavailable here: {e})")
        return pd.DataFrame()
    except Exception as e:
        print(f"(NeqSim/JVM error: {e})")
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
# Plotting
# ---------------------------------------------------------------------------

def plot_summary(summary: pd.DataFrame, props: pd.DataFrame, drawing: str) -> None:
    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(1, 2 if not props.empty else 1, figsize=(13 if not props.empty else 7, 5))
    if props.empty:
        axes = [axes]

    axes[0].barh(summary["fluid_code"], summary["n_segments"], color="#16233A")
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Piping segments")
    axes[0].set_title(f"Fluid codes in {drawing}")

    if not props.empty and props["density_kg_m3"].notna().any():
        axes[1].bar(props["fluid_code"], props["density_kg_m3"], color="#E8640F")
        axes[1].set_ylabel("Density [kg/m3]")
        axes[1].set_title("NeqSim density per fluid type")

    plt.tight_layout()
    out = FIG_DIR / f"neqsim_system_report_{drawing}.png"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"\nFigure saved: {out.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("drawing")
    ap.add_argument("--pressure", type=float, default=60.0,
                    help="Representative pressure in bara (DEXPI has no real operating pressure)")
    ap.add_argument("--temperature", type=float, default=20.0,
                    help="Representative temperature in C")
    args = ap.parse_args()

    xml_path = find_xml_for_drawing(args.drawing)
    if xml_path is None:
        print(f"Found no DEXPI XML for '{args.drawing}' under {RAW_DIR}")
        return

    summary = summarize_fluid_codes(xml_path)
    if summary.empty:
        print("No fluid codes found in this drawing.")
        return

    print(f"=== Fluid overview: {args.drawing} ===\n")
    print(summary.to_string(index=False))

    print(f"\n=== NeqSim properties at {args.pressure} bara / {args.temperature} C ===")
    print("(representative values — DEXPI has no real operating conditions, see docstring)\n")
    props = compute_neqsim_properties(summary["fluid_code"].tolist(), args.pressure, args.temperature)
    if not props.empty:
        print(props.to_string(index=False))
        FIG_DIR.mkdir(parents=True, exist_ok=True)
        plot_summary(summary, props, args.drawing)
    else:
        plot_summary(summary, pd.DataFrame(), args.drawing)


if __name__ == "__main__":
    main()