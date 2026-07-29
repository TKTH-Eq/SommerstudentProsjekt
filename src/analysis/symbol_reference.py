"""
src/analysis/symbol_reference.py
=====================================================================
A human picks one clean instance of a symbol. That instance becomes ground
truth for what the symbol is made of, and everything else is measured against it.

Why this exists
---------------
The generator's failure mode was not that it lacked knowledge of valves. It was
that it had no reference: given a region full of primitives it could not tell
"these five curves are the valve" from "this one curve is a pipe elbow". It
picked the elbow and shipped it as a BallValve.

A hand-picked region removes every source of doubt at once:

  * the box is known-good, so a detector error cannot be the explanation
  * everything inside it IS the symbol, so the primitives are ground truth
  * if extraction still returns one curve, the geometry reader is provably
    broken and the detector is exonerated

Three uses follow from one selection:

  diagnosis   sweep the extraction variants and see which reads the symbol
  reference   a profile of the shape vocabulary — how many primitives, of what
              kinds, at what sizes — used to filter noisy regions elsewhere
  pattern     the curves themselves, ready for build_pattern()

What this is NOT
----------------
Not a replacement for Model Broker's own symbol capture, which does the same
job better inside the tool. The contribution is upstream of it: the detector
finds candidates across twenty drawings and clusters them, so an engineer
confirms one cluster instead of hunting one sheet at a time.

Pure functions, no Streamlit.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .broker_config import Curve, extract_region_geometry

# Extraction settings swept when diagnosing a region. Ordered from the setting
# the generator uses by default to the loosest, so the first row that finds the
# symbol tells you how far from the default you had to go.
VARIANTS: tuple[dict, ...] = (
    {"mode": "majority", "pad_px": 8.0},
    {"mode": "majority", "pad_px": 16.0},
    {"mode": "contain", "pad_px": 8.0},
    {"mode": "contain", "pad_px": 0.0},
    {"mode": "intersect", "pad_px": 4.0},
    {"mode": "majority", "pad_px": 8.0, "flip_y": True},
)


@dataclass
class Reference:
    """One hand-confirmed symbol instance."""
    name: str
    dexpi_class: str
    drawing: str
    bbox_px: list[float]
    dpi: int
    settings: dict
    coords: list[list[float]] = field(default_factory=list)
    note: str = ""

    @property
    def curves(self) -> list[Curve]:
        return [Curve(list(c)) for c in self.coords]

    @classmethod
    def from_curves(cls, name: str, dexpi_class: str, drawing: str,
                    bbox_px, dpi: int, settings: dict,
                    curves: list[Curve], note: str = "") -> "Reference":
        return cls(name=name, dexpi_class=dexpi_class, drawing=drawing,
                   bbox_px=[float(v) for v in bbox_px], dpi=int(dpi),
                   settings=dict(settings),
                   coords=[list(c.coords) for c in curves], note=note)


# ------------------------------------------------------------------ diagnosis
def sweep_variants(pdf_path: Path | str, bbox_px, dpi: int,
                   page: int = 0) -> list[dict]:
    """Run every extraction variant on the same region and report the counts.

    The shape of the result is the diagnosis. All zero means the region is not
    where you think it is — check the DPI and the page rotation. Zero for
    "contain" but many for "majority" means the bezier control points were the
    problem, which is the common case and needs no further work: the default
    already handles it.
    """
    rows = []
    for settings in VARIANTS:
        try:
            curves = extract_region_geometry(pdf_path, tuple(bbox_px), dpi,
                                             page=page, **settings)
            err = ""
        except Exception as e:                                  # noqa: BLE001
            curves, err = [], str(e)[:100]
        w, h = _extent(curves)
        rows.append({**settings, "primitives": len(curves),
                     "points": sum(len(c.coords) // 2 for c in curves),
                     "width": round(w, 1), "height": round(h, 1),
                     "error": err})
    return rows


def _extent(curves: list[Curve]) -> tuple[float, float]:
    if not curves:
        return 0.0, 0.0
    xs = [c.coords[i] for c in curves for i in range(0, len(c.coords), 2)]
    ys = [c.coords[i] for c in curves for i in range(1, len(c.coords), 2)]
    return max(xs) - min(xs), max(ys) - min(ys)


# ------------------------------------------------------------------- preview
def render_svg(curves: list[Curve], size: int = 260,
               stroke: str = "#1f2937", background: str = "#ffffff") -> str:
    """Draw the extracted primitives so the result can be compared by eye.

    This is the point of the whole page. A table saying "7 primitives" does not
    tell you whether you extracted a ball valve or seven fragments of a pipe.
    The picture does, immediately.
    """
    if not curves:
        return (f'<svg width="{size}" height="{size}" role="img">'
                f'<rect width="100%" height="100%" fill="{background}"/>'
                f'<text x="50%" y="50%" text-anchor="middle" font-size="13" '
                f'fill="#9ca3af">ingen geometri</text></svg>')

    xs = [c.coords[i] for c in curves for i in range(0, len(c.coords), 2)]
    ys = [c.coords[i] for c in curves for i in range(1, len(c.coords), 2)]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny, 1e-6)
    k = (size - 24) / span
    ox = (size - (maxx - minx) * k) / 2 - minx * k
    oy = (size - (maxy - miny) * k) / 2 + maxy * k     # y flips for screen

    paths = []
    for c in curves:
        pts = [(c.coords[i] * k + ox, oy - c.coords[i + 1] * k)
               for i in range(0, len(c.coords) - 1, 2)]
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
        paths.append(f'<path d="{d}" fill="none" stroke="{stroke}" '
                     f'stroke-width="1.4" stroke-linecap="round"/>')
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'xmlns="http://www.w3.org/2000/svg" role="img">'
            f'<rect width="100%" height="100%" fill="{background}"/>'
            + "".join(paths) + "</svg>")


# ------------------------------------------------------------------- profile
def shape_profile(curves: list[Curve]) -> dict:
    """The shape vocabulary of a symbol: what it is built from, and at what size.

    Deliberately coarse. A fingerprint tight enough to reject a stray pipe
    segment and loose enough to accept the same valve drawn at a slightly
    different scale — precise matching is Model Broker's job, not this one's.
    """
    if not curves:
        return {"n": 0, "points": Counter(), "extent": (0.0, 0.0),
                "seg_len": (0.0, 0.0)}
    w, h = _extent(curves)
    lengths = []
    counts: Counter[int] = Counter()
    for c in curves:
        n = len(c.coords) // 2
        counts[n] += 1
        pts = [(c.coords[i], c.coords[i + 1])
               for i in range(0, len(c.coords) - 1, 2)]
        lengths.append(sum(math.dist(pts[i], pts[i + 1])
                           for i in range(len(pts) - 1)))
    return {"n": len(curves), "points": counts, "extent": (w, h),
            "seg_len": (min(lengths), max(lengths))}


def describe_profile(profile: dict) -> str:
    if not profile["n"]:
        return "tom"
    # points maps point-count -> how many primitives have it, so the tally
    # comes first: "1×15pkt" is one primitive of fifteen points, not fifteen
    # of one. Reversed here once, and it read as a broken extraction.
    pts = ", ".join(f"{c}×{n}pkt" for n, c in
                    sorted(profile["points"].items(), reverse=True)[:4])
    w, h = profile["extent"]
    total = sum(n * c for n, c in profile["points"].items())
    return (f"{profile['n']} primitiver, {total} punkter ({pts}) · "
            f"{w:.1f}×{h:.1f} pt · "
            f"lengder {profile['seg_len'][0]:.1f}–{profile['seg_len'][1]:.1f}")


def filter_by_reference(curves: list[Curve], reference: dict,
                        *, length_slack: float = 2.5,
                        extent_slack: float = 1.6) -> tuple[list[Curve], list[str]]:
    """Keep the primitives in a noisy region that look like the reference symbol.

    Two tests, both derived from the hand-picked instance: a primitive far
    longer than anything in the reference is a pipe passing through, and one
    reaching well beyond the reference's extent is not part of the symbol.

    Returns (kept, reasons) where reasons explains each rejection — the page
    shows them, because a filter that silently drops the symbol is the same bug
    in a new coat.
    """
    if not reference.get("n"):
        return curves, ["ingen referanse — ingen filtrering"]
    max_len = reference["seg_len"][1] * length_slack
    rw, rh = reference["extent"]
    kept, reasons = [], []
    for i, c in enumerate(curves):
        pts = [(c.coords[j], c.coords[j + 1])
               for j in range(0, len(c.coords) - 1, 2)]
        length = sum(math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1))
        w = max(p[0] for p in pts) - min(p[0] for p in pts)
        h = max(p[1] for p in pts) - min(p[1] for p in pts)
        if length > max_len:
            reasons.append(f"#{i}: lengde {length:.1f} > {max_len:.1f} "
                           f"— sannsynligvis rørlinje")
        elif w > rw * extent_slack or h > rh * extent_slack:
            reasons.append(f"#{i}: {w:.1f}×{h:.1f} utenfor symbolets "
                           f"{rw:.1f}×{rh:.1f}")
        else:
            kept.append(c)
    return kept, reasons


# ------------------------------------------------------------------- storage
def save_reference(ref: Reference, folder: Path | str) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in ref.name)
    path = folder / f"{safe}.json"
    path.write_text(json.dumps(asdict(ref), indent=1, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load_references(folder: Path | str) -> list[Reference]:
    folder = Path(folder)
    if not folder.exists():
        return []
    out = []
    for f in sorted(folder.glob("*.json")):
        try:
            out.append(Reference(**json.loads(f.read_text(encoding="utf-8"))))
        except Exception:                                       # noqa: BLE001
            continue
    return out