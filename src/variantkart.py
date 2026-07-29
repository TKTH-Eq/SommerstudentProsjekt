"""
src/variantkart.py
=====================================================================
Streamlit page: how many ways is each valve drawn across the drawing set, and
how many of those does the Model Broker configuration already know?

The premise, established by reading the configuration rather than assumed:
Model Broker holds a VARIANT LIBRARY, not one pattern per symbol type. Fourteen
patterns target GateValve, three target CheckValve. When a valve is missed on a
new sheet, the tool's own answer is a new variant — Check Valve D — and this
page is about finding out which variants are missing and generating them from a
sibling that works.

Order of operations matters. Confirm on the Reference symbols page that the
geometry reader returns something sensible for one valve you can see with your
own eyes. A survey built on empty extractions will report, with great
confidence, that nothing is covered.

Add to app.py:

    st.Page("variantkart.py", title="Symbol variants", icon="🧩"),
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis.broker_config import (                            # noqa: E402
    build_pattern, donor_pattern, load_config, merge_patterns, new_id,
    validate_config, write_config,
)
from analysis.symbol_reference import (                          # noqa: E402
    load_references, render_svg, shape_profile,
)
from analysis.variant_survey import (                           # noqa: E402
    combined_distance, describe_key, geometry_fingerprint, survey,
)

ROOT = Path(__file__).resolve().parents[1]
GATEVALVE_DIR = ROOT / "gatevalve-ai"
RESULTS_DIR = GATEVALVE_DIR / "results"
REF_DIR = ROOT / "data" / "broker" / "references"

try:
    from config import PID_DIR                                  # noqa: E402
except Exception:                                               # noqa: BLE001
    PID_DIR = ROOT / "data" / "raw" / "P&ID"

try:
    from ui import page_header                                  # noqa: E402
except Exception:                                               # noqa: BLE001
    def page_header(title, sub="", **_):
        st.title(title)
        if sub:
            st.caption(sub)

# The gatevalve-ai classes, mapped to the DEXPI classes their patterns target.
CLASS_TO_DEXPI = {
    "gate_open": "GateValve",
    "gate_closed": "GateValve",
    "ball_valve": "BallValve",
    "ball_open": "BallValve",
    "ball_closed": "BallValve",
    "globe_valve": "GlobeValve",
    "check_valve": "CheckValve",
    "butterfly_valve": "ButterflyValve",
    "reducer": "PipeReducer",
}
DISPLAY = {
    "gate_open": "Gate valve, open", "gate_closed": "Gate valve, closed",
    "ball_valve": "Ball valve", "ball_open": "Ball valve, open",
    "ball_closed": "Ball valve, closed", "globe_valve": "Globe valve",
    "check_valve": "Check valve", "butterfly_valve": "Butterfly valve",
    "reducer": "Reducer",
}

page_header("Symbol variants",
            "Which compositions exist on the drawings — and which the "
            "configuration already knows")

# ------------------------------------------------------------------ sources
cfg_path = st.text_input(
    "Reference configuration",
    str(ROOT / "data" / "broker" / "Huldra DEXPI P&ID 2.0_configuration.json"))
if not Path(cfg_path).exists():
    st.error("Configuration not found.")
    st.stop()
config = load_config(cfg_path)


def _sources() -> list[dict]:
    """Every analysed drawing that still has its PDF and its detections."""
    out = []
    for det in sorted(RESULTS_DIR.glob("*_detections.json")):
        stem = det.name[:-len("_detections.json")]
        pdfs = [p for p in Path(PID_DIR).rglob("*")
                if p.suffix.lower() == ".pdf" and p.stem == stem]
        if not pdfs:
            continue
        dpi = 200
        run = RESULTS_DIR / f"{stem}_run.json"
        if run.exists():
            try:
                dpi = int(json.loads(run.read_text(encoding="utf-8"))["dpi"])
            except Exception:                                   # noqa: BLE001
                pass
        try:
            dets = json.loads(det.read_text(encoding="utf-8"))
        except Exception:                                       # noqa: BLE001
            continue
        out.append({"pdf": pdfs[0], "detections": dets, "dpi": dpi})
    return out


sources = _sources()
if not sources:
    st.error("No analysed drawings found. Run some on the Drawing analysis "
             "page first.")
    st.stop()

st.caption(f"{len(sources)} analysed drawings · "
           f"{sum(len(s['detections']) for s in sources)} detections available.")

chosen = st.multiselect(
    "Classes to survey", list(CLASS_TO_DEXPI),
    default=list(CLASS_TO_DEXPI),
    format_func=lambda c: DISPLAY.get(c, c))

o1, o2, o3, o4 = st.columns(4)
with o1:
    min_conf = st.slider("Minimum confidence", 0.5, 1.0, 0.90, 0.05)
with o2:
    max_per = st.number_input("Max per class per drawing", 3, 60, 25)
with o3:
    min_inst = st.number_input("Minimum instances", 1, 20, 3,
                               help="A real drawing convention recurs. A "
                                    "composition seen once or twice is more "
                                    "often a false detection or a partial "
                                    "extraction than a variant worth adding.")
with o4:
    max_dist = st.slider("Coverage distance", 0.05, 0.60, 0.25, 0.05,
                         help="How close a harvested composition must be to an "
                              "existing pattern to count as covered. Lower is "
                              "stricter and reports more as missing.")

if st.button("Run survey", type="primary", disabled=not chosen):
    bar = st.progress(0.0, "Reading geometry …")
    result = survey(config, sources, CLASS_TO_DEXPI,
                    classes=set(chosen), min_conf=min_conf,
                    max_per_class_per_drawing=int(max_per),
                    max_distance=max_dist, min_instances=int(min_inst),
                    progress=lambda f, t: bar.progress(min(f, 1.0), t))
    bar.empty()
    st.session_state["survey"] = result

result = st.session_state.get("survey")
if not result:
    st.stop()

comps = result["compositions"]
missing = result["missing"]
failures = result["failures"]

# Saved references are the only ground truth on this page: a human looked at
# the drawing and confirmed "this is a check valve". Everything else is the
# detector's class label taken on trust. Measuring each composition against
# them is what separates a real drawing variant from a false detection.
refs = load_references(REF_DIR)
ref_by_class: dict[str, list[dict]] = {}
for r in refs:
    curves = r.curves
    ref_by_class.setdefault(r.dexpi_class, []).append(
        {"name": r.name, "profile": shape_profile(curves),
         "fingerprint": geometry_fingerprint(curves)})


def _ref_match(comp) -> tuple[str | None, float]:
    """Closest saved reference for this composition, if any exist."""
    candidates = ref_by_class.get(comp.dexpi) or []
    if not candidates:
        return None, 1.0
    rep = comp.representative
    cand = {"profile": rep.profile, "fingerprint": rep.fingerprint}
    best = min(candidates, key=lambda r: combined_distance(cand, r))
    return best["name"], combined_distance(cand, best)

m = st.columns(5)
m[0].metric("Instances read", len(result["instances"]))
m[1].metric("Compositions", len(comps))
m[2].metric("Covered", len(comps) - len(missing))
m[3].metric("Missing", len(missing))
m[4].metric("Coverage", f"{result['coverage']:.0%}")

skipped = result.get("skipped") or []
if skipped:
    st.info(f"{len(skipped)} drawings have no vector layer and were skipped "
            f"({sum(s['detections'] for s in skipped)} detections). Scanned "
            f"sheets cannot yield geometry, and counting them as failures "
            f"would make the numbers below look far worse than they are.")
    with st.expander("Drawings without a vector layer"):
        st.dataframe(pd.DataFrame(skipped), use_container_width=True,
                     hide_index=True)

if failures:
    share = len(failures) / max(len(failures) + len(result["instances"]), 1)
    msg = (f"{len(failures)} regions produced no usable geometry "
           f"({share:.0%} of everything attempted).")
    if share > 0.5:
        st.error(msg + " More than half failed — the survey below is not "
                       "trustworthy. Fix the geometry reader first on the "
                       "Reference symbols page.")
    else:
        st.warning(msg)
    with st.expander("Failures"):
        st.dataframe(pd.DataFrame(failures).groupby(
            ["drawing", "class", "reason"]).size().reset_index(name="count"),
            use_container_width=True, hide_index=True)

st.caption("A covered composition means the configuration knows this primitive "
           "vocabulary and roughly this shape. It does NOT prove the pattern "
           "fires — coordinates and tolerances decide that, and only Model "
           "Broker can answer it. Treat coverage as a reason not to generate "
           "a variant yet.")
st.warning("**This page does not judge what a symbol is.** Every composition "
           "below comes from a region the detector labelled with that class. "
           "False detections and partial extractions arrive here as "
           "compositions and look exactly like real variants. A long list for "
           "one class measures noise in the pipeline, not richness in the "
           "drawings — the pictures are the review, and a saved reference is "
           "the only thing on this page that a human has confirmed.")

# ----------------------------------------------------------- per class view
st.divider()
by_class: dict[str, list] = {}
for c in comps:
    by_class.setdefault(c.dexpi, []).append(c)

for dexpi in sorted(by_class):
    existing = [p for p in result["patterns"]
                if dexpi in {x.strip() for x in p["dexpi"].split(",")}]
    gaps = [c for c in by_class[dexpi] if c.covered_by is None]
    st.subheader(f"{dexpi} — {len(by_class[dexpi])} compositions found, "
                 f"{len(existing)} patterns exist"
                 + (f", {len(gaps)} missing" if gaps else ""))

    with st.expander(f"Existing patterns ({len(existing)})"):
        st.dataframe(pd.DataFrame([
            {"name": p["name"], "enabled": p["enabled"],
             "composition": describe_key(p["key"]),
             "aspect": p["fingerprint"]["aspect"],
             "text matchers": p["text_matchers"],
             "terminals": p["terminals"]}
            for p in existing]), use_container_width=True, hide_index=True)

    for comp in by_class[dexpi]:
        rep = comp.representative
        c1, c2 = st.columns([1, 3])
        with c1:
            st.markdown(render_svg(rep.curves, size=150),
                        unsafe_allow_html=True)
        with c2:
            if comp.covered_by:
                st.markdown(f"**Covered** by `{comp.covered_by}` "
                            f"(distance {comp.distance:.2f})")
            else:
                st.markdown(f"**Not covered** — nearest pattern is "
                            f"{comp.distance:.2f} away")
            st.caption(describe_key(comp.key))
            st.caption(f"{comp.n} instances across {len(comp.drawings)} "
                       f"drawings: {', '.join(comp.drawings[:4])}"
                       + (" …" if len(comp.drawings) > 4 else ""))
            fill_note = ("fills the detection box" if comp.fill >= 0.6 else
                         "partial — geometry covers only part of the box"
                         if comp.fill < 0.45 else "fills most of the box")
            st.caption(f"Fill {comp.fill:.2f} — {fill_note}")
            rname, rdist = _ref_match(comp)
            if rname and rdist <= 0.35:
                st.caption(f"Same composition as saved reference `{rname}`")

# --------------------------------------------------------------- generation
st.divider()
st.subheader("Generate the missing variants")

if not missing:
    st.success("Every composition found is already covered. If a symbol is "
               "still not recognised in Model Broker, the problem is "
               "coordinates or tolerances on an existing pattern, not a "
               "missing variant.")
    st.stop()

st.caption("Each variant inherits its tolerances and its typed terminals from "
           "an existing sibling in the same class — a pattern that demonstrably "
           "works elsewhere. Only the geometry is new. Everything ships "
           "disabled, in its own folder.")

f1, f2 = st.columns(2)
with f1:
    min_fill = st.slider("Minimum fill of the detection box", 0.0, 1.0, 0.45,
                         0.05,
                         help="How much of the box the geometry spans. A whole "
                              "symbol nearly fills the box the detector drew "
                              "round it; an arrowhead read without the rest of "
                              "the valve does not. This is the filter that "
                              "separates a partial extraction from a genuinely "
                              "different drawing convention.")
with f2:
    min_drawings = st.number_input("Minimum drawings", 1, 10, 1,
                                   help="A composition seen on several sheets "
                                        "is a convention. One seen on a single "
                                        "sheet may still be real — but it is "
                                        "the weaker case.")

pool = [i for i in range(len(missing))
        if missing[i].fill >= min_fill
        and len(missing[i].drawings) >= int(min_drawings)]
st.caption(f"{len(pool)} of {len(missing)} compositions pass. Distance to a "
           f"saved reference is deliberately NOT used here: a reference from "
           f"one drawing cannot vouch for a composition from a sheet that "
           f"draws the symbol differently, which is precisely what this page "
           f"is looking for.")

labels = []
for c in missing:
    rname, rdist = _ref_match(c)
    tag = f" · ≈ {rname}" if rname and rdist <= 0.35 else ""
    labels.append(f"{c.dexpi} · {describe_key(c.key)} · {c.n} instances "
                  f"· fill {c.fill:.2f}{tag}")

picked = st.multiselect(
    "Compositions to generate", pool, default=[],
    format_func=lambda i: labels[i],
    help="Nothing is preselected on purpose. Look at each picture above and "
         "pick the ones that are actually the symbol.")
if not picked:
    st.info("Pick at least one composition. Choosing them deliberately is the "
            "point — a generated pattern that matches the wrong thing is worse "
            "than a missing one.")

if st.button("Generate variants", type="primary", disabled=not picked):
    folder_id = new_id()
    patterns, report = [], []
    for i in picked:
        comp = missing[i]
        rep = comp.representative
        donor = donor_pattern(config, comp.dexpi)
        if donor is None:
            report.append({"class": comp.dexpi, "status": "no donor",
                           "detail": "no existing symbol pattern to inherit "
                                     "tolerances and terminals from"})
            continue
        letters = "BCDEFGHIJK"
        n_existing = sum(1 for p in result["patterns"]
                         if comp.dexpi in p["dexpi"])
        name = f"{comp.dexpi} {letters[min(n_existing, len(letters) - 1)]} (AI)"
        patterns.append(build_pattern(name, rep.curves, comp.dexpi,
                                      donor=donor, folder_id=folder_id,
                                      enabled=False))
        report.append({"class": comp.dexpi, "status": "generated",
                       "name": name, "donor": donor.get("name", ""),
                       "primitives": len(rep.curves),
                       "instances": comp.n, "drawings": len(comp.drawings),
                       "from": rep.drawing, "conf": round(rep.conf, 3)})

    merged = merge_patterns(config, patterns, folder_id, "AI-varianter")
    errors = [p for p in validate_config(merged) if p["severity"] == "feil"]

    st.dataframe(pd.DataFrame(report), use_container_width=True,
                 hide_index=True)

    if errors:
        st.error(f"{len(errors)} structural errors — not written.")
        st.dataframe(pd.DataFrame(errors), use_container_width=True,
                     hide_index=True)
    elif patterns:
        out = ROOT / "data" / "broker" / \
            f"{Path(cfg_path).stem}__varianter.json"
        write_config(merged, out)
        st.success(f"{len(patterns)} variants written to `{out}`")
        st.download_button(
            "Download configuration",
            data=json.dumps(merged, indent=1, ensure_ascii=False).encode("utf-8"),
            file_name=out.name, mime="application/json")
        st.caption("Import into Model Broker, open the AI-varianter folder, "
                   "and switch them on one at a time. Rerun the drawing after "
                   "each — that is how you find out whether the variant was "
                   "the answer.")

# ------------------------------------------------------------- hygiene note
if result.get("duplicates"):
    with st.expander(f"{len(result['duplicates'])} near-duplicate patterns "
                     f"already in the configuration"):
        st.caption("A by-product, not the point — but a library that grew "
                   "sheet by sheet accumulates redundancy, and two patterns "
                   "competing for the same geometry is worth knowing about "
                   "before adding a third.")
        st.dataframe(pd.DataFrame(result["duplicates"],
                                  columns=["pattern A", "pattern B",
                                           "distance"]),
                     use_container_width=True, hide_index=True)