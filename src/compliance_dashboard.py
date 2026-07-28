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
from analysis.rule_catalog import screen_all_extended, CLAUSES, propose_fixes

try:
    from config import DATA
except Exception:                                                  # noqa: BLE001
    DATA = Path(__file__).resolve().parents[1] / "data" / "raw"

_RULE_TITLE = {
    "R1": "Missing relief path", "R2": "Trip without action",
    "R3": "No pressure monitoring", "R8": "Valve without position feedback",
    "R9": "Trip without voting",
    "R10": "Shutdown valve without cause (C&E)",
    "R11": "Trip without effect (C&E)",
    "R12": "C&E references unknown tag",
    "R13": "Relief without pressure monitoring",
    "R14": "Control function without final element",
    "R15": "Lone redundancy leg",
    "R16": "Near-duplicate tags",
}
_SEV_EN = {"høy": "high", "middels": "medium", "lav": "low"}
_SEV_ORDER = ["high", "medium", "low"]
_PROV_BADGE = {"verified": "✓ verified clause",
               "indicative": "~ clause NOT verified",
               "practice": "· no clause — engineering practice"}


@st.cache_resource(show_spinner="Screening every drawing…")
def _findings():
    ce = None
    ce_dir = Path("data/cause_effect")
    if ce_dir.exists():
        try:
            from analysis.cause_effect import load_ce, validate_ce
            from analysis.plant_model import build_plant_model
            pm = build_plant_model(str(DATA))
            ce = validate_ce(load_ce(ce_dir), {o.tag: o for o in pm["objects"]})
        except Exception:                                          # noqa: BLE001
            ce = None
    return screen_all_extended(str(DATA), ce=ce)


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

# ---- proposed actions per finding ------------------------------------------
st.divider()
st.subheader("What to do about it — proposed actions")
st.caption(
    "Proposals for review, never decisions, and never an invented tag: each "
    "action is phrased against the tags the finding already carries. For "
    "PDF-derived findings the extraction check comes FIRST — at a measured "
    "55 % recall, 'we may simply have missed it' is the cheapest and most "
    "often correct hypothesis, and sending an engineer after a design change "
    "that isn't needed is the expensive mistake.")

if len(view):
    _opts = [f"{r['rule']} · {r['drawing']} · {', '.join(r['tags'][:3])}"
             for r in view.to_dict("records")]
    _pick = st.selectbox("Finding", _opts, index=0)
    _row = view.to_dict("records")[_opts.index(_pick)]
    _prov = CLAUSES.get(_row["rule"], {}).get("provenance", "practice")

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown(f"**{_row['title']}**")
        st.write(_row.get("description", ""))
        st.caption(f"Anchor tags: {', '.join(_row['tags'])}")
    with c2:
        st.metric("Clause provenance", _PROV_BADGE.get(_prov, _prov))
        st.caption(_row.get("standard", ""))

    _src = "dexpi" if _row["drawing"] != "(anleggsdekkende)" else "dexpi"
    for _f in propose_fixes(_row, source=_src):
        st.markdown(f"- **{_f['label']}** — {_f['action']}")
    st.caption("Record the outcome under HAZOP → Rule findings, where a "
               "reviewer's disposition is stored per finding.")

with st.expander("Rule catalogue and clause provenance"):
    st.caption(
        "A fabricated clause reference is worse than none — it looks "
        "authoritative and someone acts on it. Every rule therefore declares "
        "where its reference comes from, and `cite()` refuses a rule marked "
        "verified that has no clause and paraphrase. To upgrade a rule, fill "
        "in the clause and paraphrase from the standard text; no code that "
        "performs a check needs to change.")
    st.dataframe(
        [{"rule": r, "topic": c["topic"], "family": c["family"],
          "clause": c["clause"] or "—",
          "provenance": _PROV_BADGE.get(c["provenance"], c["provenance"])}
         for r, c in sorted(CLAUSES.items(), key=lambda kv: int(kv[0][1:]))],
        use_container_width=True, hide_index=True)
