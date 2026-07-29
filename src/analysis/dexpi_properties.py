"""
src/analysis/dexpi_properties.py
=====================================================================
What is actually IN the DEXPI files — object classes, generic attributes,
connection points, and the tag decomposition Model Broker already performed.

Why this module exists: before you can generate a Model Broker configuration
you have to know what the current one produces. That answer is not in the
configuration file (which only says which patterns exist) but in the DEXPI
output (which says which classes and attributes actually came out the other
end). This module reads that output and turns it into three inventories:

  class_inventory      : ComponentClass -> count + RDL URI
                         => the target list a generated pattern must map to
  attribute_coverage   : GenericAttribute name -> how often populated
                         => which attributes the configuration knows how to fill
  tag_grammar          : part1/part2/part3 value domains, recovered from
                         the GenericAttributes Model Broker writes
                         => the naming convention, observed rather than guessed

The tag grammar is the interesting one. Model Broker's Letter patterns split
each tag into positional parts and store them as part1..partN. Reading them
back gives you the segmentation the existing configuration used, including
its mistakes: a numeric value showing up in part2 means the split slid for
that tag.

Pure functions, no Streamlit, no I/O beyond reading the given paths —
unit-testable headless.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Elements in Proteus/DEXPI that represent a plant item rather than geometry.
# Kept explicit rather than "anything with a TagName" so the inventory is
# stable across files that tag different things.
ITEM_TAGS = (
    "Equipment", "Nozzle", "PipingComponent", "PipingNetworkSegment",
    "PipingNetworkSystem", "ProcessInstrument", "InstrumentComponent",
    "ActuatingSystem", "ActuatingFunction", "ProcessSignalGeneratingSystem",
    "ProcessSignalGeneratingFunction", "ProcessInstrumentationFunction",
    "PipeOffPageConnector", "SignalOffPageConnector", "PropertyBreak",
    "InformationFlow",
)

# GenericAttribute names that hold the positional tag split. Model Broker
# emits part1, part2, ... — we read as many as are present.
_PART_PREFIX = "part"


@dataclass
class Item:
    """One plant item from a DEXPI file."""
    drawing: str
    element: str                       # XML element name, e.g. PipingComponent
    item_id: str
    component_class: str | None
    class_uri: str | None
    tag: str | None
    attributes: dict[str, str] = field(default_factory=dict)
    parts: dict[str, str] = field(default_factory=dict)
    n_connection_points: int = 0
    connection_types: tuple[str, ...] = ()

    @property
    def has_tag(self) -> bool:
        return bool(self.tag)


# --------------------------------------------------------------- parsing
def _generic_attributes(elem: ET.Element) -> dict[str, str]:
    """All GenericAttribute Name -> Value directly under this element.

    Uses a direct-child path so a component does not absorb the attributes
    of nested items.
    """
    out: dict[str, str] = {}
    for ga in elem.findall("./GenericAttributes/GenericAttribute"):
        name, value = ga.get("Name"), ga.get("Value")
        if name is not None and value is not None:
            out[name] = value
    return out


def _connection_points(elem: ET.Element) -> tuple[int, tuple[str, ...]]:
    """Number of connection nodes and their declared types (process/signal)."""
    cp = elem.find("./ConnectionPoints")
    if cp is None:
        return 0, ()
    nodes = cp.findall("./Node")
    types = tuple(n.get("Type") or "" for n in nodes)
    return len(nodes), types


def _tag_of(elem: ET.Element, attrs: dict[str, str]) -> str | None:
    """TagName attribute if present, else the tagName generic attribute.

    Both occur in the same file — TagName on the element for piping
    components, tagName in GenericAttributes for several other types.
    """
    return elem.get("TagName") or attrs.get("tagName") or attrs.get("valveTag")


def parse_file(path: Path | str) -> list[Item]:
    """Every plant item in one DEXPI/Proteus XML file."""
    path = Path(path)
    root = ET.parse(path).getroot()
    drawing = path.stem
    items: list[Item] = []
    for elem in root.iter():
        if elem.tag not in ITEM_TAGS:
            continue
        attrs = _generic_attributes(elem)
        n_cp, cp_types = _connection_points(elem)
        parts = {k: v for k, v in attrs.items()
                 if k.startswith(_PART_PREFIX) and k[len(_PART_PREFIX):].isdigit()}
        items.append(Item(
            drawing=drawing,
            element=elem.tag,
            item_id=elem.get("ID") or "",
            component_class=elem.get("ComponentClass"),
            class_uri=elem.get("ComponentClassURI"),
            tag=_tag_of(elem, attrs),
            attributes=attrs,
            parts=parts,
            n_connection_points=n_cp,
            connection_types=cp_types,
        ))
    return items


def load_items(root: Path | str, pattern: str = "*.xml") -> list[Item]:
    """Every plant item across a folder of DEXPI files.

    Skips files that fail to parse rather than aborting the whole load —
    a malformed delivery should degrade, not stop the app.
    """
    root = Path(root)
    files = sorted(root.rglob(pattern)) if root.is_dir() else [root]
    items: list[Item] = []
    for f in files:
        try:
            items.extend(parse_file(f))
        except ET.ParseError:
            continue
    return items


# ------------------------------------------------------------ inventories
def class_inventory(items: list[Item]) -> list[dict]:
    """ComponentClass -> count, URI, how many carry a tag.

    This is the list a generated Model Broker pattern has to target: every
    class here was produced by some pattern in the current configuration.
    """
    counts: Counter[str] = Counter()
    uris: dict[str, str] = {}
    tagged: Counter[str] = Counter()
    elements: dict[str, Counter] = defaultdict(Counter)
    for it in items:
        cls = it.component_class or f"({it.element})"
        counts[cls] += 1
        elements[cls][it.element] += 1
        if it.class_uri:
            uris.setdefault(cls, it.class_uri)
        if it.has_tag:
            tagged[cls] += 1
    return [{"class": c, "count": n, "tagged": tagged[c],
             "tagged_pct": round(100 * tagged[c] / n, 1) if n else 0.0,
             "uri": uris.get(c, ""),
             "elements": ", ".join(sorted(elements[c]))}
            for c, n in counts.most_common()]


def attribute_coverage(items: list[Item]) -> list[dict]:
    """GenericAttribute name -> how many items carry it, and sample values.

    An attribute present on 70 of 82 segments is configured and working.
    One present on 3 is either rare by design or a configuration gap —
    the distinction needs an engineer, so show the numbers, not a verdict.
    """
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    distinct: dict[str, set[str]] = defaultdict(set)
    for it in items:
        for name, value in it.attributes.items():
            counts[name] += 1
            distinct[name].add(value)
            if len(samples[name]) < 3 and value not in samples[name]:
                samples[name].append(value)
    total = len(items) or 1
    return [{"attribute": a, "count": n,
             "of_items_pct": round(100 * n / total, 1),
             "distinct": len(distinct[a]),
             "samples": ", ".join(samples[a])}
            for a, n in counts.most_common()]


def tag_grammar(items: list[Item]) -> list[dict]:
    """Positional value domains recovered from part1..partN.

    Returns one row per position with the observed values and a flag for
    values that look out of place — a numeric value in a position that is
    otherwise alphabetic (or vice versa) means the split slid for that tag.
    """
    per_pos: dict[str, Counter] = defaultdict(Counter)
    for it in items:
        for name, value in it.parts.items():
            per_pos[name][value] += 1

    rows = []
    for pos in sorted(per_pos, key=lambda p: int(p[len(_PART_PREFIX):])):
        values = per_pos[pos]
        numeric = sum(n for v, n in values.items() if v.isdigit())
        alpha = sum(n for v, n in values.items() if v.isalpha())
        total = sum(values.values())
        # the minority shape is the suspect one
        if numeric and alpha:
            odd = ([v for v in values if v.isdigit()] if numeric < alpha
                   else [v for v in values if v.isalpha()])
        else:
            odd = []
        rows.append({
            "position": pos,
            "distinct": len(values),
            "count": total,
            "numeric": numeric,
            "alphabetic": alpha,
            "mixed": total - numeric - alpha,
            "values": ", ".join(v for v, _ in values.most_common(12)),
            "suspect": ", ".join(sorted(odd)[:8]),
        })
    return rows


def tag_reconstruction_check(items: list[Item]) -> list[dict]:
    """Items where joining the parts does not reproduce the tag.

    A cheap, exact consistency test: the parts are a decomposition of the
    tag, so concatenating them (ignoring separators) must give the tag back.
    Where it does not, either the split is wrong or the tag was rewritten
    after splitting — both worth an engineer's eye.
    """
    out = []
    for it in items:
        if not (it.tag and it.parts):
            continue
        ordered = [it.parts[k] for k in
                   sorted(it.parts, key=lambda p: int(p[len(_PART_PREFIX):]))]
        joined = "".join(ordered)
        flat = it.tag.replace("-", "").replace(" ", "")
        if joined != flat:
            out.append({"tag": it.tag, "drawing": it.drawing,
                        "parts": " | ".join(ordered), "joined": joined,
                        "class": it.component_class or it.element})
    return out


def tagged_items(items: list[Item]) -> list[Item]:
    """Objects that carry both a tag and a positional split, newest first.

    These are the ones the decoder can work with: without parts there is
    nothing to click, and without a tag there is nothing to decode.
    """
    return sorted((it for it in items if it.tag and it.parts),
                  key=lambda it: it.tag or "")


def part_positions(items: list[Item]) -> list[str]:
    """Every position name present, in order: part1, part2, ..."""
    names = {k for it in items for k in it.parts}
    return sorted(names, key=lambda p: int(p[len(_PART_PREFIX):]))


def ordered_parts(item: Item) -> list[tuple[str, str]]:
    """[(position, value), ...] for one item, left to right."""
    return [(k, item.parts[k]) for k in
            sorted(item.parts, key=lambda p: int(p[len(_PART_PREFIX):]))]


def position_values(items: list[Item], position: str) -> Counter:
    """How often each value occurs at one position across the whole set.

    This is the value domain — the thing you actually need when configuring a
    tool to read these tags, and the thing that is tedious to collect by hand.
    """
    c: Counter[str] = Counter()
    for it in items:
        if position in it.parts:
            c[it.parts[position]] += 1
    return c


def items_with_part(items: list[Item], position: str, value: str) -> list[Item]:
    """Every object sharing one value at one position."""
    return [it for it in items if it.parts.get(position) == value]


def summary(items: list[Item]) -> dict:
    """Headline numbers for the page header."""
    drawings = {it.drawing for it in items}
    tags = {it.tag for it in items if it.has_tag}
    classes = {it.component_class for it in items if it.component_class}
    with_parts = sum(1 for it in items if it.parts)
    return {"items": len(items), "drawings": len(drawings), "tags": len(tags),
            "classes": len(classes), "with_parts": with_parts,
            "untagged": sum(1 for it in items if not it.has_tag)}


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
    its = load_items(src)
    s = summary(its)
    print(f"{s['items']} objekter · {s['drawings']} tegninger · "
          f"{s['tags']} tags · {s['classes']} klasser")
    print("\nKlasser:")
    for r in class_inventory(its)[:15]:
        print(f"  {r['count']:4d}  {r['class']:34s} {r['tagged_pct']:5.1f} % tagget")
    print("\nTag-grammatikk:")
    for r in tag_grammar(its):
        print(f"  {r['position']}: {r['distinct']} unike — {r['values'][:60]}")
        if r["suspect"]:
            print(f"      mistenkelige: {r['suspect']}")
    bad = tag_reconstruction_check(its)
    print(f"\n{len(bad)} tags der delene ikke gjenskaper taggen")
    for b in bad[:5]:
        print(f"  {b['tag']:16s} <- {b['parts']}")