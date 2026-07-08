"""Central configuration: paths, tag taxonomy, category mapping."""
from __future__ import annotations
from pathlib import Path

# project root = parent of src/
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "raw"
PID_DIR = DATA / "P&ID"
SCD_DIR = DATA / "SCD"
REPORTS = ROOT / "reports"
AI_REPORTS = REPORTS / "ai_explanations"

# Instrument / equipment type codes used on Huldra process + PSD drawings.
# Grouped so we can categorise each tag as input / logic / output / equipment.
INPUTS = {"PT", "TT", "LT", "FT", "PI", "TI", "LI", "FI", "PDI", "PDT", "PDIT",
          "AE", "SI", "ZS", "ZL", "LSH", "LSL", "LSHH", "PSH", "FSH", "PSE"}
LOGIC  = {"PIC", "LIC", "TIC", "FIC", "PY", "LY", "TY", "FY", "HS", "XY"}
OUTPUTS = {"XV", "ZV", "FV", "LV", "PV", "FO", "PSV"}
EQUIPMENT = {"KA", "PA", "VG", "VD"}          # compressor, pump, vessel, drum

ALL_TYPES = INPUTS | LOGIC | OUTPUTS | EQUIPMENT

# tags that indicate a safety / shutdown function (for the safety register)
SAFETY_TYPES = {"XV", "PSV", "LSH", "LSHH", "PSH", "FSH", "HS", "ZS", "ZL"}
SAFETY_SUFFIXES = ("AHH", "ALL", "HH", "LL")  # alarm/trip annotations

CATEGORY_COLORS = {
    "input": "#2d7dd2", "logic": "#f4a259", "output": "#8f2d56",
    "equipment": "#3f8f4f", "other": "#9aa0a6",
}


def categorise(type_code: str) -> str:
    if type_code in INPUTS: return "input"
    if type_code in LOGIC: return "logic"
    if type_code in OUTPUTS: return "output"
    if type_code in EQUIPMENT: return "equipment"
    return "other"