"""
src/broker_konfig.py
=====================================================================
Streamlit page: see what a Model Broker configuration is made of.

The page exists for one image. A configuration is not one pattern per symbol
— it is a library that grew as new sheets were met, and the Huldra file holds
fourteen patterns for GateValve alone. Stated as a number that is a curiosity.
Rendered as fourteen pictures of nearly the same valve, built from wildly
different primitive counts, it is the argument the Symbol variants page rests
on, and it needs no explanation.

Everything else on this page is a check rather than a finding, so it is
collapsed: coverage against the DEXPI output, structural soundness, near
duplicates, and a comparison against a second exported file. Run them when
something looks wrong; ignore them otherwise.

An earlier version of this page also generated patterns. That moved to Symbol
variants, where a human confirms each composition first, and was removed here
rather than left in — two routes to the same output with only one of them
gated is a way around the gate.

Add to app.py:

    st.Page("broker_konfig.py", title="Model Broker config", icon="⚙️"),
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis.broker_config import (                            # noqa: E402
    compare_configs, coverage_gap, load_config, pattern_catalogue,
    validate_config,
)
from analysis.dexpi_properties import class_inventory, load_items  # noqa: E402
from analysis.symbol_reference import render_svg                # noqa: E402
from analysis.variant_survey import (                           # noqa: E402
    describe_key, near_duplicates, pattern_curves, pattern_profiles,
)

ROOT = Path(__file__).resolve().parents[1]

try:
    from config import BROKER_CONFIG, RAW_DIR                    # noqa: E402
except Exception:                                                # noqa: BLE001
    RAW_DIR = ROOT / "data" / "raw"
    BROKER_CONFIG = (ROOT / "data" / "broker" /
                     "Huldra DEXPI P&ID 2.0_configuration.json")
BROKER_DIR = Path(BROKER_CONFIG).parent

try:
    from ui import page_header                                   # noqa: E402
except Exception:                                                # noqa: BLE001
    def page_header(title, sub="", **_):
        st.title(title)
        if sub:
            st.caption(sub)


@st.cache_data(show_spinner=False)
def _load(path: str, mtime: float):
    return load_config(path)


page_header("Model Broker config",
            "One symbol, many patterns — what the configuration is made of")

# ------------------------------------------------------------------- source
choices = sorted(p for p in BROKER_DIR.glob("*.json")) \
    if BROKER_DIR.exists() else []
if not choices:
    st.error(f"Found no JSON configurations under {BROKER_DIR}.")
    st.stop()
default = next((i for i, p in enumerate(choices)
                if p.name == Path(BROKER_CONFIG).name), 0)
cfg_path = st.selectbox("Configuration", choices, index=default,
                        format_func=lambda p: p.name)
try:
    config = _load(str(cfg_path), cfg_path.stat().st_mtime)
except json.JSONDecodeError as e:
    st.error(f"Could not read the configuration: {e}")
    st.stop()

catalogue = pattern_catalogue(config)
symbols = [r for r in catalogue if r["type"] == "Symbol"]

families: dict[str, list] = {}
for r in symbols:
    for cls in (x.strip() for x in (r["dexpi"] or "—").split(",")):
        families.setdefault(cls, []).append(r)
multi = {k: v for k, v in families.items() if len(v) > 1}

c = st.columns(4)
c[0].metric("Patterns", len(catalogue))
c[1].metric("Symbols", len(symbols))
c[2].metric("Classes with variants", len(multi))
c[3].metric("Largest family",
            max((len(v) for v in families.values()), default=0))

st.caption("Only the symbol patterns are within reach of a symbol detector — "
           "the rest handle text, lines and sheet furniture. Of those, most "
           "classes carry more than one pattern, because the same symbol is "
           "drawn from different primitives on different sheets.")

st.divider()

# ------------------------------------------------------------- the gallery
st.subheader("The same symbol, drawn differently")

order = sorted(families, key=lambda k: (-len(families[k]), k))
pick = st.selectbox("DEXPI class", order,
                    format_func=lambda k: f"{k}  ({len(families[k])})")

profs = pattern_profiles(config, {pick})
defs = {k.split("/", 1)[1]: v for k, v in config.items()
        if k.startswith("patternDefinitions/")}

if not profs:
    st.info("No symbol patterns target this class.")
else:
    st.caption(f"{len(profs)} patterns target `{pick}`. They render as nearly "
               f"the same valve and are built from very different primitive "
               f"counts — which is exactly why a pattern that works on one "
               f"sheet can find nothing on another.")

    per_row = 4
    for start in range(0, len(profs), per_row):
        row = profs[start:start + per_row]
        cols = st.columns(per_row)
        for col, p in zip(cols, row):
            with col:
                curves = pattern_curves(defs.get(p["id"], {}))
                st.markdown(render_svg(curves, size=150),
                            unsafe_allow_html=True)
                dot = "🟢" if p["enabled"] else "⚪"
                st.markdown(f"{dot} **{p['name']}**")
                st.caption(f"{p['curves']} primitives"
                           + (f" · {p['text_matchers']} text"
                              if p["text_matchers"] else "")
                           + f" · {p['terminals']} terminals")
                st.caption(describe_key(p["key"]))

    st.caption("A pattern matches on the primitive vocabulary, not on the "
               "picture. Two of these can look identical and still be "
               "separate patterns.")

st.divider()

# ---------------------------------------------------------------- the checks
st.subheader("Checks")
st.caption("Run these when something looks wrong. None of them needs a model "
           "or geometry extraction.")

problems = validate_config(config)
errors = [p for p in problems if p["severity"] == "error"]
profs_all = pattern_profiles(config, set(families))
dupes = near_duplicates(profs_all)

k = st.columns(3)
k[0].metric("Structural errors", len(errors),
            help="Broken internal references. The delivered configuration has "
                 "zero, so the bar is exact rather than a judgement call.")
k[1].metric("Near-duplicates", len(dupes),
            help="Pairs of patterns that are geometrically all but identical.")
k[2].metric("Disabled patterns", sum(1 for r in catalogue if not r["enabled"]))

if errors:
    st.error("Broken internal references — this file will be rejected on "
             "import, usually with an unhelpful message.")
    st.dataframe(pd.DataFrame(errors), use_container_width=True,
                 hide_index=True)
else:
    st.success("No dangling references: every `order` entry points at the "
               "pattern's own matchers, and every folder reference resolves.")

with st.expander(f"Near-duplicate patterns ({len(dupes)})"):
    st.caption("A library maintained by hand accumulates redundancy. Two "
               "patterns competing for the same geometry is worth knowing "
               "about before a third is added.")
    st.dataframe(pd.DataFrame(dupes, columns=["pattern A", "pattern B",
                                              "distance"]),
                 use_container_width=True, hide_index=True)

with st.expander("Coverage against the DEXPI output"):
    st.caption("Two lists and a set difference: which classes the export "
               "produces with no pattern targeting them, and which patterns "
               "target a class that never appears.")
    src = st.text_input("DEXPI folder", str(RAW_DIR), key="cov_src")
    if Path(src).exists():
        items = load_items(src)
        if items:
            counts = {r["class"]: r["count"] for r in class_inventory(items)}
            gap = coverage_gap(config, counts)
            g = st.columns(3)
            g[0].metric("Covered", len(gap["both"]))
            g[1].metric("No pattern", len(gap["missing"]))
            g[2].metric("Never seen", len(gap["unused"]))
            st.dataframe(pd.DataFrame(
                [{"class": c, "occurrences": counts.get(c, 0)}
                 for c in gap["missing"]]),
                use_container_width=True, hide_index=True)
            st.caption("Not all of these are errors — several come from "
                       "connection and sheet handling rather than from a "
                       "symbol pattern.")
        else:
            st.info("No DEXPI objects found there.")

with st.expander("Compare against another configuration"):
    st.caption("After importing generated variants and exporting again: is "
               "what came back what went in?")
    others = [p for p in choices if p != cfg_path]
    if not others:
        st.info("Only one configuration in the folder.")
    else:
        other = st.selectbox("Compare against", others,
                             format_func=lambda p: p.name, key="diff_pick")
        try:
            d = compare_configs(config,
                                _load(str(other), other.stat().st_mtime))
        except json.JSONDecodeError as e:
            st.error(f"Could not read it: {e}")
            d = None
        if d:
            m = st.columns(4)
            m[0].metric("Added", len(d["added"]))
            m[1].metric("Removed", len(d["removed"]))
            m[2].metric("Changed", len(d["changed"]))
            m[3].metric("Untouched", d["untouched"])
            if d["new_folders"]:
                st.info("New folders: " + ", ".join(d["new_folders"]))
            if d["removed"]:
                st.error("Patterns are missing from the second file. An "
                         "addition should never remove anything.")
                st.dataframe(pd.DataFrame(d["removed"]),
                             use_container_width=True, hide_index=True)
            if d["added"]:
                st.dataframe(pd.DataFrame(d["added"]),
                             use_container_width=True, hide_index=True)
            if not (d["added"] or d["removed"] or d["changed"]):
                st.success("Identical in their patterns.")

st.caption("Read-only. Generating patterns lives on the Symbol variants page, "
           "behind a confirmation step.")