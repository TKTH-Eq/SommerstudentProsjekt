"""
src/analysis/broker_config.py
=====================================================================
Read a Semantum Model Broker configuration, and generate an ADDITION to it
from what the symbol model found.

The shape of the problem
------------------------
A Model Broker symbol pattern is not a bounding box. It is a set of vector
primitives with control-point coordinates in a local frame, plus terminals
(connection points with position and cardinality), plus a mapping to a DEXPI
class, plus about fifteen tolerance parameters:

    "matchers": {"<id>": {"type": "curve",
                          "coords": [-22.68, 18.42, ...],
                          "metric": "CONTROL_POINTS"}, ...}

gatevalve-ai produces boxes on pixels. You cannot turn a box into geometry,
because a box has none. So the detector is used as a REGION SELECTOR: it says
where a symbol is and which class it belongs to, and the geometry is then read
out of the PDF's own vector layer — the same source the configuration was
authored from ("source": "pdf" on every pattern in the reference file).

That reframe is the whole module. The model's job is to find and GROUP the
occurrences; the geometry comes from the drawing, exactly as it does when an
engineer picks a symbol in the Model Broker UI.

Human in the loop, using the tool's own affordances
---------------------------------------------------
Generated patterns are written into their own folder, given their own colour,
and set enabled=False below a confidence threshold. The engineer opens Model
Broker, sees a folder of greyed-out proposals, and switches them on as they
check them. No new review UI is needed, and a wrong proposal cannot fire.

Fixed after the first Model Broker import failed
------------------------------------------------
The first generated file was rejected with a server error. Cause: "order" was
copied from the donor pattern, so it referred to seven matcher IDs that did not
exist in the new pattern. Three things changed:

  * "order" is derived from the pattern's own matchers, never inherited
  * terminals are inherited from the donor with their TYPES intact
    (valveLabel_to, sizeLabel_to, valveActuator are contracts with other
    patterns — without them the object comes out untagged)
  * validate_config() checks internal references before anything is written

Untested path
-------------
extract_region_geometry() has NOT been run against a real vector P&ID — the
PDFs available while writing this were rasterised copies with no vector layer.
The DEXPI and configuration functions are tested; treat the geometry function
as a first draft and check the first pattern it produces by hand.

Pure functions, no Streamlit.
"""
from __future__ import annotations

import json
import math
import random
import string
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

# Model Broker keys are nanoid-style: 21 chars from this alphabet.
_NANO_ALPHABET = string.ascii_letters + string.digits + "_-"
_NANO_LEN = 21

GENERATED_FOLDER_NAME = "AI-forslag"
GENERATED_COLOR = "#8b8b8b"          # grey: visibly different from hand-made


def new_id(rng: random.Random | None = None) -> str:
    r = rng or random
    return "".join(r.choice(_NANO_ALPHABET) for _ in range(_NANO_LEN))


# ------------------------------------------------------------ reading config
def load_config(path: Path | str) -> dict:
    """The configuration as Model Broker exports it: a flat dict whose keys
    are 'collection/id' strings plus a few scalars."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _collection(config: dict, name: str) -> dict[str, dict]:
    prefix = name + "/"
    return {k[len(prefix):]: v for k, v in config.items() if k.startswith(prefix)}


def pattern_catalogue(config: dict) -> list[dict]:
    """One row per pattern: name, type, folder, enabled, and the classes it
    targets in each export format."""
    meta = _collection(config, "patternMeta")
    defs = _collection(config, "patternDefinitions")
    folders = _collection(config, "patternFolders")
    rows = []
    for pid, m in meta.items():
        d = defs.get(pid, {})
        targets = m.get("targets") or d.get("targets") or {}
        rows.append({
            "id": pid,
            "name": m.get("name") or d.get("name") or "(uten navn)",
            "type": m.get("type") or d.get("type") or "",
            "folder": (folders.get(m.get("folder") or "", {}) or {}).get("name", ""),
            "enabled": bool(m.get("enabled", d.get("enabled", False))),
            "dexpi": ", ".join(targets.get("Dexpi2", [])),
            "proteus": ", ".join(targets.get("Proteus", [])),
            "primitives": len(d.get("matchers") or {}),
            "terminals": len(d.get("terminals") or []),
        })
    rows.sort(key=lambda r: (r["type"], r["name"]))
    return rows


def covered_dexpi_classes(config: dict) -> set[str]:
    """Every DEXPI class some pattern in the configuration targets."""
    out: set[str] = set()
    for m in _collection(config, "patternMeta").values():
        out.update((m.get("targets") or {}).get("Dexpi2", []))
    for d in _collection(config, "patternDefinitions").values():
        out.update((d.get("targets") or {}).get("Dexpi2", []))
    return {c for c in out if c}


def coverage_gap(config: dict, dexpi_class_counts: dict[str, int]) -> dict:
    """Compare the configuration against what the DEXPI output actually contains.

    Two directions, both informative:
      missing  : classes in the DEXPI files that no pattern targets. Either
                 they came from a different mechanism (connections, sheet
                 components) or the configuration has drifted from the output.
      unused   : patterns targeting classes that never appear. Dead weight,
                 or symbols that exist on drawings you have not run yet.
    """
    covered = covered_dexpi_classes(config)
    present = {c for c in dexpi_class_counts if c}
    return {
        "missing": sorted(present - covered,
                          key=lambda c: -dexpi_class_counts.get(c, 0)),
        "unused": sorted(covered - present),
        "both": sorted(present & covered,
                       key=lambda c: -dexpi_class_counts.get(c, 0)),
    }


def donor_pattern(config: dict, dexpi_class: str | None = None,
                  pattern_type: str = "Symbol") -> dict | None:
    """An existing pattern to copy tolerance settings from.

    Never invent tolerance values. Prefer a pattern targeting the same DEXPI
    class, then any symbol pattern with a reasonable number of primitives.
    """
    defs = _collection(config, "patternDefinitions")
    meta = _collection(config, "patternMeta")
    candidates = []
    for pid, d in defs.items():
        m = meta.get(pid, {})
        if (m.get("type") or d.get("type")) != pattern_type:
            continue
        targets = (m.get("targets") or d.get("targets") or {}).get("Dexpi2", [])
        score = (2 if dexpi_class and dexpi_class in targets else 0) \
            + (1 if 3 <= len(d.get("matchers") or {}) <= 40 else 0)
        candidates.append((score, pid, d))
    if not candidates:
        return None
    candidates.sort(key=lambda t: -t[0])
    return candidates[0][2]


# Fields copied verbatim from the donor. Everything not listed is either
# geometry (generated) or identity (fresh).
#
# "order" must NOT be here. It is a list of matcher IDs giving the sequence
# Model Broker tries primitives in, and it refers to the pattern's OWN
# matchers. Copying it from a donor leaves seven dangling references that no
# longer resolve — which is exactly what made the first generated file fail on
# import with a server error. It is identity, not tolerance, and build_pattern
# now derives it from the matchers it just created.
_TOLERANCE_FIELDS = (
    "allowedRotations", "tolerance", "textTolerance", "scalable",
    "minScale", "maxScale", "displacements", "attachmentDistanceTolerance",
    "attachmentAngleTolerance", "splitMinLength", "branchAttachmentTolerance",
    "perpendicularGapTolerance", "jumpGapRadius", "dashGapLength",
    "minGapLength", "splitLines", "createBranches", "branchTargets",
    "connectionSplitType", "considerInserts", "considerRenderingOrder",
    "routeConnectednessTolerance", "attachmentDistanceToleranceUnit",
    "minScaleExpression", "maxScaleExpression", "scaleExpression",
    "toleranceExpression", "textToleranceExpression",
    "attachmentDistanceToleranceExpression", "attachmentAngleToleranceExpression",
    "splitMinLengthExpression", "branchAttachmentToleranceExpression",
    "perpendicularGapToleranceExpression", "jumpGapRadiusExpression",
    "dashGapLengthExpression", "minGapLengthExpression",
    "routeConnectednessToleranceExpression",
)


# --------------------------------------------------------- geometry from PDF
@dataclass
class Curve:
    """One polyline primitive in local (symbol-centred) coordinates."""
    coords: list[float]

    def as_matcher(self, rng: random.Random | None = None) -> tuple[str, dict]:
        cid = new_id(rng)
        return cid, {"type": "curve", "id": cid,
                     "coords": [round(c, 4) for c in self.coords],
                     "metric": "CONTROL_POINTS",
                     "freeXPlacement": False, "freeYPlacement": False,
                     "includeInRoute": False, "constraints": []}


def extract_region_geometry(pdf_path: Path | str, bbox_px: tuple[float, float, float, float],
                            dpi: int, page: int = 0,
                            pad_px: float = 2.0) -> list[Curve]:
    """Vector primitives inside a pixel bounding box, in local coordinates.

    bbox_px is in the pixel space the detector worked in (i.e. the PDF
    rendered at `dpi`), matching the "bbox_orig" field gatevalve-ai writes.
    PDF user space is 72 units per inch, so the conversion is dpi/72.

    Returns polylines translated so the region centre is the origin — the
    frame Model Broker patterns use.

    UNTESTED against a real vector P&ID. If the first generated pattern does
    not match anything, check the y-axis direction first: PDF user space has
    y increasing upwards, raster pixels have y increasing downwards, and this
    function flips accordingly. If your renderer disagrees, that is the knob.
    """
    import pdfplumber

    scale = dpi / 72.0
    x0, y0, x1, y1 = (v / scale for v in bbox_px)

    with pdfplumber.open(str(pdf_path)) as pdf:
        pg = pdf.pages[page]
        height = pg.height
        # raster y grows down; pdfplumber's top/bottom also grow down, so the
        # box needs no flip here — only the emitted coordinates do
        pad = pad_px / scale
        region = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        cx = (region[0] + region[2]) / 2
        cy = (region[1] + region[3]) / 2

        curves: list[Curve] = []
        for prim in list(pg.lines) + list(pg.curves) + list(pg.rects):
            pts = prim.get("pts")
            if pts:
                seq = [(float(px), float(py)) for px, py in pts]
                # pdfplumber's pts are in bottom-up space for curves
                seq = [(px, height - py) for px, py in seq]
            elif "x0" in prim and "top" in prim:
                if prim.get("width", 0) or prim.get("height", 0):
                    seq = [(float(prim["x0"]), float(prim["top"])),
                           (float(prim["x1"]), float(prim["bottom"]))]
                else:
                    continue
            else:
                continue

            if not all(region[0] <= px <= region[2] and region[1] <= py <= region[3]
                       for px, py in seq):
                continue
            flat: list[float] = []
            for px, py in seq:
                flat.extend([px - cx, cy - py])       # local frame, y up
            if len(flat) >= 4:
                curves.append(Curve(flat))
    return curves


def geometry_signature(curves: list[Curve], quantum: float = 0.5) -> str:
    """A rotation-naive fingerprint used to check that occurrences the model
    grouped together really are the same symbol.

    Quantising to half a point absorbs rendering jitter without collapsing
    genuinely different symbols. Sorting makes it order-independent, since
    two instances of the same symbol may list their primitives differently.
    """
    rounded = sorted(
        tuple(round(c / quantum) for c in cur.coords) for cur in curves)
    return "|".join(",".join(str(v) for v in seq) for seq in rounded)


def cluster_by_geometry(occurrences: list[tuple[str, list[Curve]]]
                        ) -> dict[str, list[str]]:
    """Group occurrence keys by identical geometry signature.

    If the detector put two different symbols in one class, this splits them
    back apart — a free consistency check before anything is written.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for key, curves in occurrences:
        groups[geometry_signature(curves)].append(key)
    return dict(groups)


def infer_terminals(curves: list[Curve], tol: float = 1.5) -> list[dict]:
    """Propose connection points at the extreme endpoints of the geometry.

    Rough by construction: it takes the endpoint furthest left, right, top and
    bottom and offers those as terminals. An engineer moving a proposed
    terminal is much cheaper than placing one from nothing, which is the whole
    bargain here — do not present these as correct.
    """
    if not curves:
        return []
    pts: list[tuple[float, float]] = []
    for cur in curves:
        cs = cur.coords
        pts.append((cs[0], cs[1]))
        pts.append((cs[-2], cs[-1]))

    picks = []
    for key in (lambda p: p[0], lambda p: -p[0], lambda p: p[1], lambda p: -p[1]):
        cand = min(pts, key=key)
        if not any(math.dist(cand, q) < tol for q in picks):
            picks.append(cand)

    return [{"id": new_id(), "type": "",
             "position": {"type": "point", "x": round(x, 4), "y": round(y, 4),
                          "allowGapConnection": False},
             "connections": {"min": 1, "max": 1},
             "constrainMax": True, "required": False}
            for x, y in picks]


def _extent(points: list[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return max(xs) - min(xs), max(ys) - min(ys)


def inherit_terminals(donor: dict, curves: list[Curve], *,
                      fit_untyped: bool = True,
                      rng: random.Random | None = None
                      ) -> tuple[list[dict], list[str]]:
    """Take the donor's terminals rather than inventing new ones.

    Terminals are not free-form. A valve in this configuration carries five:
    two untyped process points, plus valveLabel_to, sizeLabel_to and
    valveActuator. Those three names are CONTRACTS with other patterns — they
    are how the tag and size labels get attached, and therefore how part1..partN
    ever get filled. A generated pattern with two anonymous terminals loads
    fine and then produces an object with no tag, which is worse than failing.

    So: copy every terminal from the donor with fresh IDs, keeping types,
    cardinalities and positions. Optionally rescale the UNTYPED ones so their
    spread matches the geometry that was actually extracted — a variant symbol
    of a different size needs its process points moved, while the label
    terminals stay where the configuration expects them.

    Returns (terminals, warnings). Warnings are for the report, not exceptions:
    a suspicious scale factor is worth showing an engineer, not worth refusing.
    """
    rng = rng or random
    donor_terms = donor.get("terminals") or []
    warnings: list[str] = []
    if not donor_terms:
        return infer_terminals(curves), ["donoren har ingen terminaler å arve"]

    def _pos(t):
        p = t.get("position") or {}
        return float(p.get("x", 0.0)), float(p.get("y", 0.0))

    untyped = [t for t in donor_terms if not (t.get("type") or "")]
    scale_x = scale_y = 1.0
    if fit_untyped and curves and untyped:
        pts: list[tuple[float, float]] = []
        for cur in curves:
            cs = cur.coords
            pts.extend((cs[i], cs[i + 1]) for i in range(0, len(cs) - 1, 2))
        gx, gy = _extent(pts)
        dx, dy = _extent([_pos(t) for t in untyped])
        if dx > 1e-6 and gx > 1e-6:
            scale_x = gx / dx
        if dy > 1e-6 and gy > 1e-6:
            scale_y = gy / dy
        for name, s in (("x", scale_x), ("y", scale_y)):
            if s and not 0.6 <= s <= 1.7:
                warnings.append(
                    f"terminalene skalert {s:.2f}× i {name} — det genererte "
                    f"symbolet har vesentlig annen størrelse enn donoren "
                    f"«{donor.get('name')}»; kontroller plasseringen")

    out: list[dict] = []
    for t in donor_terms:
        new = json.loads(json.dumps(t))            # deep copy, no shared state
        new["id"] = new_id(rng)
        if fit_untyped and not (t.get("type") or ""):
            p = new.get("position") or {}
            if "x" in p:
                p["x"] = round(float(p["x"]) * scale_x, 4)
            if "y" in p:
                p["y"] = round(float(p["y"]) * scale_y, 4)
        out.append(new)
    return out, warnings


# ------------------------------------------------------------ building patterns
def build_pattern(name: str, curves: list[Curve], dexpi_class: str, *,
                  donor: dict, folder_id: str, enabled: bool,
                  terminals: list[dict] | None = None,
                  color: str = GENERATED_COLOR,
                  rng: random.Random | None = None) -> tuple[str, dict, dict]:
    """One (id, patternDefinition, patternMeta) triple ready to merge.

    Tolerances come from the donor, never from imagination. Identity, geometry
    and targets are new.
    """
    pid = new_id(rng)
    matchers = dict(c.as_matcher(rng) for c in curves)
    if terminals is None:
        terminals, _ = inherit_terminals(donor, curves, rng=rng)
    definition = {k: donor[k] for k in _TOLERANCE_FIELDS if k in donor}
    definition.update({
        "name": name,
        "source": "pdf",
        "color": color,
        "type": "Symbol",
        "matchers": matchers,
        # own matcher IDs, never the donor's — see the note on _TOLERANCE_FIELDS
        "order": [list(matchers)],
        "terminals": terminals,
        "attributes": [],
        "targets": {"Proteus": [dexpi_class], "Dexpi2": [dexpi_class]},
        "enabled": enabled,
        "folder": folder_id,
    })
    meta = {"name": name, "color": color, "enabled": enabled,
            "type": "Symbol", "folder": folder_id,
            "targets": {"Proteus": [dexpi_class], "Dexpi2": [dexpi_class]}}
    return pid, definition, meta


def merge_patterns(config: dict, patterns: list[tuple[str, dict, dict]],
                   folder_id: str, folder_name: str = GENERATED_FOLDER_NAME
                   ) -> dict:
    """A copy of the configuration with the new patterns and their folder added.

    The original is never mutated, and nothing existing is touched: version,
    patternTemplate, targetDefinitions and every hand-made pattern come through
    unchanged. Model Broker should see the file as the same configuration plus
    one folder.
    """
    out = dict(config)
    out[f"patternFolders/{folder_id}"] = {
        "id": folder_id, "name": folder_name, "color": GENERATED_COLOR,
        "icon": "folder-close", "type": "Symbol"}
    for pid, definition, meta in patterns:
        out[f"patternDefinitions/{pid}"] = definition
        out[f"patternMeta/{pid}"] = meta
    return out


def validate_config(config: dict) -> list[dict]:
    """Structural check before export. Run it on every file you write.

    This exists because the first generated configuration was rejected by
    Model Broker with an unhelpful server error, and the cause — an "order"
    list pointing at matcher IDs that did not exist — was a five-line check
    away. A configuration is a graph of internal references; anything that
    dangles is a load failure waiting to happen.

    Each row carries a severity:

      "feil"     — a broken internal reference. The reference configuration
                   from Model Broker has zero of these, so the bar is exact:
                   any file you write should also have zero.
      "advarsel" — legal but worth a look. Calibrated against the reference
                   file, which contains 17 single-primitive symbol patterns
                   (Valve Label, Flange, Fitting …) that work because they are
                   constrained by terminals and text attachment rather than by
                   geometry. Deliberate in a hand-made pattern, suspicious in a
                   generated one.

    An empty list of errors means the file is structurally sound, which is not
    the same as saying its patterns are correct.
    """
    problems: list[dict] = []
    defs = _collection(config, "patternDefinitions")
    meta = _collection(config, "patternMeta")
    folders = _collection(config, "patternFolders")

    for pid, d in defs.items():
        name = d.get("name") or meta.get(pid, {}).get("name") or pid
        matcher_ids = set(d.get("matchers") or {})

        ordered = {x for group in (d.get("order") or []) for x in group}
        dangling = ordered - matcher_ids
        if dangling:
            problems.append({
                "pattern": name, "id": pid, "severity": "feil", "problem": "order peker utenfor mønsteret",
                "detail": f"{len(dangling)} id-er finnes ikke blant mønsterets "
                          f"{len(matcher_ids)} matchers"})
        missing = matcher_ids - ordered
        if ordered and missing:
            problems.append({
                "pattern": name, "id": pid, "severity": "advarsel", "problem": "matchers mangler i order",
                "detail": f"{len(missing)} primitiver står ikke i rekkefølgen"})

        if pid not in meta:
            problems.append({"pattern": name, "id": pid,
                             "severity": "feil", "problem": "mangler patternMeta", "detail": ""})

        folder = d.get("folder") or meta.get(pid, {}).get("folder")
        if folder and folder not in folders:
            problems.append({"pattern": name, "id": pid,
                             "severity": "feil", "problem": "peker på en mappe som ikke finnes",
                             "detail": str(folder)})

        term_ids = [t.get("id") for t in (d.get("terminals") or [])]
        if len(term_ids) != len(set(term_ids)):
            problems.append({"pattern": name, "id": pid,
                             "severity": "feil", "problem": "duplikate terminal-id-er", "detail": ""})

        if (meta.get(pid, {}).get("type") or d.get("type")) == "Symbol" \
                and d.get("enabled") and len(matcher_ids) < 2:
            problems.append({
                "pattern": name, "id": pid, "severity": "advarsel", "problem": "aktivt symbol med for lite geometri",
                "detail": f"{len(matcher_ids)} primitiv — vil matche nesten "
                          f"hva som helst på arket"})

    for pid in set(meta) - set(defs):
        problems.append({"pattern": meta[pid].get("name", pid), "id": pid,
                         "severity": "feil", "problem": "patternMeta uten patternDefinition",
                         "detail": ""})
    return problems


def write_config(config: dict, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    return path


# ------------------------------------------------------------- orchestration
def generate_from_detections(config: dict, detections: list[dict],
                             pdf_path: Path | str, dpi: int,
                             class_to_dexpi: dict[str, str],
                             *, min_conf: float = 0.80,
                             enable_above: float = 0.95,
                             max_per_class: int = 12,
                             min_primitives: int = 3,
                             seed: int | None = 42) -> dict:
    """Full pass: detections -> geometry -> clusters -> patterns -> merged config.

    Returns {"config", "patterns", "report"}. The report is the honest part:
    which classes produced a pattern, how many occurrences agreed on the
    geometry, and what was skipped and why.
    """
    rng = random.Random(seed)
    by_class: dict[str, list[dict]] = defaultdict(list)
    for det in detections:
        if float(det.get("conf", 0)) < min_conf:
            continue
        cls = det.get("cls")
        if cls in class_to_dexpi:
            by_class[cls].append(det)

    folder_id = new_id(rng)
    patterns: list[tuple[str, dict, dict]] = []
    report: list[dict] = []

    for cls, dets in by_class.items():
        dets = sorted(dets, key=lambda d: -float(d.get("conf", 0)))[:max_per_class]
        occurrences: list[tuple[str, list[Curve]]] = []
        for i, det in enumerate(dets):
            box = det.get("bbox_orig")
            if not box:
                continue
            try:
                curves = extract_region_geometry(pdf_path, tuple(box), dpi)
            except Exception as e:                              # noqa: BLE001
                report.append({"class": cls, "status": "geometri feilet",
                               "detail": str(e)[:120]})
                curves = []
            if curves:
                occurrences.append((f"{cls}#{i}", curves))

        if not occurrences:
            report.append({"class": cls, "status": "ingen geometri",
                           "detail": "regionen inneholdt ingen vektorprimitiver "
                                     "— skannet ark, eller feil DPI"})
            continue

        clusters = cluster_by_geometry(occurrences)
        biggest = max(clusters.values(), key=len)
        agreement = len(biggest) / len(occurrences)
        curves = dict(occurrences)[biggest[0]]

        # A pattern made of one or two primitives is not a symbol — it is a
        # line, and it will match every line on the sheet. When this fires the
        # geometry reader failed, not the detector: check the DPI, the y-axis
        # direction, and whether the symbols are Form XObjects.
        if len(curves) < min_primitives:
            report.append({
                "class": cls, "status": "for lite geometri",
                "occurrences": len(occurrences), "primitives": len(curves),
                "detail": f"bare {len(curves)} primitiv(er) lest ut — under "
                          f"grensen på {min_primitives}. Geometrileseren traff "
                          f"sannsynligvis rørlinjen, ikke symbolet."})
            continue

        best_conf = float(dets[0].get("conf", 0))
        dexpi_class = class_to_dexpi[cls]
        donor = donor_pattern(config, dexpi_class)
        if donor is None:
            report.append({"class": cls, "status": "ingen donor",
                           "detail": "fant ikke et eksisterende symbolmønster "
                                     "å arve toleranser fra"})
            continue

        terminals, term_warnings = inherit_terminals(donor, curves, rng=rng)
        enabled = (best_conf >= enable_above and agreement >= 0.8
                   and not term_warnings)

        name = f"{dexpi_class} (AI)"
        patterns.append(build_pattern(name, curves, dexpi_class, donor=donor,
                                      folder_id=folder_id, enabled=enabled,
                                      terminals=terminals, rng=rng))
        report.append({
            "class": cls, "status": "mønster laget", "dexpi": dexpi_class,
            "occurrences": len(occurrences), "clusters": len(clusters),
            "agreement": round(agreement, 2), "primitives": len(curves),
            "terminals": len(terminals), "best_conf": round(best_conf, 3),
            "enabled": enabled, "donor": donor.get("name", ""),
            "detail": "; ".join(term_warnings) or
                      ("aktivert" if enabled else
                       "levert avslått — skru på i Model Broker etter kontroll"),
        })

    merged = merge_patterns(config, patterns, folder_id)
    problems = validate_config(merged)
    return {"config": merged, "patterns": patterns, "report": report,
            "folder_id": folder_id, "problems": problems}


if __name__ == "__main__":
    import sys
    cfg = load_config(sys.argv[1])
    cat = pattern_catalogue(cfg)
    print(f"{len(cat)} mønstre i konfigurasjonen")
    for t, n in Counter(r["type"] for r in cat).most_common():
        print(f"  {n:4d}  {t}")
    print(f"\n{len(covered_dexpi_classes(cfg))} DEXPI-klasser dekket")