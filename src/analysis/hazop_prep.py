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

  SAFEGUARDS  Safety-typed tags (config.SAFETY_TYPES) in the loop or
              directly downstream, filtered by relevance to the deviation
              (a PSV safeguards High pressure, an LSH safeguards High
              level). Only tags that exist in the extraction are proposed.

Everything is preparation material: a pre-filled worksheet a HAZOP chair can
edit, not a completed study. Same AI pattern as ai/operator_brief.py: the
deterministic worksheet is the product; an LLM can optionally rephrase and
extend it, constrained to the tags it is given.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

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


def build_worksheet(graph: nx.DiGraph, objects, loops: list[str] | None = None,
                    nodes: dict[str, list] | None = None) -> list[dict]:
    """The HAZOP preparation worksheet: one row per (node, deviation).

    Nodes default to functional loops (PDF pipeline). Pass `nodes`
    ({name: [EngineeringObject, ...]}) to use richer groupings instead —
    e.g. equipment-anchored process sections from DEXPI connectivity
    (see analysis/hazop_dexpi.py). Same worksheet, better nodes.

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
        member_tags = ", ".join(sorted(o.tag for o in members))
        for param in params:
            for dev in DEVIATIONS[param]:
                sg = _safeguards(members, down, by_tag, dev)
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
    # quick check:  python src/analysis/hazop_prep.py 27
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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