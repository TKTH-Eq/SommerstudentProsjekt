"""
Vision-assisted HAZOP excerpt — Gemini LOOKS at the drawing and proposes
observations; every tag it mentions is verified against the extraction.

Why verification is the whole point: a multimodal model reading a dense
P&ID makes confident transcription errors (LSL548 vs LSL0548 is a known
duplicate pattern in this dataset) and can invent plausible tags outright.
An unverified vision excerpt is therefore worse than none. Instead, every
tag the model mentions is classified against the tag register:

  verified       exists in the text-layer extraction — safe to reference
  new_candidate  well-formed tag NOT in the extraction — possibly a
                 symbol-only element the text layer missed (the 45 %
                 recall gap!), must be checked on the drawing by a human
  suspect        does not match any known tag format — probable
                 hallucination or misread, shown so the failure mode is
                 visible instead of hidden

This mirrors the project's recurring method: don't trust, MEASURE. The
"new_candidate" bucket is where vision can genuinely add value (eating into
the symbol-only recall gap); the "suspect" bucket is the honest cost.

Uses the same Gemini client, key (GEMINI_API_KEY) and pypdfium2 rendering
as extraction/vision_extract.py. Free-tier friendly: one image, one call.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:      # direct run support
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# tag shapes seen in this dataset: type-first (27-PT4805, 27-KA50),
# number-first hand valves (27-4561PV), and the wellhead convention with a
# space and no system prefix (HV 2264, PI 2275A, ESV 2252)
_TYPE_FIRST = re.compile(r"^\d{2}-[A-Z]{2,4}\d{2,4}[A-Z]?$")
_NUM_FIRST = re.compile(r"^\d{2}-\d{3,4}[A-Z]{1,4}$")
_BARE = re.compile(r"^[A-Z]{1,4}\s?\d{2,4}[A-Z]?$")


def _type_number(tag: str) -> tuple[str, str] | None:
    """(type_code, number) for any of the known conventions, else None.
    'HV 2264', '13-HV-2264', '13-2264HV' and '13-HV2264' all give
    ('HV', '2264') — the pair is convention-independent, which is what
    verification needs. Suffix letters (PI 2262A) fold into the type check
    via the trailing group."""
    t = re.sub(r"\s+", "", tag.strip().upper())
    t = t.split("-", 1)[1] if re.match(r"^\d{2}-", t) else t
    t = t.replace("-", "")                                   # HV-2264 -> HV2264
    m = re.match(r"^([A-Z]{1,4})(\d{2,4})([A-Z]?)$", t)      # type-first
    if m:
        # words that match the tag pattern but are not components
        if m.group(1) in {"NOTE", "SHEET", "REV", "PAGE", "DWG", "DOC"}:
            return None
        return m.group(1), m.group(2)
    m = re.match(r"^(\d{2,4})([A-Z]{1,4})$", t)              # number-first
    if m:
        return m.group(2), m.group(1)
    return None


def _classify(tag: str, known: set[str], known_pairs: set[tuple]) -> str:
    t = re.sub(r"\s+", "", tag.strip().upper())
    if t in known:
        return "verified"
    pair = _type_number(tag)
    if pair and pair in known_pairs:
        return "verified_loose"        # same instrument, other convention
    if pair:
        return "new_candidate"         # well-formed tag, not in extraction
    return "suspect"

PROMPT = """\
This image is an offshore P&ID / System Control Diagram. You are helping
prepare a HAZOP by LOOKING at the drawing.

Return ONLY JSON with this exact shape:
{
 "summary": "2-3 sentences on what process section the drawing shows",
 "observations": [
   {"observation": "one HAZOP-relevant observation (possible deviation,
     missing barrier, single point of failure, unusual arrangement)",
    "deviation": "closest guideword deviation, e.g. 'High pressure'",
    "tags": ["every tag you can READ that the observation involves"]}
 ],
 "possible_symbol_only": [
   {"tag": "tag of an element you can SEE as a symbol",
    "symbol": "what the symbol appears to be, e.g. 'relief valve'"}
 ]
}

Rules:
- Max 6 observations. Transcribe tags EXACTLY as printed (format examples:
  27-PT4805, 27-KA50, 27-4561PV). NEVER invent a tag you cannot read.
- "possible_symbol_only": elements drawn as symbols whose tag you can read —
  these are checked against a text-layer extraction, so precision matters.
- No text outside the JSON object.
"""


def verify_tags(excerpt: dict, known_tags) -> dict:
    """Classify every tag in the excerpt. Pure function — unit-testable
    without network. Adds 'status' per tag and a totals dict."""
    known = {re.sub(r"\s+", "", str(t).strip().upper()) for t in known_tags}
    known_pairs = {p for t in known if (p := _type_number(t))}
    counts = {"verified": 0, "verified_loose": 0, "new_candidate": 0, "suspect": 0}

    def _mark(tags):
        out = []
        for t in tags or []:
            s = _classify(t, known, known_pairs)
            counts[s] += 1
            out.append({"tag": str(t).strip().upper(), "status": s})
        return out

    for obs in excerpt.get("observations", []):
        obs["tags"] = _mark(obs.get("tags"))
    for so in excerpt.get("possible_symbol_only", []):
        so.update(_mark([so.get("tag", "")])[0])
    excerpt["tag_totals"] = counts
    return excerpt


def vision_hazop_excerpt(pdf_path: Path, known_tags, dpi: int = 200) -> dict:
    """Render page 1, ask Gemini for HAZOP observations, verify every tag.
    Requires GEMINI_API_KEY and pypdfium2 (same as vision_extract)."""
    from google.genai import types
    from extraction.vision_extract import _render_png
    from ai.gemini_client import generate

    png = _render_png(Path(pdf_path), dpi)
    img = Path(png).read_bytes()
    resp = generate(
        [types.Part.from_bytes(data=img, mime_type="image/png"), PROMPT],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    try:
        excerpt = json.loads(resp.text)
    except Exception:
        excerpt = {"summary": "(could not parse model output)",
                   "observations": [], "possible_symbol_only": [],
                   "raw": resp.text}
    return verify_tags(excerpt, known_tags)


_BADGE = {"verified": "✅", "verified_loose": "☑️",
          "new_candidate": "🟠", "suspect": "❓"}


def to_markdown(excerpt: dict) -> str:
    """Streamlit-friendly rendering with per-tag verification badges."""
    lines = [f"**Tegningen (modellens lesning):** {excerpt.get('summary', '')}", ""]
    for i, obs in enumerate(excerpt.get("observations", []), 1):
        tags = " ".join(f"{_BADGE[t['status']]}`{t['tag']}`" for t in obs["tags"]) or "—"
        lines.append(f"{i}. *{obs.get('deviation', '?')}* — "
                     f"{obs.get('observation', '')}  \n   Tags: {tags}")
    so = excerpt.get("possible_symbol_only", [])
    if so:
        lines += ["", "**Mulige symbol-only-elementer** (kan være recall-gapet):"]
        for s in so:
            lines.append(f"- {_BADGE[s['status']]}`{s['tag']}` — {s.get('symbol', '')}")
    c = excerpt.get("tag_totals", {})
    lines += ["", f"Tag-verifisering: ✅ {c.get('verified', 0)} bekreftet i uttrekket · "
                  f"☑️ {c.get('verified_loose', 0)} bekreftet via (type, nummer)-match · "
                  f"🟠 {c.get('new_candidate', 0)} nye kandidater (sjekk tegning) · "
                  f"❓ {c.get('suspect', 0)} ukjent format (linjenr/dok-ref/hallusinasjon)",
              "",
              "*Vision-generert forslag verifisert mot tag-registeret — "
              "for HAZOP-team-gjennomgang, ikke en fasit.*"]
    return "\n".join(lines)


if __name__ == "__main__":
    # usage: python src/ai/hazop_vision.py <drawing.pdf>   (needs GEMINI_API_KEY)
    from extraction.tag_extractor import extract_tags
    if len(sys.argv) < 2:
        sys.exit("usage: python src/ai/hazop_vision.py <drawing.pdf>")
    pdf = Path(sys.argv[1])
    known = extract_tags(str(pdf))
    ex = vision_hazop_excerpt(pdf, known)
    print(to_markdown(ex))