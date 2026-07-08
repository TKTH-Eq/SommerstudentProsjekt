"""
Operator briefing layer.

Takes the structured failure data for one tag (from analysis.analyze_scd.
failure_map) and turns it into a short, fixed-structure briefing an operator
can read at a glance:

    SITUATION · POSSIBLE FAILURE MODES · IMMEDIATE IMPACT ·
    WHERE TO INVESTIGATE · RECOMMENDED FIRST CHECKS · NOTE

Two implementations behind one function:
  - _template_brief : deterministic, runs offline, shows the exact structure.
  - _ai_brief       : the SAME facts sent to an approved model for fluent prose.

`operator_brief()` uses the model when ANTHROPIC_API_KEY is set, else the
template. So wiring in AI is literally: set the key (or point _ai_brief at the
approved Azure deployment) — nothing else in the pipeline changes.

Everything is decision SUPPORT: it is built from AI-extracted, loop-based data
and must be verified against the drawings and live readings before action.
"""
from __future__ import annotations
import os

# operator-facing first checks, by instrument/equipment type (generic guidance)
FIRST_CHECKS = {
    "PT": ["compare reading against a second/redundant transmitter",
           "check impulse line and isolation valves for blockage",
           "confirm the value in the control system vs local gauge"],
    "TT": ["compare against a nearby temperature reading",
           "check sensor connection / thermowell"],
    "LT": ["cross-check level against sight glass or redundant transmitter",
           "verify no false trip has latched"],
    "FT": ["check flow element for blockage/fouling", "compare with upstream/downstream flow"],
    "XV": ["confirm valve position feedback (ZS/ZL) matches command",
           "check actuator air/hydraulic supply", "verify no active interlock is holding it"],
    "PSV": ["check for passing/leakage", "confirm set pressure and last test date"],
    "PIC": ["check controller mode (auto/manual) and output", "review recent setpoint changes"],
    "KA": ["check trip/alarm status and vibration", "review anti-surge and seal-gas systems"],
    "PA": ["check trip status, suction pressure and seal system"],
}
DEFAULT_CHECKS = ["verify the signal in the control system",
                  "inspect the device and its connections",
                  "cross-check against a redundant or related measurement"]

TYPE_NAMES = {
    "PT": "pressure transmitter", "PI": "pressure indicator", "PDT": "diff-pressure transmitter",
    "PDI": "diff-pressure indicator", "TT": "temperature transmitter", "TI": "temperature indicator",
    "LT": "level transmitter", "LSH": "high-level switch", "LSL": "low-level switch",
    "FT": "flow transmitter", "FE": "flow element", "XV": "shutdown valve",
    "FV": "control valve", "PV": "control valve", "PSV": "relief valve", "HS": "hand switch",
    "PIC": "pressure controller", "LIC": "level controller", "FIC": "flow controller",
    "ZS": "position switch", "ZL": "position lamp/limit", "KA": "compressor", "PA": "pump",
}


def _facts(tag, entry, by_tag):
    o = by_tag.get(tag)
    tc = o.type_code if o else ""
    return {
        "tag": tag,
        "type_name": TYPE_NAMES.get(tc, "component"),
        "type_code": tc,
        "category": entry["category"],
        "modes": entry["modes"],
        "downstream": entry["downstream"],
        "safety": entry["safety"],
        "upstream": entry["upstream"],
        "checks": FIRST_CHECKS.get(tc, DEFAULT_CHECKS),
    }


def _template_brief(f) -> str:
    impact = (f"affects {len(f['downstream'])} downstream function(s)"
              + (f"; safety functions possibly degraded: {', '.join(f['safety'])}"
                 if f['safety'] else "; no safety function affected in the loop model"))
    where = (", ".join(f['upstream']) if f['upstream']
             else "no upstream candidate in the loop model")
    return (
        f"SITUATION: {f['tag']} ({f['type_name']}) reported faulty.\n"
        f"POSSIBLE FAILURE MODES: {'; '.join(f['modes'])}.\n"
        f"IMMEDIATE IMPACT: {impact}.\n"
        f"WHERE TO INVESTIGATE: {where}.\n"
        f"RECOMMENDED FIRST CHECKS: {'; '.join(f['checks'])}.\n"
        f"NOTE: Decision support from AI-extracted, loop-based data — verify "
        f"against the P&ID/SCD and live readings before acting."
    )


OPERATOR_PROMPT = """\
You are assisting a control-room operator. From the structured facts below,
write a SHORT briefing with EXACTLY these headings, one line each:
SITUATION, POSSIBLE FAILURE MODES, IMMEDIATE IMPACT, WHERE TO INVESTIGATE,
RECOMMENDED FIRST CHECKS, NOTE.
Rules: use ONLY the facts given; never invent tags or numbers; be concise and
plain; in NOTE state this is AI-extracted decision support to be verified
against the drawings and live readings. Facts:
"""


def _ai_brief(f) -> str:
    import anthropic
    client = anthropic.Anthropic()          # or the approved Azure deployment
    msg = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=400,
        messages=[{"role": "user", "content": OPERATOR_PROMPT + str(f)}])
    return msg.content[0].text


def operator_brief(tag, entry, by_tag, use_ai: bool | None = None) -> str:
    """Structured operator briefing for one tag. Model if available, else template."""
    f = _facts(tag, entry, by_tag)
    if use_ai is None:
        use_ai = bool(os.getenv("ANTHROPIC_API_KEY"))
    return _ai_brief(f) if use_ai else _template_brief(f)


def briefs_for(fmap, objects, use_ai: bool | None = None) -> dict:
    """One briefing per tag (for embedding in the dashboard)."""
    by_tag = {o.tag: o for o in objects}
    return {tag: operator_brief(tag, entry, by_tag, use_ai)
            for tag, entry in fmap.items()}


if __name__ == "__main__":
    # quick check on the HO27 pair: python src/ai/operator_brief.py 27 27-PT4805
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from extraction.tag_extractor import extract_tags, create_objects
    from analysis.build_dependency_graph import build_graph
    from analysis.analyze_scd import failure_map
    from main import resolve_inputs
    system = sys.argv[1] if len(sys.argv) > 1 else "27"
    tag = sys.argv[2] if len(sys.argv) > 2 else "27-PT4805"
    pid, scd, system = resolve_inputs(["x", system])
    objs = sorted(set(create_objects(extract_tags(pid), "P&ID"))
                  | set(create_objects(extract_tags(scd), "SCD")), key=lambda o: o.tag)
    fmap = failure_map(build_graph(objs), objs)
    print(operator_brief(tag, fmap[tag], {o.tag: o for o in objs}))