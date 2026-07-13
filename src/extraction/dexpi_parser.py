# src/extraction/dexpi_parser.py
"""
Parser for DEXPI-XML — den semantiske P&ID-eksporten som ligger bak
DGN-tegningene (*.DGN.xml).

DEXPI (Data Exchange in the Process Industry) er en bransjestandard som
representerer en P&ID som ekte objekter — instrumenter, ventiler,
roerlinjer, utstyr — med koordinater OG eksplisitte koblinger mellom dem.
Dette er fundamentalt annerledes enn PDF-tekstuttrekket i main.py, som kun
finner tag-NAVN uten aa vite hva som er koblet til hva.

To datasett hentes ut per fil:

  tags        én rad per plantobjekt: id, tag-navn, kategori, komponenttype,
              posisjon (x, y i mm) og hvilken tegning den kom fra.

  connections én rad per fysisk/signalmessig kobling mellom to objekt-ID-er
              (roer- eller signallinjer), med hvilken node paa hvert objekt
              de kobler til. Dette ER topologien.

  associations én rad per semantisk relasjon ("is fulfilled by", "is a part
              of", "is located in" osv.) — kobler f.eks. en instrument-
              FUNKSJON til det fysiske instrumentet som oppfyller den.

Bruk:
    from extraction.dexpi_parser import parse_dexpi
    tags_df, conn_df, assoc_df = parse_dexpi(Path("...DGN.xml"))
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

# Elementtyper som regnes som "tagbare" plantobjekter, og kategorien
# de skal merkes med i output.
TAG_ELEMENT_TYPES: dict[str, str] = {
    "ProcessInstrumentationFunction": "instrument",
    "InstrumentationLoopFunction": "instrument_loop",
    "ProcessSignalGeneratingFunction": "signal_generator",
    "ActuatingFunction": "actuating_function",
    "ActuatingSystem": "actuating_system",
    "ActuatingSystemComponent": "actuator",
    "PipingComponent": "piping_component",
    "PipingNetworkSegment": "piping_segment",
    "PipingNetworkSystem": "piping_system",
    "Equipment": "equipment",
    "Nozzle": "nozzle",
    "PipeOffPageConnector": "pipe_off_page",
    "SignalOffPageConnector": "signal_off_page",
}

# Elementer hvis <Connection>-barn representerer denne typen kobling
CONNECTION_CONTEXT_KIND = {
    "InformationFlow": "signal",
    "PipingNetworkSegment": "process",
}


def _get_attr(el: ET.Element, name: str) -> str | None:
    """Finn verdien av en <GenericAttribute Name="..."> rett under elementet
    (ikke i undertrær, for aa unngaa aa hente fra nestede barn)."""
    for ga in el.findall("./GenericAttributes/GenericAttribute"):
        if ga.get("Name") == name:
            return ga.get("Value")
    return None


def _get_position(el: ET.Element) -> tuple[float | None, float | None]:
    loc = el.find("./Position/Location")
    if loc is None:
        return None, None
    try:
        return float(loc.get("X", "nan")), float(loc.get("Y", "nan"))
    except (TypeError, ValueError):
        return None, None


def _best_tag_name(el: ET.Element) -> str | None:
    """Proev flere steder DEXPI kan gjemme tag-navnet, i prioritert rekkefoelge."""
    for candidate in ("tagName", "valveTag", "TagNameAssignmentClass"):
        val = _get_attr(el, candidate)
        if val:
            return val
    # Noen elementer (PipingNetworkSegment) har TagName som XML-attributt
    return el.get("TagName")


def parse_dexpi(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Parse én DEXPI-XML-fil. Returnerer (tags_df, connections_df, associations_df)."""
    drawing = path.stem.replace(".DGN", "")
    tree = ET.parse(path)
    root = tree.getroot()

    tag_rows: list[dict] = []
    conn_rows: list[dict] = []
    assoc_rows: list[dict] = []

    def walk(el: ET.Element, ancestors: list[tuple[str, str | None]]) -> None:
        tag = el.tag
        el_id = el.get("ID")

        if tag in TAG_ELEMENT_TYPES:
            x, y = _get_position(el)
            tag_rows.append({
                "drawing": drawing,
                "id": el_id,
                "category": TAG_ELEMENT_TYPES[tag],
                "component_class": el.get("ComponentClass", tag),
                "tag_name": _best_tag_name(el),
                "x_mm": x,
                "y_mm": y,
            })

        elif tag == "Connection":
            owner_tag, owner_id = ancestors[-1] if ancestors else (None, None)
            conn_rows.append({
                "drawing": drawing,
                "owner_id": owner_id,
                "kind": CONNECTION_CONTEXT_KIND.get(owner_tag, owner_tag),
                "from_id": el.get("FromID"),
                "from_node": el.get("FromNode"),
                "to_id": el.get("ToID"),
                "to_node": el.get("ToNode"),
            })

        elif tag == "Association":
            _, owner_id = ancestors[-1] if ancestors else (None, None)
            assoc_rows.append({
                "drawing": drawing,
                "source_id": owner_id,
                "assoc_type": el.get("Type"),
                "target_id": el.get("ItemID"),
            })

        new_ancestors = ancestors + [(tag, el_id)] if el_id else ancestors
        for child in el:
            walk(child, new_ancestors)

    walk(root, [])

    tags_df = pd.DataFrame(tag_rows).drop_duplicates(subset=["drawing", "id"])
    conn_df = pd.DataFrame(conn_rows)
    assoc_df = pd.DataFrame(assoc_rows)
    return tags_df, conn_df, assoc_df


def find_dexpi_files(raw_dir: Path) -> list[Path]:
    """Alle DEXPI-XML-filer under data/raw (mønster: *.DGN.xml)."""
    return sorted(raw_dir.rglob("*.DGN.xml"))
    