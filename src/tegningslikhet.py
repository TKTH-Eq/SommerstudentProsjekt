"""
src/tegningslikhet.py
=====================================================================
A drop-in panel for the Drawing analysis page: which other drawings resemble
this one, judged by what the symbol model found on them.

Add one line near the bottom of tegningsanalyse.py, inside the block that runs
when a drawing has been analysed:

    from tegningslikhet import similarity_panel
    similarity_panel(choice, RESULTS_DIR, CLASS_INFO)

Anchoring on the current drawing rather than showing a bare matrix is
deliberate. "Which drawings are like this one" is a question you have while
looking at a drawing; "here is a 20×20 similarity grid" is a question nobody
asked. The full grid is still available in the expander for when it is wanted.

Only drawings that have been analysed appear. That is a real limitation and the
panel says so rather than quietly comparing against three sheets.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from analysis.drawing_similarity import (
    cosine_matrix, cluster, distinctive_classes, load_profiles, neighbours,
    to_matrix,
)


def _name(cls: str, class_info: dict) -> str:
    return class_info.get(cls, (cls,))[0]


@st.cache_data(show_spinner=False)
def _profiles(results_dir: str, signature: tuple):
    return load_profiles(results_dir)


def _signature(results_dir: Path) -> tuple:
    return tuple(sorted((p.name, p.stat().st_mtime)
                        for p in Path(results_dir).glob("*_detections.json")))


def similarity_panel(drawing: Path, results_dir: Path, class_info: dict,
                     *, key: str = "sim") -> None:
    """Everything the panel shows, in one call."""
    results_dir = Path(results_dir)
    sig = _signature(results_dir)
    if len(sig) < 2:
        st.caption("Similar drawings: at least two analysed drawings are "
                   "needed. Analyse another and this fills in.")
        return

    profiles = _profiles(str(results_dir), sig)
    stem = drawing.stem
    if stem not in profiles:
        st.caption("This drawing produced no findings, so it cannot be "
                   "compared.")
        return

    st.subheader("Drawings like this one")
    st.caption(f"Compared across {len(profiles)} analysed drawings, by the "
               f"proportion of each component class rather than raw counts — "
               f"so a big sheet does not simply resemble every other big sheet.")

    labels, classes, m = to_matrix(profiles)
    sim = cosine_matrix(m)

    threshold = st.slider("Similarity threshold", 0.50, 0.99, 0.85, 0.01,
                          key=f"{key}_thr",
                          help="Where a group ends. Higher means tighter, "
                               "fewer, more confident groups.")

    near = neighbours(stem, labels, sim, top=8)
    close = [(d, s) for d, s in near if s >= threshold]

    if close:
        st.dataframe(
            pd.DataFrame([{"drawing": d, "similarity": round(s, 3)}
                          for d, s in close]),
            use_container_width=True, hide_index=True)
    else:
        best = near[0] if near else None
        st.info("No drawing reaches the threshold. Either this sheet is "
                "genuinely unlike the others, or the model underperformed on "
                "it — the second is the more common explanation, and worth "
                "checking before concluding the first."
                + (f" Closest is {best[0]} at {best[1]:.2f}." if best else ""))

    dist = distinctive_classes(stem, profiles, top=4)
    if dist:
        st.markdown("**What sets this drawing apart**")
        st.dataframe(
            pd.DataFrame([{"class": _name(c, class_info),
                           "share here": f"{a:.0%}",
                           "share everywhere": f"{b:.0%}",
                           "difference": f"{a - b:+.0%}"}
                          for c, a, b in dist]),
            use_container_width=True, hide_index=True)
        st.caption("Over-representation against the whole analysed set. A "
                   "drawing that is 80 % one class where the set averages 20 % "
                   "is a candidate for its own Model Broker configuration "
                   "rather than the shared one.")

    with st.expander("All groups"):
        groups = cluster(labels, sim, threshold)
        singles = [g[0] for g in groups if len(g) == 1]
        st.caption(f"{len(groups)} groups at threshold {threshold:.2f}, "
                   f"of which {len(singles)} contain a single drawing. "
                   f"Single-linkage: a group is connected by similarity, not "
                   f"clustered around a centre.")
        for i, g in enumerate(groups, 1):
            here = " ←" if stem in g else ""
            st.markdown(f"**Group {i}** ({len(g)}){here}")
            st.write(", ".join(g))

    with st.expander("Full similarity matrix"):
        st.dataframe(
            pd.DataFrame(sim, index=labels, columns=labels).round(2)
              .style.background_gradient(cmap="Blues", vmin=0, vmax=1),
            use_container_width=True)
        st.caption("Cosine similarity of the class-proportion vectors. "
                   "Useful mainly for spotting the block structure — a clear "
                   "block means a family of sheets that can share one "
                   "configuration.")

    with st.expander("Component profile per drawing"):
        rows = []
        for i, lab in enumerate(labels):
            row = {"drawing": lab}
            row.update({_name(c, class_info): int(profiles[lab].get(c, 0))
                        for c in classes})
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)