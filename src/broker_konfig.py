"""
src/broker_konfig.py
=====================================================================
Streamlit page: audit a Model Broker configuration.

What this page is NOT any more: it used to contain a pattern generator. That
was superseded by the Symbol variants page, which does the same thing with a
confirmation step in front of it, and keeping a second route with no human
gate would have been a way to bypass the gate. It was removed rather than
left disabled.

What remains is the part that turned out to be useful without a model, without
geometry extraction and without anything that can go quietly wrong:

  Variant families  the evidence that a configuration is a library rather than
                    one pattern per symbol, which is the observation the whole
                    Symbol variants page rests on
  Coverage          which DEXPI classes have no pattern, and which patterns
                    target a class that never appears. Two lists and a set
                    difference
  Health            dangling references, near-duplicate patterns, and patterns
                    that would match almost anything
  Compare           what changed between two exported configurations, which is
                    how you check that an import did what you expected

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
from analysis.variant_survey import (                           # noqa: E402
    describe_key, near_duplicates, pattern_profiles,
)

ROOT = Path(__file__).resolve().parents[1]

# Paths live in config.py so the project name appears in exactly one place.
try:
    from config import BROKER_CONFIG, RAW_DIR                    # noqa: E402
except Exception:                                                # noqa: BLE001
    RAW_DIR = ROOT / "data" / "raw"
    BROKER_CONFIG = (ROOT / "data" / "broker" /
                     "Huldra DEXPI P&ID 2.0_configuration.json")

try:
    from ui import page_header                                   # noqa: E402
except Exception:                                                # noqa: BLE001
    def page_header(title, sub="", **_):
        st.title(title)
        if sub:
            st.caption(sub)

page_header("Model Broker config",
            "What the configuration contains, what it misses, and what "
            "changed since last time")

cfg_path = st.text_input("Configuration (JSON exported from Model Broker)",
                         str(BROKER_CONFIG))
if not Path(cfg_path).exists():
    st.error("Configuration not found. Export it from Model Broker and point "
             "this field at the file.")
    st.stop()
try:
    config = load_config(cfg_path)
except json.JSONDecodeError as e:
    st.error(f"Could not read the configuration: {e}")
    st.stop()

catalogue = pattern_catalogue(config)
by_type = Counter(r["type"] for r in catalogue)

c = st.columns(5)
c[0].metric("Patterns", len(catalogue))
for i, t in enumerate(["Symbol", "Letter", "ConnectionSegment",
                       "SheetComponent"]):
    c[i + 1].metric(t, by_type.get(t, 0))
st.caption("Only the symbol patterns are within reach of a symbol detector. "
           "Letter, ConnectionSegment and SheetComponent handle text, lines "
           "and sheet furniture — roughly half the configuration is out of "
           "scope for any automated contribution from the outset.")

tab_fam, tab_cov, tab_health, tab_diff = st.tabs(
    ["Variant families", "Coverage", "Health", "Compare"])

# ------------------------------------------------------------ variant families
with tab_fam:
    st.caption("A Model Broker configuration is not one pattern per symbol "
               "type. It is a library that grew as new sheets were met — so "
               "when a valve is not recognised on a new drawing, the tool's "
               "own answer is an added variant, not a repaired one. This tab "
               "is the evidence for that claim.")

    families: dict[str, list] = {}
    for r in catalogue:
        if r["type"] != "Symbol":
            continue
        for cls in (x.strip() for x in (r["dexpi"] or "(no target)").split(",")):
            families.setdefault(cls, []).append(r)

    multi = {k: v for k, v in families.items() if len(v) > 1}
    st.markdown(f"**{len(multi)} classes have more than one pattern.** "
                f"The largest families are where the drawing set varies most.")
    st.dataframe(pd.DataFrame(
        [{"DEXPI class": k, "patterns": len(v),
          "primitives": f"{min(r['primitives'] for r in v)}–"
                        f"{max(r['primitives'] for r in v)}",
          "names": ", ".join(sorted({r["name"] for r in v}))}
         for k, v in sorted(multi.items(), key=lambda x: -len(x[1]))]),
        use_container_width=True, hide_index=True)

    pick = st.selectbox("Inspect a family", sorted(families),
                        index=sorted(families).index("GateValve")
                        if "GateValve" in families else 0)
    profs = pattern_profiles(config, {pick})
    if profs:
        st.dataframe(pd.DataFrame(
            [{"name": p["name"], "enabled": p["enabled"],
              "composition": describe_key(p["key"]),
              "aspect": p["fingerprint"]["aspect"],
              "curves": p["curves"], "text matchers": p["text_matchers"],
              "terminals": p["terminals"]} for p in profs]),
            use_container_width=True, hide_index=True)
        st.caption("Composition is what a matcher keys on: the same valve "
                   "drawn as 17 separate strokes and as 2 polylines are the "
                   "same picture and different patterns.")

# ------------------------------------------------------------------- coverage
with tab_cov:
    st.caption("Two lists and a set difference. No model, no geometry, "
               "nothing that can fail quietly — run this first on any new "
               "configuration.")
    dexpi_src = st.text_input("DEXPI folder", str(RAW_DIR), key="cov_src")
    if not Path(dexpi_src).exists():
        st.info("Point this at the folder holding the DEXPI XML files.")
    else:
        items = load_items(dexpi_src)
        if not items:
            st.info("No DEXPI objects found under that folder.")
        else:
            counts = {r["class"]: r["count"] for r in class_inventory(items)}
            gap = coverage_gap(config, counts)
            g = st.columns(3)
            g[0].metric("Covered and present", len(gap["both"]))
            g[1].metric("Present, no pattern", len(gap["missing"]))
            g[2].metric("Pattern, never present", len(gap["unused"]))

            st.markdown("**Classes in the output with no pattern targeting them**")
            st.caption("Not automatically an error — several come from "
                       "connection and sheet handling rather than from a "
                       "symbol pattern. The ones worth a look are equipment "
                       "and component classes with a high count.")
            st.dataframe(pd.DataFrame(
                [{"class": c, "occurrences": counts.get(c, 0)}
                 for c in gap["missing"]]),
                use_container_width=True, hide_index=True)

            with st.expander("Patterns whose class never appears"):
                st.caption("Either dead weight, or symbols that only occur on "
                           "drawings you have not converted yet. Check before "
                           "deleting anything.")
                st.write(", ".join(gap["unused"]) or "(none)")

# --------------------------------------------------------------------- health
with tab_health:
    problems = validate_config(config)
    errors = [p for p in problems if p["severity"] == "feil"]
    warnings = [p for p in problems if p["severity"] == "advarsel"]

    h = st.columns(2)
    h[0].metric("Structural errors", len(errors))
    h[1].metric("Warnings", len(warnings))

    if errors:
        st.error("Broken internal references. A configuration with these will "
                 "be rejected on import, usually with an unhelpful message.")
        st.dataframe(pd.DataFrame(errors), use_container_width=True,
                     hide_index=True)
    else:
        st.success("No dangling references. Every `order` entry points at the "
                   "pattern's own matchers, every pattern has its metadata, "
                   "and every folder reference resolves.")
        st.caption("This check exists because a generated configuration was "
                   "once rejected with a server error, and the cause — an "
                   "`order` list inherited from another pattern, pointing at "
                   "seven matchers that did not exist — was five lines of "
                   "checking away.")

    profs = pattern_profiles(config, {r["dexpi"].split(",")[0].strip()
                                      for r in catalogue if r["dexpi"]})
    dupes = near_duplicates(profs)
    with st.expander(f"Near-duplicate patterns ({len(dupes)})"):
        st.caption("A library maintained by hand across projects accumulates "
                   "redundancy. Two patterns competing for the same geometry "
                   "is worth knowing about before a third is added.")
        st.dataframe(pd.DataFrame(dupes,
                                  columns=["pattern A", "pattern B", "distance"]),
                     use_container_width=True, hide_index=True)

    with st.expander(f"Warnings ({len(warnings)})"):
        st.caption("Legal but worth a look. Most are single-primitive symbol "
                   "patterns — a Flange defined as one vertical stroke will "
                   "match a great many things, which is deliberate in a "
                   "hand-made pattern and suspicious in a generated one.")
        st.dataframe(pd.DataFrame(warnings), use_container_width=True,
                     hide_index=True)

# -------------------------------------------------------------------- compare
with tab_diff:
    st.caption("After importing generated variants and exporting again, this "
               "answers whether what came back is what went in — and whether "
               "anything else moved.")
    other_path = st.text_input("Compare against", str(BROKER_CONFIG),
                               key="diff_path")
    if not Path(other_path).exists():
        st.info("Point this at a second exported configuration.")
    elif Path(other_path).resolve() == Path(cfg_path).resolve():
        st.info("Same file. Choose a different one to compare.")
    else:
        try:
            other = load_config(other_path)
        except json.JSONDecodeError as e:
            st.error(f"Could not read it: {e}")
            st.stop()
        d = compare_configs(config, other)

        m = st.columns(4)
        m[0].metric("Added", len(d["added"]))
        m[1].metric("Removed", len(d["removed"]))
        m[2].metric("Changed", len(d["changed"]))
        m[3].metric("Untouched", d["untouched"])

        if d["version_before"] != d["version_after"]:
            st.warning(f"Configuration version differs: "
                       f"{d['version_before']} → {d['version_after']}.")
        if d["new_folders"]:
            st.info("New folders: " + ", ".join(d["new_folders"]))
        if d["lost_folders"]:
            st.warning("Folders no longer present: "
                       + ", ".join(d["lost_folders"]))

        if d["added"]:
            st.markdown("**Added**")
            st.dataframe(pd.DataFrame(d["added"]), use_container_width=True,
                         hide_index=True)
        if d["removed"]:
            st.error("Patterns are missing from the second file. An addition "
                     "should never remove anything.")
            st.dataframe(pd.DataFrame(d["removed"]), use_container_width=True,
                         hide_index=True)
        if d["changed"]:
            st.markdown("**Changed**")
            st.dataframe(pd.DataFrame(d["changed"]), use_container_width=True,
                         hide_index=True)
        if not (d["added"] or d["removed"] or d["changed"]):
            st.success("The two configurations are identical in their patterns.")

st.caption("Read-only. This page never writes a configuration — generating "
           "patterns lives on the Symbol variants page, behind a confirmation "
           "step.")