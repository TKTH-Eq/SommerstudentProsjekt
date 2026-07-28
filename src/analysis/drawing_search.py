"""
Find-the-right-drawing: rank P&ID sheets by a plain-language query.

The daily pain is knowing WHICH sheet to open. This builds a searchable profile
per drawing — deterministically from the tag register (type codes expanded into
words: "PT" → "pressure transmitter"), the tag names and the sheet name, PLUS
the cached 30-second vision summary when one exists (that is where words like
"separator" or "flare" come from). A query is scored against those profiles.

Works with no API key. An optional Gemini layer only EXPANDS the query into
extra keywords/synonyms (handling Norwegian↔English and "separator"→"vessel");
it never changes which drawings exist or invents matches — ranking stays over
the real sheets.
"""
from __future__ import annotations

import re
from pathlib import Path

# instrument/valve type code -> descriptive words (so "level transmitter" finds
# an LT sheet even though the drawing only carries the code)
_TYPE_PHRASES = {
    "PT": "pressure transmitter", "PIT": "pressure transmitter",
    "PI": "pressure indicator gauge", "PIC": "pressure controller control",
    "PSV": "pressure safety relief valve psv overpressure",
    "PSE": "pressure relief rupture disc overpressure",
    "PDI": "differential pressure", "PDT": "differential pressure transmitter",
    "LT": "level transmitter", "LI": "level indicator", "LG": "level gauge",
    "LSH": "level switch high", "LSHH": "level trip high high",
    "LSL": "level switch low", "LV": "level control valve",
    "FT": "flow transmitter", "FI": "flow indicator", "FIC": "flow controller",
    "FV": "flow control valve", "FO": "restriction orifice flow",
    "TT": "temperature transmitter", "TI": "temperature indicator",
    "TIC": "temperature controller", "TV": "temperature control valve",
    "XV": "shutdown valve esd on off isolation", "ESV": "emergency shutdown valve",
    "PV": "control valve", "PCV": "pressure control valve",
    "HV": "hand valve manual", "ZS": "valve position switch feedback",
    "ZL": "valve position lamp indication", "AE": "analyser gas detector",
    "HS": "hand switch", "XY": "solenoid relay", "PY": "pressure relay",
}
_STOP = {"the", "a", "an", "of", "in", "on", "is", "are", "which", "what",
         "where", "show", "me", "find", "drawing", "sheet", "with", "has",
         "have", "for", "to", "and", "that", "this", "på", "som", "har",
         "hvilken", "hvilke", "tegning", "med", "og", "er", "en", "et", "vis"}


def _tok(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-zA-Z0-9æøå]+", (text or "").lower())
            if w and w not in _STOP and len(w) > 1]


def build_index(raw_dir="data/raw", results_dir="reports/ai_cache") -> list[dict]:
    """One profile per DEXPI drawing: {stem, system, type_codes, terms,
    tagnames, summary, has_summary}. Cache at the call site."""
    from extraction.dexpi_parser import parse_dexpi
    from models.engineering_object import EngineeringObject
    from ai.drawing_summary import load_summary

    idx = []
    for xml in sorted(Path(raw_dir).rglob("*.DGN.xml")):
        stem = xml.stem.replace(".DGN", "")
        try:
            tags, _, _ = parse_dexpi(xml)
        except Exception:                                   # noqa: BLE001
            continue
        type_codes, tagnames, system = set(), set(), ""
        for r in tags.itertuples():
            if isinstance(r.tag_name, str) and r.tag_name.strip():
                o = EngineeringObject.from_tag(r.tag_name)
                if o.type_code:
                    type_codes.add(o.type_code)
                tagnames.add(o.tag.lower())
                if not system and o.system:
                    system = o.system

        terms = set(_tok(stem.replace("-", " ")))
        for tc in type_codes:
            terms.add(tc.lower())
            terms.update(_TYPE_PHRASES.get(tc, "").split())

        summ = load_summary(stem)
        summ_text = ""
        if summ:
            summ_text = " ".join(
                [summ.get("summary", "")] + summ.get("key_equipment", [])
                + summ.get("main_hazards", [])).lower()
        idx.append({
            "stem": stem, "system": system or "?",
            "type_codes": sorted(type_codes), "terms": terms,
            "tagnames": tagnames, "summary": summ_text,
            "has_summary": bool(summ)})
    return idx


def search(query: str, index: list[dict], extra_terms=None,
           top: int = 10) -> list[dict]:
    """Rank drawings for a query. Summary hits weigh most (3), descriptive
    terms next (2), a raw tag substring least (1). Returns the scored hits."""
    q = set(_tok(query)) | {str(t).lower() for t in (extra_terms or [])}
    out = []
    for d in index:
        score, hits = 0, []
        for t in q:
            if d["summary"] and t in d["summary"]:
                score += 3; hits.append(t)
            elif t in d["terms"]:
                score += 2; hits.append(t)
            elif any(t in tn for tn in d["tagnames"]):
                score += 1; hits.append(t)
        # a direct system-number query ("system 27")
        if d["system"] in q:
            score += 2; hits.append("system " + d["system"])
        if score:
            out.append({**d, "score": score, "hits": sorted(set(hits))})
    return sorted(out, key=lambda r: (-r["score"], r["stem"]))[:top]


def _phrase_to_codes() -> dict[str, set[str]]:
    """word -> {type codes whose phrase contains it}, plus each code by itself."""
    inv: dict[str, set[str]] = {}
    for code, phrase in _TYPE_PHRASES.items():
        for w in phrase.split():
            inv.setdefault(w, set()).add(code)
        inv.setdefault(code.lower(), set()).add(code)
    return inv


def query_codes(query: str, extra_terms=None) -> set[str]:
    """The instrument/valve type codes a query refers to, kept PRECISE: only
    the codes matching the MOST query words survive, so 'pressure relief valve'
    -> {PSV} (3 words) rather than every pressure- or valve-ish code. A
    single-word query keeps all codes matching that word ('valve' -> all
    valves). Used to highlight the right tags, not everything."""
    inv = _phrase_to_codes()
    terms = set(_tok(query)) | {str(t).lower() for t in (extra_terms or [])}
    counts: dict[str, int] = {}
    for t in terms:
        for c in inv.get(t, set()):
            counts[c] = counts.get(c, 0) + 1
    if not counts:
        return set()
    best = max(counts.values())
    return {c for c, n in counts.items() if n == best}


def relevant_tags(query: str, objects, extra_terms=None) -> list[str]:
    """Tags on ONE drawing that match the query — either their type code maps
    to a query term, or the tag text contains a query token. `objects` is an
    iterable of (tag, type_code)."""
    codes = query_codes(query, extra_terms)
    terms = set(_tok(query)) | {str(t).lower() for t in (extra_terms or [])}
    out = set()
    for tag, tc in objects:
        low = str(tag).lower()
        if (tc and tc in codes) or any(t in low for t in terms):
            out.add(tag)
    return sorted(out)


def expand_query(query: str) -> list[str]:
    """Optional: Gemini expands the query into extra English keywords/synonyms
    (equipment, instrument types, NO↔EN). Only affects scoring terms — never
    the set of drawings. [] with no key / on failure."""
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:                                       # noqa: BLE001
        pass
    if not os.getenv("GEMINI_API_KEY"):
        return []
    try:
        import json as _json
        from google.genai import types as _gt
        from ai.gemini_client import generate
        r = generate(expand_prompt(query), config=_gt.GenerateContentConfig(
            response_mime_type="application/json"))
        data = _json.loads(r.text)
        return [str(k).lower() for k in data.get("keywords", [])][:10]
    except Exception:                                       # noqa: BLE001
        return []


def expand_prompt(query: str) -> str:
    return (
        "A user is searching for an engineering P&ID drawing. Expand their "
        "query into up to 8 relevant lowercase ENGLISH keywords — equipment, "
        "instrument/valve types, process synonyms — translating any Norwegian. "
        'Respond ONLY with JSON {"keywords": ["..."]}. Do not answer the '
        f"question, only list keywords.\nQUERY: {query}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    ix = build_index()
    print(f"indexed {len(ix)} drawings "
          f"({sum(d['has_summary'] for d in ix)} with a vision summary)\n")
    for q in ["pressure relief valve", "shutdown valve", "level transmitter",
              "system 27"]:
        hits = search(q, ix, top=4)
        print(f"Q: {q}")
        for h in hits:
            print(f"   {h['score']:2d}  {h['stem']}  ← {', '.join(h['hits'][:6])}")
        print()
