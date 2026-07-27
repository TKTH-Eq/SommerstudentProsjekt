"""
Plant-wide GraphRAG: natural-language questions answered from the DEXPI graph
and tag register — NOT from a free-form LLM.

The pattern is the project's signature — *retrieve structured facts, then (optionally)
let the LLM phrase them* — applied to whole-plant queries:

    "what is downstream of 27-PT4805?"        -> nx.descendants on the tag graph
    "what protects 24-XV2163A?"                -> relief/trip tags in its neighbourhood
    "what trips close 27-XV4814?"              -> SHH/SLL functions that reach it
    "how is 27-PT4805 connected to 27-XV4814?" -> shortest path
    "list all PSVs in system 27"               -> register filter

Every tag in an answer is a REAL tag from the merged DEXPI graph, so the answer
is verifiable by construction. The optional LLM layer only rephrases the
retrieved facts and is told to invent nothing; the deterministic engine answers
fully without any API key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

# safeguard vocabulary (shared spirit with analysis.rule_screening)
_RELIEF = {"PSV", "PSE"}
_TRIP = {"LSHH", "PSHH", "LSH", "PSH", "LSL", "FSH", "LSLL", "PSLL"}
_SAFEGUARD = _RELIEF | _TRIP
_ACTUATED = {"XV", "ESV", "XY", "PV", "LV", "FV", "HV", "TV"}


# --------------------------------------------------------------- plant model
def build_plant_graph(raw_dir: str | Path = "data/raw") -> dict:
    """Merge every DEXPI drawing into one directed tag graph + object register.
    Returns {graph, objects, sections}. Cache this at the call site."""
    from analysis.hazop_dexpi import load_dexpi_model
    g = nx.DiGraph()
    objects: dict = {}
    sections: dict = {}
    for xml in sorted(Path(raw_dir).rglob("*.DGN.xml")):
        m = load_dexpi_model(xml)
        for o in m["objects"]:
            objects.setdefault(o.tag, o)
        g = nx.compose(g, m["tag_graph"])
        stem = xml.stem.replace(".DGN", "")
        sections[stem] = {name: [o.tag for o in members]
                          for name, members in (m["sections"] or {}).items()}
    return {"graph": g, "objects": objects, "sections": sections}


# ----------------------------------------------------------- entity lookup
def _norm(t: str) -> str:
    return re.sub(r"[\s\-]+", "", str(t).upper())


_TAG_RE = re.compile(r"\b\d{2}[-\s]?[A-Z]{1,4}[-\s]?\d{2,4}[A-Z]?\b", re.I)
# trailing s? so plurals ("PSVs", "valves") still match the type code
_TYPE_RE = re.compile(r"\b(PSV|PSE|PT|PIT|PDI|PDT|TT|LT|FT|"
                      r"XV|ESV|XY|PV|LV|FV|HV|TV|ZS|ZL|LSHH|PSHH|LSH|PSH|"
                      r"LSL|FSH|PIC|LIC|FIC|TIC|HS|FO|PI|TI|LI|FI)s?\b", re.I)


def resolve_tags(question: str, objects: dict) -> list[str]:
    """Real tags named in the question (exact-norm, else loose type+number)."""
    by_norm = {_norm(t): t for t in objects}
    by_typenum = {}
    for t, o in objects.items():
        if o.type_code and o.number:
            by_typenum.setdefault(f"{o.type_code}{o.number}", t)
    found = []
    for m in _TAG_RE.finditer(question):
        raw = _norm(m.group(0))
        if raw in by_norm:
            found.append(by_norm[raw])
            continue
        sysm = re.match(r"^(\d{2})", raw)
        qsys = sysm.group(1) if sysm else None
        key = re.sub(r"^\d{2}", "", raw)                     # drop system prefix
        mm = re.match(r"^([A-Z]{1,4})(\d{2,4}[A-Z]?)$", key)
        if mm:
            cand = by_typenum.get(f"{mm.group(1)}{mm.group(2)}")
            # only accept a loose match if it is in the SAME system the user
            # named — never silently jump to another system's tag
            if cand and (qsys is None or objects[cand].system == qsys):
                found.append(cand)
    # de-dup, keep order
    seen, out = set(), []
    for t in found:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def _systems(question: str) -> list[str]:
    return re.findall(r"\bsystem\s*(\d{2})\b", question, re.I)


# plain-word synonyms → sets of type codes, so "transmitters"/"valves" work
_SYNONYMS = {
    "transmitter": {"PT", "TT", "LT", "FT", "PDT", "PIT"},
    "valve": {"XV", "ESV", "PV", "LV", "FV", "HV", "TV", "PCV", "FO"},
    "instrument": {"PT", "PI", "TT", "TI", "LT", "LI", "FT", "FI", "PDI", "PDT"},
    "relief": _RELIEF,
    "psv": _RELIEF,
    "trip": _TRIP,
    "controller": {"PIC", "LIC", "FIC", "TIC"},
    "indicator": {"PI", "TI", "LI", "FI"},
    "position switch": {"ZS", "ZL"},
}


def _types(question: str) -> set[str]:
    ql = question.lower()
    want = {m.group(1).upper() for m in _TYPE_RE.finditer(question)}
    for word, codes in _SYNONYMS.items():
        if re.search(rf"\b{re.escape(word)}s?\b", ql):
            want |= codes
    return want


# ---------------------------------------------------------------- intents
@dataclass
class Answer:
    intent: str
    text: str
    tags: list[str]           # grounding: real tags the answer rests on
    facts: dict


def _short(o) -> str:
    return f"{o.tag} ({o.type_code})" if getattr(o, "type_code", "") else o.tag


def _classify(q: str) -> str:
    # prefix matching (no trailing \b) so plurals/inflections match:
    # "protects", "trips", "closes", "isolation", "sections"
    ql = q.lower()
    if re.search(r"\b(between|path|route)\b", ql) or "connected to" in ql:
        return "path"
    if re.search(r"\b(downstream|feeds into|flow|goes to)", ql) or "after " in ql:
        return "downstream"
    if re.search(r"\b(upstream|feeds from|source of|comes from)", ql) \
            or "before " in ql:
        return "upstream"
    if re.search(r"\b(protect|safeguard|relief)", ql):
        return "protects"
    if re.search(r"\b(trip|close|shut|esd|isolat)", ql):
        return "trips_closing"
    if re.search(r"\bloop", ql):
        return "loop"
    if re.search(r"\b(section|node)", ql):
        return "section"
    if re.search(r"\b(list|all|how many|count|number of)\b", ql):
        return "list_type"
    if re.search(r"\b(connected|neighbou?r|attached|next to)", ql):
        return "neighbors"
    return "neighbors"


_INTENTS = ["downstream", "upstream", "neighbors", "path", "protects",
            "trips_closing", "loop", "section", "list_type"]


def understand_prompt(question: str) -> str:
    """The exact prompt sent to Gemini to PARSE a question into a structured
    query. Exposed so the UI can show it — no hidden prompting."""
    return (
        "You convert a plant-engineering question into a structured query. "
        "Respond ONLY with JSON: "
        '{"intent": "<one of ' + "|".join(_INTENTS) + '>", "tags": ["<full '
        'tags mentioned, e.g. 27-PT4805>"], "types": ["<instrument/valve type '
        'codes, e.g. PSV>"], "systems": ["<2-digit system numbers>"]}. '
        "intent meanings: downstream/upstream = graph reachability; path = "
        "route between two tags; protects = relief/trip safeguards; "
        "trips_closing = trips that shut a valve; loop = same loop; section = "
        "HAZOP section; list_type = enumerate a type. Do not invent tags.\n"
        f"QUESTION: {question}")


def phrase_prompt(question: str, ans: "Answer") -> str:
    """The exact prompt sent to Gemini to REPHRASE the retrieved facts."""
    return (
        "You are a plant-engineering assistant. Answer the question using "
        "ONLY the facts below — do not invent tags or connections. Keep it "
        "to 2–4 sentences and cite the tags.\n\n"
        f"QUESTION: {question}\n\nRETRIEVED FACTS (from the DEXPI graph):\n"
        f"{ans.text}\n\nGrounding tags: {', '.join(ans.tags[:30])}")


def llm_understand(question: str, objects: dict) -> dict | None:
    """Optional AI layer: parse a free-form question into {intent, tags, types,
    systems}. The LLM only *proposes* — every tag it returns is re-resolved
    against the register (resolve_tags), so a hallucinated tag is dropped, not
    trusted. Returns None with no key / on failure, and the deterministic
    regex parser takes over."""
    import os
    import json as _json
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:                                       # noqa: BLE001
        pass
    if not os.getenv("GEMINI_API_KEY"):
        return None
    try:
        from google.genai import types as _gt
        from ai.gemini_client import generate
        prompt = understand_prompt(question)
        r = generate(prompt, config=_gt.GenerateContentConfig(
            response_mime_type="application/json"))
        data = _json.loads(r.text)
        intent = data.get("intent")
        tags = resolve_tags(" ".join(str(t) for t in data.get("tags", [])),
                            objects)                        # grounding gate
        types = {str(t).upper() for t in data.get("types", [])}
        systems = [str(s) for s in data.get("systems", []) if str(s).isdigit()]
        return {"intent": intent if intent in _INTENTS else None,
                "tags": tags, "types": types, "systems": systems}
    except Exception:                                       # noqa: BLE001
        return None


def ask(question: str, model: dict, hint: dict | None = None) -> Answer:
    """Grounded answer from the plant graph. `hint` (from llm_understand) may
    supply a parsed intent/tags/types/systems; anything missing falls back to
    the deterministic regex parser, so this always works without a key."""
    g, objects = model["graph"], model["objects"]
    tags = (hint or {}).get("tags") or resolve_tags(question, objects)
    intent = (hint or {}).get("intent") or _classify(question)

    def obj(t):
        return objects.get(t)

    want = set((hint or {}).get("types") or set()) | _types(question)
    # ---- list / count by type (+ optional system) ------------------------
    # only when the question is genuinely a list/enumerate — an explicit tag
    # intent whose tag we failed to resolve must NOT silently become a list.
    if intent == "list_type" or (not tags and want and intent == "neighbors"):
        syss = set((hint or {}).get("systems") or set()) | set(_systems(question))
        hits = sorted(t for t, o in objects.items()
                      if o.type_code in want and (not syss or o.system in syss))
        scope = f" in system {'/'.join(syss)}" if syss else ""
        kinds = "/".join(sorted(want)) or "components"
        return Answer("list_type",
                      f"{len(hits)} {kinds}{scope}: " +
                      (", ".join(hits[:40]) + (" …" if len(hits) > 40 else "")
                       if hits else "none found."),
                      hits, {"count": len(hits), "types": sorted(want)})

    if not tags:
        return Answer("unknown",
                      "No known tag recognised in the question. Name a tag "
                      "(e.g. 27-PT4805) or ask e.g. “list all PSVs in system 27”.",
                      [], {})
    a = tags[0]
    if a not in g:
        return Answer(intent, f"{a} is in the register but has no connections "
                      f"in the DEXPI graph (isolated or symbol-only).", [a], {})

    # ---- path between two tags -------------------------------------------
    if intent == "path" and len(tags) >= 2:
        b = tags[1]
        try:
            p = nx.shortest_path(g.to_undirected(as_view=True), a, b)
            return Answer("path",
                          f"{a} connects to {b} via {len(p)-1} hop(s): "
                          + " → ".join(p), p, {"hops": len(p) - 1})
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return Answer("path", f"No path found between {a} and {b} in the "
                          f"DEXPI graph.", [a, b], {})

    # ---- downstream / upstream -------------------------------------------
    if intent in ("downstream", "upstream"):
        reach = (nx.descendants if intent == "downstream" else nx.ancestors)(g, a)
        acts = sorted(t for t in reach
                      if obj(t) and obj(t).type_code in _ACTUATED)
        rel = sorted(t for t in reach
                     if obj(t) and obj(t).type_code in _SAFEGUARD)
        word = "downstream of" if intent == "downstream" else "upstream of"
        lines = [f"{len(reach)} tags {word} {a}."]
        if acts:
            lines.append("Actuated valves reached: " + ", ".join(acts[:12]))
        if rel:
            lines.append("Safeguards reached: " + ", ".join(rel[:12]))
        sample = sorted(reach)[:20]
        lines.append("Sample: " + ", ".join(sample) + (" …" if len(reach) > 20 else ""))
        return Answer(intent, "  \n".join(lines), sorted(reach),
                      {"reachable": len(reach), "valves": acts, "safeguards": rel})

    # ---- protects / safeguards -------------------------------------------
    if intent == "protects":
        nbrhood = nx.ancestors(g, a) | nx.descendants(g, a) | {a}
        loop = obj(a).loop if obj(a) else None
        same_loop = {t for t, o in objects.items() if o.loop == loop} if loop else set()
        sg = sorted(t for t in (nbrhood | same_loop)
                    if t != a and obj(t) and obj(t).type_code in _SAFEGUARD)
        if not sg:
            return Answer("protects",
                          f"No relief (PSV/PSE) or trip (SHH/SLL) tag found in "
                          f"{a}'s graph neighbourhood or loop. This may be a real "
                          f"gap OR the safeguard is symbol-only / on an adjacent "
                          f"sheet — cross-check (see the rule findings tab).",
                          [a], {"safeguards": []})
        rel = [t for t in sg if obj(t).type_code in _RELIEF]
        trp = [t for t in sg if obj(t).type_code in _TRIP]
        parts = [f"Safeguards associated with {a}:"]
        if rel:
            parts.append("Relief: " + ", ".join(rel))
        if trp:
            parts.append("Trips: " + ", ".join(trp))
        return Answer("protects", "  \n".join(parts), sg,
                      {"relief": rel, "trips": trp})

    # ---- trips that close a valve ----------------------------------------
    if intent == "trips_closing":
        ups = nx.ancestors(g, a)
        trips = sorted(t for t in ups
                       if obj(t) and obj(t).type_code in _TRIP)
        if obj(a) and obj(a).type_code not in _ACTUATED:
            note = (f" (note: {a} is a {obj(a).type_code}, not an actuated "
                    f"valve — results show trips upstream of it).")
        else:
            note = ""
        if not trips:
            return Answer("trips_closing",
                          f"No trip function (SHH/SLL) found upstream of {a} in "
                          f"the graph{note}. The actuation may be in SCD logic "
                          f"or on another sheet — verify (see rule R2).",
                          [a], {"trips": []})
        return Answer("trips_closing",
                      f"{len(trips)} trip function(s) upstream of {a}{note}: "
                      + ", ".join(trips), trips, {"trips": trips})

    # ---- loop siblings ----------------------------------------------------
    if intent == "loop":
        loop = obj(a).loop if obj(a) else None
        sibs = sorted(t for t, o in objects.items() if o.loop == loop)
        return Answer("loop", f"Loop {loop} has {len(sibs)} tag(s): "
                      + ", ".join(sibs), sibs, {"loop": loop})

    # ---- section membership ----------------------------------------------
    if intent == "section":
        for drawing, secs in model["sections"].items():
            for name, members in secs.items():
                if a in members:
                    return Answer("section",
                                  f"{a} is in section “{name}” on {drawing} "
                                  f"({len(members)} members): "
                                  + ", ".join(sorted(members)[:20]),
                                  members, {"section": name, "drawing": drawing})
        return Answer("section", f"{a} is not assigned to a named section.",
                      [a], {})

    # ---- default: direct neighbours --------------------------------------
    pre = sorted(g.predecessors(a))
    suc = sorted(g.successors(a))
    return Answer("neighbors",
                  f"{a} connects directly to {len(pre)+len(suc)} tag(s).  \n"
                  f"Upstream: {', '.join(pre[:12]) or '—'}  \n"
                  f"Downstream: {', '.join(suc[:12]) or '—'}",
                  pre + suc, {"upstream": pre, "downstream": suc})


# ------------------------------------------------------- optional LLM phrasing
def phrase_with_llm(question: str, ans: Answer) -> str | None:
    """Rephrase the RETRIEVED facts into a fluent answer — invents nothing.
    Returns None if no API key / call fails; the deterministic text stands."""
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:                                       # noqa: BLE001
        pass
    if not os.getenv("GEMINI_API_KEY"):
        return None
    try:
        from ai.gemini_client import generate
        r = generate(phrase_prompt(question, ans))
        return (r.text or "").strip() or None
    except Exception:                                       # noqa: BLE001
        return None


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    M = build_plant_graph("data/raw")
    print(f"plant graph: {M['graph'].number_of_nodes()} tags, "
          f"{M['graph'].number_of_edges()} edges\n")
    for q in ["what is downstream of 27-PT4805?",
              "what protects 24-XV2163A?",
              "what trips close 27-XV4814?",
              "how is 27-PT4805 connected to 27-XV4814?",
              "list all PSVs in system 27",
              "what is in the same loop as 24-XV2163A?"]:
        a = ask(q, M)
        print(f"Q: {q}\n[{a.intent}] {a.text}\n")
