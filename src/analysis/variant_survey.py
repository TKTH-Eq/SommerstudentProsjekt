"""
src/analysis/variant_survey.py
=====================================================================
How many ways is a check valve drawn across the drawing set, and how many of
them does the configuration already know?

The observation this is built on
--------------------------------
A Model Broker configuration is not one pattern per symbol type. It is a
variant library that grew as new sheets were met. The Huldra configuration
holds fourteen patterns targeting GateValve (1 to 65 primitives, five of them
sharing the name "Gate Valve Closed"), eight for ControlledActuator, three for
CheckValve. When a valve is not recognised on a new sheet, the tool's own
answer is a new variant — Check Valve D — not a repaired old one.

That makes "which compositions exist, and which are covered" the useful
question, and it is answerable: harvest the geometry under every detection,
describe each instance by what it is BUILT FROM, and compare against the same
description computed for the patterns already in the configuration.

Composition, not shape
----------------------
The grouping key is the primitive vocabulary: how many primitives, with how
many points each. A Z drawn as three separate strokes and the same Z drawn as
one four-point polyline are the same picture and a different composition — and
composition is what a Model Broker matcher keys on, so that is the right
granularity. Size and position are deliberately ignored; scale is handled by
the pattern's own tolerance settings, not by having a separate pattern.

Grouping uses an exact key, because authored patterns are clean. Matching a
harvested group against an existing pattern uses a distance with slack,
because extraction is not: one stray primitive should not make a covered
composition look missing.

Depends on the geometry reader working. Confirm that on one symbol in the
reference picker before trusting anything here — a survey built on empty
extractions will confidently report that nothing is covered.

Pure functions, no Streamlit.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .broker_config import (
    Curve, extract_regions, page_primitive_count, pattern_catalogue,
)
from .symbol_reference import shape_profile


@dataclass
class Instance:
    """One detected symbol whose geometry was successfully read."""
    drawing: str
    cls: str
    dexpi: str
    conf: float
    bbox: list[float]
    dpi: int
    curves: list[Curve] = field(default_factory=list)
    profile: dict = field(default_factory=dict)
    fingerprint: dict = field(default_factory=dict)
    fill: float = 0.0                  # extracted extent / detection box

    def as_candidate(self) -> dict:
        return {"profile": self.profile, "fingerprint": self.fingerprint}


@dataclass
class Composition:
    """A group of instances built from the same primitive vocabulary."""
    dexpi: str
    key: str
    instances: list[Instance]
    covered_by: str | None = None
    distance: float = 1.0

    @property
    def n(self) -> int:
        return len(self.instances)

    @property
    def drawings(self) -> list[str]:
        return sorted({i.drawing for i in self.instances})

    @property
    def fill(self) -> float:
        """Median fill across members — one clipped instance should not
        condemn a composition, nor one good one rescue it."""
        vals = sorted(i.fill for i in self.instances)
        return vals[len(vals) // 2] if vals else 0.0

    @property
    def representative(self) -> Instance:
        """Highest confidence — all members share the composition anyway."""
        return max(self.instances, key=lambda i: i.conf)


# ------------------------------------------------- profiles of what exists
def pattern_curves(definition: dict) -> list[Curve]:
    """Curve matchers as Curve objects. Text matchers carry no coordinates and
    are counted separately by pattern_profiles()."""
    out = []
    for m in (definition.get("matchers") or {}).values():
        if m.get("type") == "curve" and m.get("coords"):
            out.append(Curve([float(c) for c in m["coords"]]))
    return out


def pattern_profiles(config: dict, dexpi_classes: set[str]) -> list[dict]:
    """One row per existing Symbol pattern targeting one of the given classes."""
    defs = {k.split("/", 1)[1]: v for k, v in config.items()
            if k.startswith("patternDefinitions/")}
    rows = []
    for r in pattern_catalogue(config):
        if r["type"] != "Symbol":
            continue
        targets = {c.strip() for c in r["dexpi"].split(",") if c.strip()}
        if not targets & dexpi_classes:
            continue
        d = defs.get(r["id"], {})
        curves = pattern_curves(d)
        prof = shape_profile(curves)
        rows.append({"id": r["id"], "name": r["name"], "dexpi": r["dexpi"],
                     "enabled": r["enabled"], "profile": prof,
                     "fingerprint": geometry_fingerprint(curves),
                     "key": composition_key(prof),
                     "curves": len(curves),
                     "text_matchers": sum(
                         1 for m in (d.get("matchers") or {}).values()
                         if m.get("type") == "text"),
                     "terminals": r["terminals"]})
    rows.sort(key=lambda r: (r["dexpi"], r["curves"]))
    return rows


# ------------------------------------------------------------- composition
def composition_key(profile: dict) -> str:
    """Exact vocabulary key: total primitives, then point counts with tallies.

    "5|2x4,3x2" reads as five primitives: four of two points, one of three.
    """
    if not profile.get("n"):
        return "0|"
    parts = ",".join(f"{c}x{p}" for p, c in
                     sorted(profile["points"].items(), reverse=True))
    return f"{profile['n']}|{parts}"


def describe_key(key: str) -> str:
    n, _, parts = key.partition("|")
    if not parts:
        return "tom"
    human = ", ".join(f"{c} med {p} punkter" for c, _, p in
                      (x.partition("x") for x in parts.split(",")))
    return f"{n} primitiver: {human}"


def geometry_fingerprint(curves: list[Curve]) -> dict:
    """A scale-free shape signature, used to separate patterns that share a
    composition but are not the same drawing.

    Needed because composition alone is not enough. In the Huldra
    configuration, Check Valve and Check Valve C are both seventeen two-point
    primitives — composition distance zero — while Check Valve B is thirty-five
    of them plus two four-point curves. The first pair really are near
    duplicates; but the same coincidence could easily arise between two symbols
    that are not, and a survey that called them covered would be wrong.

    Aspect ratio plus the distribution of segment lengths relative to the
    longest. Both invariant to scale and translation, neither invariant to
    shape — which is exactly the discrimination wanted.
    """
    if not curves:
        return {"aspect": 0.0, "quantiles": (0.0, 0.0, 0.0)}
    xs = [c.coords[i] for c in curves for i in range(0, len(c.coords), 2)]
    ys = [c.coords[i] for c in curves for i in range(1, len(c.coords), 2)]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    lengths: list[float] = []
    for c in curves:
        pts = [(c.coords[i], c.coords[i + 1])
               for i in range(0, len(c.coords) - 1, 2)]
        lengths.extend(math.dist(pts[k], pts[k + 1])
                       for k in range(len(pts) - 1))
    if not lengths:
        return {"aspect": (w / h) if h else 0.0, "quantiles": (0.0, 0.0, 0.0)}
    longest = max(lengths) or 1.0
    norm = sorted(v / longest for v in lengths)
    q = tuple(norm[min(int(len(norm) * f), len(norm) - 1)]
              for f in (0.1, 0.5, 0.9))
    return {"aspect": round((w / h) if h else 0.0, 3),
            "quantiles": tuple(round(v, 3) for v in q)}


def fingerprint_distance(a: dict, b: dict) -> float:
    """0 when the two shapes agree, 1 when they do not. Aspect ratio compared
    as a ratio so 2.0 against 2.05 is close and 2.0 against 2.74 is not."""
    aa, ab = a.get("aspect") or 0.0, b.get("aspect") or 0.0
    if aa > 0 and ab > 0:
        aspect_d = 1.0 - min(aa, ab) / max(aa, ab)
    else:
        aspect_d = 1.0 if (aa or ab) else 0.0
    qa, qb = a.get("quantiles") or (0,) * 3, b.get("quantiles") or (0,) * 3
    quant_d = sum(abs(x - y) for x, y in zip(qa, qb)) / 3.0
    return min(1.0, 0.5 * aspect_d + 0.5 * quant_d)


def near_duplicates(patterns: list[dict], threshold: float = 0.05
                    ) -> list[tuple[str, str, float]]:
    """Pairs of existing patterns that are all but identical.

    A by-product of the survey rather than its purpose, but a useful one: a
    library that grew sheet by sheet accumulates redundancy, and two patterns
    competing for the same geometry is worth an engineer's attention.
    """
    out = []
    for i in range(len(patterns)):
        for j in range(i + 1, len(patterns)):
            a, b = patterns[i], patterns[j]
            if a["dexpi"] != b["dexpi"]:
                continue
            d = combined_distance(a, b)
            if d <= threshold:
                out.append((a["name"], b["name"], round(d, 3)))
    return sorted(out, key=lambda t: t[2])


def combined_distance(a: dict, b: dict) -> float:
    """Composition first, shape second. Composition carries more weight because
    it is what a matcher keys on; shape breaks the ties composition cannot."""
    return (0.6 * composition_distance(a["profile"], b["profile"])
            + 0.4 * fingerprint_distance(a.get("fingerprint") or {},
                                         b.get("fingerprint") or {}))


def composition_distance(a: dict, b: dict) -> float:
    """0 when built from the same vocabulary, 1 when nothing is shared.

    Multiset overlap of point counts. Robust to one stray primitive, which is
    the common extraction error, and firmly separates 17 primitives from 37,
    which is the real difference between Check Valve and Check Valve B.
    """
    ca, cb = a.get("points") or Counter(), b.get("points") or Counter()
    if not ca and not cb:
        return 0.0
    if not ca or not cb:
        return 1.0
    shared = sum(min(ca[k], cb.get(k, 0)) for k in ca)
    total = max(sum(ca.values()), sum(cb.values()))
    return 1.0 - (shared / total if total else 0.0)


def nearest_pattern(candidate: dict, patterns: list[dict],
                    max_distance: float = 0.25) -> tuple[str | None, float]:
    """The closest existing pattern, or (None, distance) if none is close enough.

    `candidate` is a dict with "profile" and "fingerprint" — the same shape as a
    row from pattern_profiles(), so patterns can be compared against each other
    as well as against harvested instances.

    A match here means "the configuration knows this composition and roughly
    this shape". It does not mean the pattern WILL fire: coordinates and
    tolerances decide that, and only Model Broker can answer it. Treat a
    covered composition as a reason not to generate a variant yet, not as
    proof that recognition works.
    """
    best_name, best_d = None, 1.0
    for p in patterns:
        d = combined_distance(candidate, p)
        if d < best_d:
            best_name, best_d = p["name"], d
    return (best_name, best_d) if best_d <= max_distance else (None, best_d)


# ---------------------------------------------------------------- harvest
def harvest(sources: list[dict], class_to_dexpi: dict[str, str], *,
            classes: set[str] | None = None,
            min_conf: float = 0.80,
            max_per_class_per_drawing: int = 25,
            settings: dict | None = None,
            progress=None) -> tuple[list[Instance], list[dict], list[dict]]:
    """Read geometry under every qualifying detection across several drawings.

    `sources` is [{"pdf": Path, "detections": [...], "dpi": int}, ...].
    Returns (instances, failures). Failures are kept and reported rather than
    swallowed: a class that produced fifty empty regions is the most important
    thing on the page, because it means the survey below it is meaningless.
    """
    settings = settings or {}
    instances: list[Instance] = []
    failures: list[dict] = []
    skipped: list[dict] = []
    total = sum(len(s.get("detections") or []) for s in sources) or 1
    done = 0

    for src in sources:
        pdf = Path(src["pdf"])
        dpi = int(src.get("dpi", 200))
        if progress:
            progress(done / total, f"{pdf.name} …")

        # Select the detections for this drawing first, then read all their
        # regions in ONE pass over the page. Reading them one at a time
        # re-parsed a three-thousand-primitive sheet once per valve.
        per_class: Counter[str] = Counter()
        chosen: list[dict] = []
        for det in sorted(src.get("detections") or [],
                          key=lambda d: -float(d.get("conf", 0))):
            cls = det.get("cls")
            if not cls or cls not in class_to_dexpi:
                continue
            if classes and cls not in classes:
                continue
            if float(det.get("conf", 0)) < min_conf:
                continue
            if per_class[cls] >= max_per_class_per_drawing:
                continue
            if not det.get("bbox_orig"):
                continue
            per_class[cls] += 1
            chosen.append(det)

        done += len(src.get("detections") or [])
        if not chosen:
            continue

        # A sheet with no vector layer is out of scope, not fifty failures.
        if page_primitive_count(pdf) == 0:
            skipped.append({"drawing": pdf.stem,
                            "detections": len(chosen),
                            "reason": "ingen vektorgeometri på siden — "
                                      "skannet ark"})
            continue

        try:
            batches = extract_regions(
                pdf, [tuple(d["bbox_orig"]) for d in chosen], dpi, **settings)
        except Exception as e:                                  # noqa: BLE001
            failures.extend({"drawing": pdf.stem, "class": d.get("cls"),
                             "reason": f"siden kunne ikke leses: {str(e)[:60]}"}
                            for d in chosen)
            continue

        for det, curves in zip(chosen, batches):
            cls = det["cls"]
            if len(curves) < 2:
                failures.append({"drawing": pdf.stem, "class": cls,
                                 "reason": f"{len(curves)} primitiv(er) lest ut"})
                continue
            prof = shape_profile(curves)
            box = det["bbox_orig"]
            scale = dpi / 72.0
            pad = 2 * settings.get("pad_px", 8.0) / scale
            rw = (box[2] - box[0]) / scale + pad
            rh = (box[3] - box[1]) / scale + pad
            w, h = prof["extent"]
            # Linear fill: how much of the box the geometry spans. A whole
            # symbol nearly fills the box the detector drew round it; an
            # arrowhead read without its Z does not. This separates a partial
            # extraction from a genuinely different drawing convention, which
            # distance to a saved reference cannot do — both look far away.
            fill = math.sqrt(max((w * h) / (rw * rh), 0.0)) if rw and rh else 0.0
            instances.append(Instance(
                drawing=pdf.stem, cls=cls, dexpi=class_to_dexpi[cls],
                conf=float(det.get("conf", 0)),
                bbox=[float(v) for v in box],
                dpi=dpi, curves=curves, profile=prof,
                fingerprint=geometry_fingerprint(curves), fill=round(fill, 3)))

    if progress:
        progress(1.0, "ferdig")
    return instances, failures, skipped


def group_compositions(instances: list[Instance], patterns: list[dict],
                       *, max_distance: float = 0.25,
                       min_instances: int = 1) -> list[Composition]:
    """Group instances by exact composition, then ask which are already covered.

    Groups are sorted uncovered first, then by size: what is missing and common
    is what you want to act on, and it should not be below the fold.
    """
    buckets: dict[tuple[str, str], list[Instance]] = {}
    for inst in instances:
        buckets.setdefault((inst.dexpi, composition_key(inst.profile)),
                           []).append(inst)

    by_class: dict[str, list[dict]] = {}
    for p in patterns:
        for c in (x.strip() for x in p["dexpi"].split(",")):
            by_class.setdefault(c, []).append(p)

    out: list[Composition] = []
    for (dexpi, key), members in buckets.items():
        if len(members) < min_instances:
            continue
        rep = max(members, key=lambda i: i.conf)
        name, dist = nearest_pattern(rep.as_candidate(), by_class.get(dexpi, []),
                                     max_distance)
        out.append(Composition(dexpi=dexpi, key=key, instances=members,
                               covered_by=name, distance=dist))
    out.sort(key=lambda c: (c.covered_by is not None, -c.n))
    return out


def survey(config: dict, sources: list[dict], class_to_dexpi: dict[str, str],
           **kwargs) -> dict:
    """Harvest, group, compare. Everything a page needs in one call."""
    dexpi_classes = set(class_to_dexpi.values())
    patterns = pattern_profiles(config, dexpi_classes)
    instances, failures, skipped = harvest(sources, class_to_dexpi, **{
        k: v for k, v in kwargs.items()
        if k in {"classes", "min_conf", "max_per_class_per_drawing",
                 "settings", "progress"}})
    comps = group_compositions(
        instances, patterns,
        max_distance=kwargs.get("max_distance", 0.25),
        min_instances=kwargs.get("min_instances", 1))
    missing = [c for c in comps if c.covered_by is None]
    return {"patterns": patterns, "instances": instances, "failures": failures,
            "skipped": skipped,
            "compositions": comps, "missing": missing,
            "duplicates": near_duplicates(patterns),
            "coverage": (1 - len(missing) / len(comps)) if comps else 0.0}