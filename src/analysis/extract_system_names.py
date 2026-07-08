# src/analysis/extract_system_names.py
"""
Infer a system-number -> system-name mapping for the C025 SCD set.

Method (robust to flattened DGN text):
  Every drawing's filename encodes its HOME system, e.g.
      C025-W-HO42-J-_E-001-01.DGN  ->  system 42
  and those sheets carry title-block text describing that system
  ("GAS EXPORT", "MEG INJECTION PUMPS", ...).
  So we group each drawing's descriptive title phrases by its home
  system and rank them. Boilerplate ("SYSTEM CONTROL DIAGRAM", the
  title-block company name, etc.) is filtered out.

Nothing is guessed silently: for every system we print the phrases we
found and how many drawings backed each, so you can confirm before
pasting the result into SYSTEM_NAMES in build_dependency_graph.py.

Run from the project root:
    uv run python -m src.analysis.extract_system_names
"""

import re
import json
from pathlib import Path
from collections import Counter, defaultdict

SCD_FOLDER = Path("data/raw/SCD")
OUT_DIR = Path("reports")

HOME_SYSTEM_RE = re.compile(r"HO(\d{2})", re.I)

# Phrases that appear on nearly every sheet and carry no system meaning.
BOILERPLATE = {
    "SYSTEM CONTROL DIAGRAM", "DRAWING TITLE", "DRAWING NO", "SYSTEM TAG",
    "OIL & GAS", "OIL  & GAS", "RNER OIL & GAS", "CORNER OIL & GAS",
    "STATOIL", "STATOIL ASA", "STATOIL STAVANGER AS", "STAVANGER",
    "AS BUILT", "ISSUED FOR CONSTRUCTION", "SCALE", "PROJECTION",
    "PROJECT NO", "WORK PACK", "AREA", "DISC", "SUP", "CHK", "DRN",
    "CONTR", "DATE", "TITLE", "REV", "SHT NO", "NUMBER", "SYSTEM NO",
    "DDB", "MULTISYSTEMS", "MULTISYSTEM",
}


def dgn_strings(path: Path) -> list[str]:
    """Return readable ASCII + UTF-16LE strings from a raw DGN file."""
    data = path.read_bytes()
    raw = re.findall(rb"[\x20-\x7e]{4,}", data)
    raw += re.findall(rb"(?:[\x20-\x7e]\x00){4,}", data)
    return [s.replace(b"\x00", b"").decode("ascii", "ignore") for s in raw]


def is_descriptive(phrase: str) -> bool:
    """Keep uppercase-ish descriptive phrases; drop boilerplate/noise."""
    p = phrase.strip().rstrip(".:;,")
    up = p.upper()
    if up in BOILERPLATE:
        return False
    if len(p) < 4 or len(p) > 40:
        return False
    letters = sum(c.isalpha() for c in p)
    if letters < 4:
        return False
    # mostly letters/spaces/&/-/. (i.e. looks like a label, not a code/number)
    if not re.fullmatch(r"[A-Za-z0-9 &()\-/.,']+", p):
        return False
    # must contain at least one "word" of 3+ letters
    if not re.search(r"[A-Za-z]{3,}", p):
        return False
    # drop pure numeric / tag-like fragments
    if re.fullmatch(r"[\d\-/. ]+", p):
        return False
    return True


def home_system(name: str) -> str | None:
    m = HOME_SYSTEM_RE.search(name)
    return m.group(1) if m else None


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    files = sorted(SCD_FOLDER.glob("*.DGN")) + sorted(SCD_FOLDER.glob("*.dgn"))
    if not files:
        raise SystemExit(f"No DGN files found in {SCD_FOLDER.resolve()}")

    # system -> Counter of descriptive phrases (counted once per drawing)
    phrases_by_system: dict[str, Counter] = defaultdict(Counter)
    drawings_by_system: dict[str, int] = Counter()
    seen: set[str] = set()

    for dgn in files:
        key = dgn.name.upper()
        if key.startswith("HHP-"):
            key = key[4:]
        if key in seen:
            continue
        seen.add(key)

        sys_no = home_system(dgn.name)
        if sys_no is None:
            continue
        drawings_by_system[sys_no] += 1

        # unique descriptive phrases in THIS drawing (so one sheet can't
        # spam the same phrase 10x)
        found = {
            s.strip().rstrip(".:;,")
            for s in dgn_strings(dgn)
            if is_descriptive(s)
        }
        for phrase in found:
            phrases_by_system[sys_no][phrase] += 1

    # Build a suggested name per system + keep evidence
    suggestions: dict[str, str] = {}
    print("=" * 72)
    print("SYSTEM NAME EVIDENCE  (verify these against the HO00 legend)")
    print("=" * 72)

    for sys_no in sorted(phrases_by_system, key=lambda s: int(s)):
        counter = phrases_by_system[sys_no]
        top = counter.most_common(6)
        n_drawings = drawings_by_system[sys_no]

        # Best single suggestion: the most frequent descriptive phrase.
        suggestion = top[0][0].title() if top else "(no readable title)"
        suggestions[sys_no] = suggestion

        label = "PLANT-WIDE / INTERCONNECTIONS" if sys_no == "00" else suggestion
        print(f"\nSystem {sys_no}  ({n_drawings} drawings)  ->  {label}")
        for phrase, cnt in top:
            bar = "#" * cnt
            print(f"    {cnt:2d} {bar:<8} {phrase}")

    # Emit a ready-to-paste Python dict
    dict_path = OUT_DIR / "system_names_suggested.py"
    lines = ["# Auto-suggested from drawing titles. VERIFY against HO00 before trusting.",
             "SYSTEM_NAMES = {"]
    for sys_no in sorted(suggestions, key=lambda s: int(s)):
        name = "Plant-wide / Interconnections" if sys_no == "00" else suggestions[sys_no]
        lines.append(f'    "{sys_no}": "{name}",')
    lines.append("}")
    dict_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = OUT_DIR / "system_names_suggested.json"
    json_path.write_text(json.dumps(suggestions, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"wrote {dict_path}")
    print(f"wrote {json_path}")
    print("Review the evidence above, correct anything wrong, then paste the")
    print("dict into build_dependency_graph.py (replacing SYSTEM_NAMES).")


if __name__ == "__main__":
    main()