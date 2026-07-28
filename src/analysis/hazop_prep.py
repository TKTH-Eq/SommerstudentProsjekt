"""
HAZOP preparation: propose nodes, deviations, causes, consequences and
safeguards from the extracted P&ID/SCD data — for human review.

How it maps to a real HAZOP:

  NODE        In a full HAZOP a node is a process section (vessel + lines).
              We cannot trace piping from the PDF text layer, so a node here
              is a FUNCTIONAL LOOP (system+number, same grouping as the
              dependency graph). Honest limit: loop-based nodes approximate
              but do not replace section-based nodes; DEXPI connectivity
              would allow real ones — which is itself a finding.

  PARAMETER   Inferred from the instrument types present in the loop
              (PT/PIC/PV -> Pressure, LT/LSH -> Level, FT/FV -> Flow, ...).

  DEVIATION   Standard guideword combinations per parameter (High/Low
              pressure, No/Reverse flow, ...). Deterministic, no AI needed.

  CAUSES      Failure modes of the loop's own logic/output elements (from
              analyze_scd.FAILURE_MODES, tied to REAL extracted tags) plus a
              few generic process causes, clearly marked "(generic)".

  CONSEQUENCE Downstream tags from the dependency graph (nx.descendants),
              i.e. what this loop actually drives in the extracted model.

  SAFEGUARDS  Two sources, strongest first.

              DESIGNED (when a cause & effect index is supplied): the
              actual trip stated on the SCD — "27-PSH4811 -> 27-XV4813:
              PSD close inlet [sheet]". This is what the plant is built
              to do, with a sheet reference the team can look up.

              STRUCTURAL (always): safety-typed tags (config.SAFETY_TYPES)
              in the loop or directly downstream, filtered by relevance to
              the deviation. This is a candidate — it says a PSV sits
              nearby, and leaves the team to infer the link.

              The difference matters in a HAZOP: "there is a safety valve
              in this loop" is a prompt, "this trip closes that valve on
              high pressure, per sheet E-101" is a safeguard. Only tags
              that exist in the extraction are ever proposed, and designed
              rows carry [UNVERIFIED] until an engineer has signed the C&E
              row off against the sheet.

              MEASURED LIMIT — designed safeguards fire on DEXPI section
              nodes and NOT on loop-based ones. A designed safeguard needs
              the initiating trip and a matching parameter in the same
              node; across all 7 systems, 0 of 55 loop-based nodes contain
              a trip element at all, because a switch's loop id (system +
              number) puts it in a loop of its own, away from the process
              loop it protects. DEXPI equipment-anchored sections do group
              them: 24-PA001-section holds 24-LSH2005 together with the
              valves it closes, so the safeguard lands. This is the
              project's format argument again, in HAZOP terms — loop-based
              nodes cannot express designed protection, section-based ones
              can.

Everything is preparation material: a pre-filled worksheet a HAZOP chair can
edit, not a completed study. Same AI pattern as ai/operator_brief.py: the
deterministic worksheet is the product; an LLM can optionally rephrase and
extend it, constrained to the tags it is given.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

if __name__ == "__main__" and __package__ is None:      # direct run support
    # must precede the `analysis.*` imports below — the bootstrap used to sit
    # in the __main__ block at the bottom, so `python src/analysis/hazop_prep.py`
    # (README workflow step 4) died on the first package import.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx

from analysis.analyze_scd import FAILURE_MODES
from config import SAFETY_TYPES

# ---------------------------------------------------------------------------
# Parameter inference and guideword tables
# ---------------------------------------------------------------------------

# type_code -> process parameter the instrument measures/controls
_PARAM_BY_PREFIX = {"P": "Pressure", "L": "Level", "F": "Flow", "T": "Temperature"}
_NON_PARAM_TYPES = {"HS", "XV", "ZS", "ZL", "KA", "PA", "VG", "VD", "FO", "PSE"}


def parameter_of(type_code: str) -> str | None:
    """Process parameter for a type code, or None if it isn't one (XV, HS...)."""
    if not type_code or type_code in _NON_PARAM_TYPES:
        return None
    return _PARAM_BY_PREFIX.get(type_code[0])


# guideword deviations per parameter (standard HAZOP practice)
DEVIATIONS = {
    "Pressure":    ["High pressure", "Low pressure"],
    "Level":       ["High level", "Low level"],
    "Flow":        ["No flow", "Low flow", "High flow", "Reverse flow"],
    "Temperature": ["High temperature", "Low temperature"],
}

# which safety-tag types are a credible safeguard for which deviation
_SAFEGUARD_FOR = {
    "High pressure":    {"PSV", "PSH", "XV"},
    "Low pressure":     {"XV"},
    "High level":       {"LSH", "LSHH", "XV"},
    "Low level":        {"LSL", "XV"},
    "No flow":          {"FSH", "XV"},
    "Low flow":         {"FSH", "XV"},
    "High flow":        {"FSH", "XV"},
    "Reverse flow":     {"XV"},
    "High temperature": {"XV"},
    "Low temperature":  {"XV"},
}

# generic consequences per deviation — engineering prompts, marked (generic)
_GENERIC_CONSEQUENCES = {
    "High pressure":    "possible overpressure of section (generic)",
    "Low pressure":     "loss of process function / possible gas breakthrough (generic)",
    "High level":       "possible carry-over / overfill (generic)",
    "Low level":        "possible gas blow-by to downstream (generic)",
    "No flow":          "loss of process function (generic)",
    "Low flow":         "reduced capacity (generic)",
    "High flow":        "possible downstream overload (generic)",
    "Reverse flow":     "possible contamination / backflow to upstream (generic)",
    "High temperature": "possible material/design-limit exceedance (generic)",
    "Low temperature":  "possible hydrate formation / brittle fracture risk (generic)",
}

# generic process causes per deviation — engineering prompts, not extracted
_GENERIC_CAUSES = {
    "High pressure":    ["blocked outlet (generic)", "upstream pressure source (generic)"],
    "Low pressure":     ["upstream supply loss (generic)", "leak / rupture (generic)"],
    "High level":       ["outlet restriction (generic)", "inflow exceeds outflow (generic)"],
    "Low level":        ["loss of feed (generic)", "excess drainage (generic)"],
    "No flow":          ["blocked line / closed valve (generic)", "pump/compressor stop (generic)"],
    "Low flow":         ["partial blockage / fouling (generic)"],
    "High flow":        ["control valve fully open (generic)"],
    "Reverse flow":     ["check-valve failure / pressure reversal (generic)"],
    "High temperature": ["loss of cooling (generic)"],
    "Low temperature":  ["JT-cooling on depressurisation (generic)", "loss of heating (generic)"],
}


# ---------------------------------------------------------------------------
# Worksheet construction (deterministic, offline)
# ---------------------------------------------------------------------------

def hazop_nodes(objects) -> dict:
    """Group extracted objects into candidate HAZOP nodes (functional loops).

    Returns {loop_id: [EngineeringObject, ...]} for loops with >= 2 members
    (a lone indicator is not a meaningful node).
    """
    loops = defaultdict(list)
    for o in objects:
        loops[o.loop].append(o)
    return {lp: ms for lp, ms in sorted(loops.items()) if len(ms) >= 2}


def _tagged_causes(members, deviation) -> list[str]:
    """Causes grounded in the loop's own CONTROL elements: 'tag: failure mode'.

    Safety-typed tags (PSV, XV, LSH...) are deliberately excluded: their
    failure is a degraded SAFEGUARD, not an initiating cause — mixing the two
    is a classic HAZOP-worksheet error.
    """
    out = []
    for o in members:
        if (o.category in ("logic", "output")
                and o.type_code not in SAFETY_TYPES
                and o.type_code in FAILURE_MODES):
            for mode in FAILURE_MODES[o.type_code][:2]:      # keep it short
                out.append(f"{o.tag}: {mode}")
    return out


def _consequences(graph: nx.DiGraph, members) -> tuple[list[str], list[str]]:
    """Functions the node drives, and the safety subset.

    The dependency graph is loop-based (edges only WITHIN a loop — see
    build_dependency_graph.py), so a node's descendants are its own members.
    The honest consequence statement is therefore: which logic/output
    functions inside the node are affected, plus any cross-loop descendants
    if a richer (e.g. DEXPI-based) graph is ever passed in.
    """
    member_tags = {o.tag for o in members}
    driven = sorted(o.tag for o in members if o.category in ("logic", "output"))
    safety = sorted(o.tag for o in members if o.type_code in SAFETY_TYPES)
    cross = set()
    for o in members:
        if o.tag in graph:
            cross |= set(nx.descendants(graph, o.tag)) - member_tags
    return sorted(set(driven) | cross), safety


def _safeguards(members, downstream_tags, by_tag, deviation) -> list[str]:
    """Safety-typed tags in the loop or directly downstream that are credible
    safeguards for THIS deviation. Only tags that exist in the extraction."""
    wanted = _SAFEGUARD_FOR.get(deviation, set())
    pool = list(members) + [by_tag[t] for t in downstream_tags if t in by_tag]
    return sorted({o.tag for o in pool if o.type_code in wanted})


# switch/trip-shaped type codes: parameter letter + S + direction (PSH, LSHH,
# FSL, PSLL). Deliberately narrow — a PT measures pressure but is not a trip.
_SWITCH_RE = re.compile(r"^([PLFT])S(HH|LL|H|L)$")


def _deviations_guarded(type_code: str) -> set[str]:
    """Deviations a trip element credibly guards, read off its own type code.

    Direction is the point: PSH guards High pressure, PSLL guards LOW
    pressure, and a high-pressure switch is not a safeguard against low
    pressure. The _SAFEGUARD_FOR table above cannot express that — it maps a
    deviation to a set of type codes without direction, and omits the HH/LL
    variants entirely (it lists PSH but not PSHH). This is used only for the
    designed-safeguard pass, where getting the direction wrong would put a
    real trip against the wrong deviation.
    """
    m = _SWITCH_RE.match((type_code or "").upper())
    if not m:
        return set()
    param = _PARAM_BY_PREFIX.get(m.group(1))
    if not param:
        return set()
    high = m.group(2).startswith("H")
    if param == "Flow":                       # no separate "No flow" switch
        return {"High flow"} if high else {"Low flow", "No flow"}
    return {f"{'High' if high else 'Low'} {param.lower()}"}


def _designed_safeguards(members, deviation, ce_index, member_tags,
                         member_loops) -> tuple[list[str], set[str]]:
    """Safeguards the DESIGNED logic states, rather than the structure guesses.

    For every member that is an initiating function for THIS deviation, the
    C&E index gives the elements it actually trips, plus the sheet the logic
    was read from. Two things the structural pass cannot do:

      * cite the ACTION ("closes 27-XV4813 on PSD") instead of naming a
        safety-typed tag that happens to sit nearby and leaving the team to
        guess whether it is connected at all
      * find safeguards OUTSIDE the node — a trip whose actuated element
        lives in another loop is invisible to the loop-based graph, but the
        C&E row states it plainly

    Only the direction "node member is the CAUSE" is implemented. The mirror
    case (an external trip acting ON a node member) was considered and left
    out: it would need the node to carry an instrument for the deviation the
    external trip guards, and no node in this dataset satisfies that — a
    valve node holds XV/HS/XY/ZL/ZS and no measuring element, so it has only
    the default Flow deviations to attach to. Worth adding if a dataset shows
    otherwise; not worth the branch here.

    Returns (lines, covered_tags); the caller skips structural entries for
    tags already described here — both the actuated element and the initiator,
    since a designed statement names both and strictly beats listing either as
    a bare proximity guess.
    """
    lines, covered = [], set()
    for o in members:
        if deviation not in _deviations_guarded(getattr(o, "type_code", "")):
            continue
        for r in ce_index.get("effects_of", {}).get(o.tag, []):
            effect = r.get("effect")
            if not effect:
                continue
            covered.update({effect, o.tag})
            # commas would break the ", ".join the safeguards column uses
            action = (r.get("function") or "action").replace(",", ";")
            marks = []
            # IPL: the detection sharing the node is the same independence
            # concern the structural pass flags — carried over so suppressing
            # the duplicate structural entry loses no warning. With loop-based
            # nodes the initiator is a member by construction and this always
            # fires; with DEXPI section nodes it discriminates.
            if getattr(o, "loop", None) in member_loops:
                marks.append("⚠ detection in node — verify independence")
            if effect in member_tags:
                marks.append("⚠ acts inside node")
            if not r.get("verified"):
                marks.append("UNVERIFIED")
            src = r.get("drawing") or r.get("file") or ""
            tail = f" [{src}]" if src else ""
            if marks:
                tail += f" [{'; '.join(marks)}]"
            lines.append(f"{o.tag} → {effect}: {action}{tail}")
    return sorted(set(lines)), covered


def build_worksheet(graph: nx.DiGraph, objects, loops: list[str] | None = None,
                    nodes: dict[str, list] | None = None,
                    ce_index: dict | None = None) -> list[dict]:
    """The HAZOP preparation worksheet: one row per (node, deviation).

    Nodes default to functional loops (PDF pipeline). Pass `nodes`
    ({name: [EngineeringObject, ...]}) to use richer groupings instead —
    e.g. equipment-anchored process sections from DEXPI connectivity
    (see analysis/hazop_dexpi.py). Same worksheet, better nodes.

    `ce_index`: the index from analysis.cause_effect.validate_ce()["index"].
    When supplied, the safeguards column leads with the DESIGNED trip stated
    on the SCD instead of a nearby safety-typed tag. Omitting it reproduces
    the previous behaviour exactly — the C&E layer is an upgrade, never a
    dependency, so a worksheet still builds with no cause & effect data at all.

    Every tag mentioned in causes/consequences/safeguards exists in the
    extracted data — nothing is invented. Rows where the node has no
    instrument for a parameter are simply not generated.
    """
    by_tag = {o.tag: o for o in objects}
    if nodes is None:
        # loop-based nodes: prefix the name so a node id ("27-4801") is not
        # mistaken for a tag — and so the PDF/DEXPI comparison makes the
        # difference in what a node CAN be visibly obvious
        base = hazop_nodes(objects)
        if loops is not None:
            base = {lp: ms for lp, ms in base.items() if lp in set(loops)}
        nodes = {f"loop {lp}": ms for lp, ms in base.items()}

    rows = []
    for loop_id, members in nodes.items():
        params = sorted({p for o in members if (p := parameter_of(o.type_code))})
        if not params:
            # a process section carries flow by definition — a node made of
            # hand valves/drains still deserves No/Reverse flow rows even
            # though nothing in it MEASURES a parameter
            if any(o.type_code for o in members):
                params = ["Flow"]
            else:
                continue
        down, down_safety = _consequences(graph, members)
        member_tag_set = {o.tag for o in members}
        member_tags = ", ".join(sorted(member_tag_set))
        for param in params:
            for dev in DEVIATIONS[param]:
                member_loops = {getattr(o, "loop", None) for o in members}
                # designed logic first: what the SCD says actually happens
                designed, covered = ([], set())
                if ce_index:
                    designed, covered = _designed_safeguards(
                        members, dev, ce_index, member_tag_set, member_loops)
                sg = _safeguards(members, down, by_tag, dev)
                # a designed statement already describes this tag, and does it
                # better — drop the bare structural mention of the same tag
                sg = [t for t in sg if t not in covered]
                # IPL principle: a safeguard sharing the loop with the
                # initiating instruments is not an independent layer —
                # credit it, but say so, so the team verifies independence.
                sg = [t + (" (⚠ same loop — verify independence)"
                           if by_tag.get(t) is not None
                           and getattr(by_tag[t], "loop", None) in member_loops
                           else "")
                      for t in sg]
                sg = designed + sg
                causes = _tagged_causes(members, dev) + _GENERIC_CAUSES.get(dev, [])
                conseq = _GENERIC_CONSEQUENCES.get(dev, "(review)")
                if down:
                    conseq += f"; functions affected: {', '.join(down)}"
                if down_safety:
                    conseq += f"; safety functions in node: {', '.join(down_safety)}"
                rows.append({
                    "node": loop_id,
                    "node_members": member_tags,
                    "parameter": param,
                    "deviation": dev,
                    "causes": "; ".join(causes) if causes else "(review)",
                    "consequences": conseq,
                    "safeguards": ", ".join(sg) if sg else "(none found in extraction — verify)",
                    "severity": "",                 # 1-5, the team's judgment
                    "likelihood": "",               # 1-5, the team's judgment
                    "risk": "",                     # computed from S x L
                    "recommendation": "",           # for the HAZOP team to fill in
                    "action_party": "",
                    "status": "proposed",
                })
    return rows


def write_worksheet_csv(rows: list[dict], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["node", "deviation"])
        w.writeheader()
        w.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# Optional AI layer — Gemini, same key/pattern as extraction/vision_extract.py
# ---------------------------------------------------------------------------

HAZOP_PROMPT = """\
You are preparing material for a HAZOP chair. Below is a machine-generated
worksheet for ONE node, built from tags extracted from the P&ID/SCD.

Rewrite and, where clearly justified, extend it:
- Keep the same columns: deviation | causes | consequences | safeguards.
- You may ONLY reference tags that appear in the worksheet or the member
  list. NEVER invent a tag. Generic engineering causes must be marked
  "(generic)".
- If a deviation has no credible safeguard among the listed tags, say
  "none identified — verify on drawing" rather than inventing one.
- Be terse: this is a worksheet, not prose.
- End with one line: "AI-prepared draft from extracted data — for HAZOP
  team review, not a completed study."

Worksheet:
"""


def ai_enrich_node(rows_for_node: list[dict]) -> str:
    """Send ONE node's deterministic rows to Gemini for fluent rewriting.
    Requires GEMINI_API_KEY (same as extraction/vision_extract.py); caller
    decides fallback (the deterministic worksheet IS the fallback and always
    exists)."""
    from ai.gemini_client import generate
    body = "\n".join(
        f"- {r['deviation']} | causes: {r['causes']} | consequences: "
        f"{r['consequences']} | safeguards: {r['safeguards']}"
        for r in rows_for_node)
    members = rows_for_node[0]["node_members"] if rows_for_node else ""
    resp = generate(f"{HAZOP_PROMPT}Node: {rows_for_node[0]['node']}\n"
                    f"Members: {members}\n{body}")
    return resp.text


if __name__ == "__main__":
    # quick check:  python src/analysis/hazop_prep.py 27      (path set at top)
    from extraction.tag_extractor import extract_tags, create_objects
    from analysis.build_dependency_graph import build_graph
    from main import resolve_inputs

    system = sys.argv[1] if len(sys.argv) > 1 else "27"
    pid, scd, system = resolve_inputs(["x", system])
    objs = sorted(set(create_objects(extract_tags(pid), "P&ID"))
                  | set(create_objects(extract_tags(scd), "SCD")), key=lambda o: o.tag)
    rows = build_worksheet(build_graph(objs), objs)
    print(f"{len(rows)} worksheet rows over {len({r['node'] for r in rows})} nodes\n")
    for r in rows[:8]:
        print(f"[{r['node']}] {r['deviation']}\n"
              f"   causes:      {r['causes']}\n"
              f"   consequence: {r['consequences']}\n"
              f"   safeguards:  {r['safeguards']}\n")
    out = Path("reports/hazop_worksheet.csv")
    out.parent.mkdir(exist_ok=True)
    write_worksheet_csv(rows, out)
    print(f"-> {out}")

def risk_of(severity, likelihood) -> str:
    """Risk class from the team's 1-5 severity x likelihood judgment.
    Deliberately NOT prefilled anywhere — scoring is the HAZOP team's
    call; this only classifies what they entered. Empty until both set."""
    try:
        s_, l_ = int(str(severity)), int(str(likelihood))
    except (TypeError, ValueError):
        return ""
    if not (1 <= s_ <= 5 and 1 <= l_ <= 5):
        return ""
    v = s_ * l_
    band = "High" if v >= 15 else "Medium" if v >= 8 else "Low"
    return f"{v} · {band}"