"""
src/compliance_dashboard.py — Streamlit page: plant-wide compliance dashboard.

Rolls up the DEXPI structural rule findings (R1–R3, R8–R9) across EVERY drawing
into a manager's view: totals, a system × rule heatmap, severity breakdown, and
an optional Gemini-written 3-sentence "state of the plant" summary grounded in
the numbers. Drill-down table with filters + CSV.

Registered in nav_pages.py. Engine: analysis.rule_screening.screen_all.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()   # GEMINI_API_KEY gate below depends on .env

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import page_header
from analysis.rule_screening import screen_all

try:
    from config import DATA
except Exception:                                                  # noqa: BLE001
    DATA = Path(__file__).resolve().parents[1] / "data" / "raw"

_RULE_TITLE = {
    "R1": "Missing relief path", "R2": "Trip without action",
    "R3": "No pressure monitoring", "R8": "Valve without position feedback",
    "R9": "Trip without voting",
}
_SEV_EN = {"høy": "high", "middels": "medium", "lav": "low"}
_SEV_ORDER = ["high", "medium", "low"]


@st.cache_resource(show_spinner="Screening every drawing…")
def _findings():
    return screen_all(str(DATA))


@st.cache_data(show_spinner="Writing the executive summary…")
def _exec_summary(stats: str) -> str | None:
    if not os.getenv("GEMINI_API_KEY"):
        return None
    try:
        from ai.gemini_client import generate
        prompt = _exec_prompt(stats)
        r = generate(prompt)
        return (r.text or "").strip() or None
    except Exception:                                       # noqa: BLE001
        return None


def _exec_prompt(stats: str) -> str:
    return (
        "You are a process-safety lead. In EXACTLY 3 sentences, summarise the "
        "plant's rule-screening status for a manager, using ONLY the numbers "
        "below — invent nothing, cite no tag that is not given. End by noting "
        "these are screening CANDIDATES that a discipline engineer must confirm, "
        "not confirmed non-conformities.\n\nNUMBERS:\n" + stats)


page_header("Plant compliance dashboard",
            "Every drawing's structural rule findings, rolled up for a manager")
st.caption("Plant-wide roll-up of the DEXPI structural rules (R1–R3 relief / "
           "action / monitoring, R8–R9 valve feedback / trip voting) across all "
           "drawings. Findings are screening CANDIDATES — a discipline engineer "
           "must confirm each before any use beyond screening. Coverage rules "
           "(R4–R7, P&ID↔SCD) live in the per-drawing HAZOP → Rule findings tab.")

rows = _findings()
n_draw = len(list(Path(DATA).rglob("*.DGN.xml")))
if not rows:
    st.info("No findings — or no drawings with a DEXPI model under data/raw.")
    st.stop()

df = pd.DataFrame(rows)
df["sev"] = df["severity"].map(_SEV_EN).fillna(df["severity"])

# ---- headline metrics ------------------------------------------------------
sev_counts = df["sev"].value_counts()
m = st.columns(5)
m[0].metric("Findings", len(df))
m[1].metric("🔴 High", int(sev_counts.get("high", 0)))
m[2].metric("🟠 Medium", int(sev_counts.get("medium", 0)))
m[3].metric("🟡 Low", int(sev_counts.get("low", 0)))
m[4].metric("Drawings flagged", f"{df['drawing'].nunique()}/{n_draw}")

# ---- executive summary (optional, grounded) --------------------------------
top_sys = df["system"].value_counts().head(4)
top_rule = df["rule"].value_counts().idxmax()
stats = (
    f"- {len(df)} findings across {df['drawing'].nunique()} of {n_draw} drawings\n"
    f"- severity: high {int(sev_counts.get('high',0))}, medium "
    f"{int(sev_counts.get('medium',0))}, low {int(sev_counts.get('low',0))}\n"
    f"- systems with most findings: "
    + ", ".join(f"system {s} ({c})" for s, c in top_sys.items()) + "\n"
    f"- most common rule: {top_rule} ({_RULE_TITLE.get(top_rule, top_rule)})")

st.subheader("Executive summary")
if os.getenv("GEMINI_API_KEY"):
    summary = _exec_summary(stats)
    if summary:
        st.info("🧠 " + summary)
        st.caption("Written by Gemini from the aggregate numbers only — no tag "
                   "is cited that the screening did not produce.")
    else:
        st.caption("AI summary unavailable — the numbers below stand on their own.")
else:
    st.caption("Set GEMINI_API_KEY for an AI-written summary. The aggregate "
               "figures below need no key.")
with st.expander("🔍 The numbers fed to the summary (and the prompt)"):
    st.code(stats, language="text")
    st.caption("Prompt template:")
    st.code(_exec_prompt("<numbers above>"), language="text")

# ---- system × rule heatmap -------------------------------------------------
st.subheader("Where the findings are — system × rule")
pivot = pd.crosstab(df["system"], df["rule"])
pivot["Σ"] = pivot.sum(axis=1)
pivot = pivot.sort_values("Σ", ascending=False)
try:
    styled = pivot.style.background_gradient(cmap="Reds", subset=[
        c for c in pivot.columns if c != "Σ"]).format("{:d}")
    st.dataframe(styled, use_container_width=True)
except Exception:                                           # noqa: BLE001
    st.dataframe(pivot, use_container_width=True)
st.caption("Rows = system, columns = rule (R1–R3, R8–R9), Σ = total. Darker = "
           "more findings. Rule key: " + " · ".join(
               f"{k} {v}" for k, v in _RULE_TITLE.items()))

# ---- findings by system, stacked by severity ------------------------------
st.subheader("Findings by system")
bar = (df.assign(n=1).pivot_table(index="system", columns="sev", values="n",
                                  aggfunc="sum", fill_value=0)
       .reindex(columns=_SEV_ORDER, fill_value=0))
st.bar_chart(bar, color=["#c0392b", "#e67e22", "#e0a800"])

# ---- drill-down table + export --------------------------------------------
st.subheader("All findings")
f1, f2, f3 = st.columns(3)
pick_sys = f1.multiselect("System", sorted(df["system"].unique()))
pick_rule = f2.multiselect("Rule", sorted(df["rule"].unique()))
pick_sev = f3.multiselect("Severity", _SEV_ORDER)
view = df.copy()
if pick_sys:
    view = view[view["system"].isin(pick_sys)]
if pick_rule:
    view = view[view["rule"].isin(pick_rule)]
if pick_sev:
    view = view[view["sev"].isin(pick_sev)]

st.dataframe(
    [{"system": r["system"], "drawing": r["drawing"], "rule": r["rule"],
      "severity": r["sev"], "title": r["title"],
      "tags": ", ".join(r["tags"]), "standard": r.get("standard", "")}
     for r in view.to_dict("records")],
    use_container_width=True, hide_index=True)
st.download_button(
    "⬇️ Download the plant findings (CSV)",
    view.drop(columns=["sev"]).to_csv(index=False).encode("utf-8-sig"),
    file_name="plant_compliance_findings.csv", mime="text/csv")
