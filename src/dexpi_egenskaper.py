"""
src/dexpi_egenskaper.py
=====================================================================
Streamlit page: what the DEXPI files actually contain — classes, attributes,
and the tag decomposition Model Broker already performed.

Why this page: the Model Broker configuration tells you which patterns exist.
It does not tell you what came out. That answer is in the DEXPI files, and it
is the input to two other things — the target mapping a generated pattern
needs, and the naming convention a tag validator checks against.

The tag grammar section is the one to look at first. Model Broker splits every
tag into positional parts and writes them back as part1..partN. Reading them
gives you the segmentation the current configuration used — including where
it went wrong.

Located in src/ next to app.py and registered by st.navigation there.
Add to app.py:

    st.Page("dexpi_egenskaper.py", title="DEXPI properties", icon="🧬"),
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis.dexpi_properties import (           # noqa: E402
    attribute_coverage, class_inventory, load_items, summary,
    tag_grammar, tag_reconstruction_check,
)

ROOT = Path(__file__).resolve().parents[1]
try:
    from config import RAW_DIR                                     # noqa: E402
except Exception:                                                  # noqa: BLE001
    RAW_DIR = ROOT / "data" / "raw"

try:
    from ui import page_header                                     # noqa: E402
except Exception:                                                  # noqa: BLE001
    def page_header(title, sub="", **_):
        st.title(title)
        if sub:
            st.caption(sub)


@st.cache_data(show_spinner="Reading the DEXPI files …")
def _load(root: str, signature: tuple):
    return load_items(root)


def _signature(root: Path) -> tuple:
    """Cache key: filenames and mtimes, so the load refreshes on change."""
    return tuple(sorted((p.name, p.stat().st_mtime)
                        for p in Path(root).rglob("*.xml")))


page_header("DEXPI properties",
            "What the delivered files contain — and what the configuration "
            "already knows how to read")

src = st.text_input("DEXPI folder", str(RAW_DIR),
                    help="Searched recursively for *.xml.")
root = Path(src)
if not root.exists():
    st.error(f"Found no folder at {root}.")
    st.stop()

sig = _signature(root)
if not sig:
    st.error(f"Found no XML files under {root}.")
    st.stop()

items = _load(str(root), sig)
s = summary(items)

c = st.columns(5)
c[0].metric("Objects", s["items"])
c[1].metric("Drawings", s["drawings"])
c[2].metric("Unique tags", s["tags"])
c[3].metric("Classes", s["classes"])
c[4].metric("Untagged", s["untagged"])
st.caption("«Untagged» objects are real — piping tees, flanged connections and "
           "signal-line functions normally carry no tag. The number matters "
           "because anything untagged is invisible to a tag-based check.")

st.divider()

# ---------------------------------------------------------------- tag grammar
st.subheader("Tag grammar, recovered from the files")
grammar = tag_grammar(items)
if not grammar:
    st.info("No part1..partN attributes found — this configuration does not "
            "split tags, or the files come from a different export.")
else:
    st.caption("Model Broker writes each tag's positional split back as "
               "GenericAttributes. This is therefore the convention the "
               "configuration actually applied, not a reconstruction.")
    st.dataframe(pd.DataFrame(grammar)[
        ["position", "distinct", "count", "numeric", "alphabetic",
         "values", "suspect"]],
        use_container_width=True, hide_index=True)
    flagged = [r for r in grammar if r["suspect"]]
    if flagged:
        st.warning(
            "A position holding both numeric and alphabetic values means the "
            "split slid for some tags. The minority shape is flagged as "
            "«suspect» — check those against the drawing before trusting the "
            "attribute downstream.")

    bad = tag_reconstruction_check(items)
    if bad:
        st.markdown(f"**{len(bad)} tags where the parts do not rebuild the tag**")
        st.caption("Concatenating the parts must reproduce the tag. Where it "
                   "does not, either the split is wrong or the tag was "
                   "rewritten afterwards — both need an engineer.")
        st.dataframe(pd.DataFrame(bad), use_container_width=True,
                     hide_index=True)
    else:
        st.success("Every tag is exactly reproduced by joining its parts.")

st.divider()

# ------------------------------------------------------------------- classes
st.subheader("Classes in the output")
st.caption("Every class here was produced by some pattern in the current "
           "configuration — this is the target list a generated pattern has "
           "to map onto.")
cls_rows = class_inventory(items)
only_tagged = st.checkbox("Only classes that carry tags", value=False)
view = [r for r in cls_rows if r["tagged"]] if only_tagged else cls_rows
st.dataframe(pd.DataFrame(view)[
    ["class", "count", "tagged", "tagged_pct", "elements", "uri"]],
    use_container_width=True, hide_index=True)

st.divider()

# ---------------------------------------------------------------- attributes
st.subheader("Attribute coverage")
st.caption("How often each GenericAttribute is populated. High coverage means "
           "the configuration reads that field reliably; a handful of "
           "occurrences is either rare by design or a gap — the numbers say "
           "which is worth checking, not which is wrong.")
attr_rows = attribute_coverage(items)
min_count = st.slider("Minimum occurrences", 1,
                      max(2, max((r["count"] for r in attr_rows), default=2)),
                      1)
st.dataframe(
    pd.DataFrame([r for r in attr_rows if r["count"] >= min_count])[
        ["attribute", "count", "of_items_pct", "distinct", "samples"]],
    use_container_width=True, hide_index=True)

with st.expander("Browse individual objects"):
    tagged_items = [it for it in items if it.has_tag]
    if not tagged_items:
        st.caption("No tagged objects in this selection.")
    else:
        pick = st.selectbox(
            "Object", range(len(tagged_items)),
            format_func=lambda i: (f"{tagged_items[i].tag} · "
                                   f"{tagged_items[i].component_class or tagged_items[i].element} · "
                                   f"{tagged_items[i].drawing[-18:]}"))
        it = tagged_items[pick]
        st.write(f"**{it.tag}** — {it.component_class or it.element}")
        st.caption(f"{it.class_uri or 'no RDL URI'} · "
                   f"{it.n_connection_points} connection points "
                   f"({', '.join(t or '–' for t in it.connection_types) or 'none'})")
        if it.parts:
            st.write("Parts: " + " | ".join(
                it.parts[k] for k in sorted(
                    it.parts, key=lambda p: int(p[4:]))))
        st.dataframe(
            pd.DataFrame(sorted(it.attributes.items()),
                         columns=["attribute", "value"]),
            use_container_width=True, hide_index=True)

st.caption("Read-only. This page never writes to the DEXPI files.")