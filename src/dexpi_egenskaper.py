"""
src/dexpi_egenskaper.py
=====================================================================
Streamlit page: read one tag by clicking it apart, then see what the DEXPI
files contain behind it.

Why the decoder is the centre of the page: configuring a tool to read these
tags means knowing what each position holds and which values actually occur.
That is tedious to collect by hand and impossible to guess reliably — but
Model Broker already wrote the answer into the files. It splits every tag
positionally and stores the pieces as part1, part2, part3. Reading them back
gives the segmentation the current configuration APPLIED, not a reconstruction
of it.

So the tag shown here is not decoded by rules this page invented. It is decoded
by rules the configuration used, which is why the page can also show where
those rules went wrong: eight tags in the Huldra set do not survive being
reassembled from their own parts.

The meaning attached to each position is a different matter. That IS inferred,
and it is marked as such — an unverified label that propagates into a Model
Broker configuration is worse than no label.

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
    attribute_coverage, class_inventory, items_with_part, load_items,
    ordered_parts, part_positions, position_values, summary, tag_grammar,
    tag_reconstruction_check, tagged_items,
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

# What each position appears to hold. INFERRED from the data, not read from a
# numbering standard — hence the flag. Same discipline as the fluid-code table
# in line_labels.py, where assumed entries are marked «antatt».
POSITION_MEANING = {
    "part1": ("System number",
              "Process system the object belongs to. Normally matches the "
              "system number in the drawing number of the sheet it sits on.",
              False),
    "part2": ("Function code",
              "First letter is the measured variable, the rest is the "
              "function. Defined on the legend sheet.", False),
    "part3": ("Sequence number",
              "Instrument number within the system. A trailing letter marks "
              "redundant units (A, B).", False),
}

# ISA-5.1 style. A STARTER TABLE: confirm against the project's own legend
# sheet before relying on any of it.
FIRST_LETTER = {
    "A": "Analysis", "B": "Burner, combustion", "C": "User-defined",
    "D": "Density", "E": "Voltage", "F": "Flow", "G": "Gauging, dimension",
    "H": "Hand (manual)", "I": "Current", "J": "Power", "K": "Time, schedule",
    "L": "Level", "M": "Moisture, humidity", "N": "User-defined",
    "O": "User-defined", "P": "Pressure, vacuum", "Q": "Quantity",
    "R": "Radiation", "S": "Speed, frequency", "T": "Temperature",
    "U": "Multivariable", "V": "Vibration", "W": "Weight, force",
    "X": "Unclassified", "Y": "Event, state", "Z": "Position, dimension",
}
LATER_LETTER = {
    "A": "Alarm", "C": "Control", "E": "Sensor, primary element",
    "G": "Glass, viewing device", "H": "High", "I": "Indicate",
    "K": "Control station", "L": "Light, low", "M": "Middle, momentary",
    "O": "Orifice, restriction", "P": "Test point",
    "Q": "Integrate, totalise", "R": "Record", "S": "Switch", "T": "Transmit",
    "U": "Multifunction", "V": "Valve, damper", "W": "Well",
    "X": "Unclassified", "Y": "Relay, compute, convert", "Z": "Driver, actuator",
}


def decode_function_code(code: str) -> list[str]:
    """Letter-by-letter reading of a function code, ISA-5.1 style."""
    out = []
    for i, ch in enumerate(code.upper()):
        if not ch.isalpha():
            continue
        table = FIRST_LETTER if i == 0 else LATER_LETTER
        out.append(f"**{ch}** — {table.get(ch, 'not in the starter table')}")
    return out


@st.cache_data(show_spinner="Reading the DEXPI files …")
def _load(root: str, signature: tuple):
    return load_items(root)


def _signature(root: Path) -> tuple:
    return tuple(sorted((p.name, p.stat().st_mtime)
                        for p in Path(root).rglob("*.xml")))


page_header("DEXPI properties",
            "Click a tag apart — and see what the files hold behind it")

src = st.text_input("DEXPI folder", str(RAW_DIR))
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
c[4].metric("Split into parts", s["with_parts"])

st.divider()

# ============================================================ the decoder
decodable = tagged_items(items)
positions = part_positions(items)

if not decodable:
    st.info("No tags in these files carry a positional split. This page's "
            "decoder needs the part1..partN attributes Model Broker writes — "
            "without them there is nothing to click apart.")
else:
    st.subheader("Tag decoder")
    st.caption("The split shown is the one the configuration applied, read "
               "back out of the files. Click a segment to see what that "
               "position holds and which values occur across the set.")

    tag_index = {f"{it.tag}  ·  {it.component_class or it.element}": it
                 for it in decodable}
    picked = st.selectbox("Tag", list(tag_index),
                          help="Every tagged object that carries a split.")
    item = tag_index[picked]
    parts = ordered_parts(item)

    # One button per segment. Clicking sets which one the panel below explains.
    if "seg" not in st.session_state or st.session_state.get("seg_tag") != item.tag:
        st.session_state["seg"] = parts[0][0]
        st.session_state["seg_tag"] = item.tag

    cols = st.columns(len(parts) + 4)
    for i, (pos, value) in enumerate(parts):
        with cols[i]:
            chosen = st.session_state["seg"] == pos
            if st.button(value, key=f"seg_{pos}", use_container_width=True,
                         type="primary" if chosen else "secondary"):
                st.session_state["seg"] = pos

    sel = st.session_state["seg"]
    sel_value = dict(parts)[sel]
    label, explanation, verified = POSITION_MEANING.get(
        sel, (sel, "No description for this position.", False))
    domain = position_values(items, sel)
    sharing = items_with_part(items, sel, sel_value)

    d1, d2 = st.columns([3, 2])
    with d1:
        st.markdown(f"### {sel_value}")
        st.markdown(f"**{label}** · position `{sel}`")
        st.write(explanation)
        if not verified:
            st.caption("⚠︎ Inferred from the data, not read from the "
                       "project's numbering standard. Confirm before relying "
                       "on it — an unverified label propagates.")
        if sel == "part2" and sel_value.isalpha():
            st.markdown("**Letter by letter** (ISA-5.1 starter table):")
            for line in decode_function_code(sel_value):
                st.markdown(f"- {line}")
        st.markdown(f"**{len(sharing)} objects** share this value, across "
                    f"{len({i.drawing for i in sharing})} drawings.")
        with st.expander(f"Show them ({len(sharing)})"):
            st.dataframe(pd.DataFrame(
                [{"tag": i.tag, "class": i.component_class or i.element,
                  "drawing": i.drawing} for i in sharing]),
                use_container_width=True, hide_index=True)

    with d2:
        st.markdown(f"**Values at `{sel}`** — {len(domain)} distinct")
        st.caption("This is the value domain: what you type into a tool "
                   "configuration, collected for you rather than by scrolling.")
        st.bar_chart(pd.Series(dict(domain.most_common(12))), height=240)

    # ------------------------------------------------ the object behind it
    st.markdown("---")
    o1, o2 = st.columns([2, 3])
    with o1:
        st.markdown(f"### {item.tag}")
        st.write(f"**{item.component_class or item.element}**")
        st.caption(item.class_uri or "no RDL URI")
        st.caption(f"{item.n_connection_points} connection points · "
                   f"drawing {item.drawing}")
        joined = "".join(v for _, v in parts)
        flat = (item.tag or "").replace("-", "").replace(" ", "")
        if joined != flat:
            st.error(f"The parts do not rebuild the tag: `{joined}` vs "
                     f"`{flat}`. Either the split slid, or the tag was "
                     f"rewritten after splitting.")
        else:
            st.success("The parts rebuild the tag exactly.")
    with o2:
        st.markdown("**All attributes on this object**")
        st.dataframe(pd.DataFrame(sorted(item.attributes.items()),
                                  columns=["attribute", "value"]),
                     use_container_width=True, hide_index=True, height=240)

st.divider()

# ================================================== the grammar as a whole
st.subheader("The convention, as applied")
grammar = tag_grammar(items)
if grammar:
    gcols = st.columns(len(grammar))
    for col, row in zip(gcols, grammar):
        with col:
            label = POSITION_MEANING.get(row["position"], (row["position"],))[0]
            st.markdown(f"**{label}**")
            st.caption(f"`{row['position']}` · {row['distinct']} distinct "
                       f"values · {row['count']} objects")
            shape = ("numeric" if row["alphabetic"] == 0 else
                     "alphabetic" if row["numeric"] == 0 else "mixed")
            st.caption(f"Shape: {shape}")
            if row["suspect"]:
                st.warning(f"Odd ones out: {row['suspect']}")
            st.code(row["values"][:70], language=None)
    st.caption("A position holding both numbers and letters means the split "
               "slid for some tags — the minority shape is flagged.")

bad = tag_reconstruction_check(items)
if bad:
    st.error(f"{len(bad)} tags are not reproduced by joining their own parts")
    st.caption("Concatenating the parts must give the tag back. Where it does "
               "not, the configuration read that tag wrongly — these are "
               "found by exact string comparison, with no model involved.")
    st.dataframe(pd.DataFrame(bad), use_container_width=True, hide_index=True)
else:
    st.success("Every tag is exactly reproduced by joining its parts.")

st.divider()

# ================================================== the rest, in expanders
with st.expander("Classes in the output"):
    st.caption("Every class here was produced by some pattern in the current "
               "configuration — the target list a generated pattern must map "
               "onto.")
    st.dataframe(pd.DataFrame(class_inventory(items))[
        ["class", "count", "tagged", "tagged_pct", "elements", "uri"]],
        use_container_width=True, hide_index=True)

with st.expander("Attribute coverage"):
    st.caption("How often each GenericAttribute is populated. High coverage "
               "means the configuration reads that field reliably; a handful "
               "of occurrences is either rare by design or a gap.")
    st.dataframe(pd.DataFrame(attribute_coverage(items))[
        ["attribute", "count", "of_items_pct", "distinct", "samples"]],
        use_container_width=True, hide_index=True)

st.caption("Read-only. This page never writes to the DEXPI files.")