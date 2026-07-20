"""
Rule screening: findings the drawing does NOT show — anchored to standards.

The HAZOP worksheet describes deviations for what IS on the drawing. This
module finds what seems to be MISSING: a pressure-controlled section with
no relief path, a trip function with no actuation, a section with no
pressure monitoring. That capability provably requires structured data —
from a PDF, the absence of a line cannot be distinguished from an
extraction miss (the 45 % recall gap), which is why this module runs on the
DEXPI model only.

STANDARD REFERENCES ARE INDICATIVE. Each finding carries a pointer to the
governing standard family (NORSOK P-001 pressure protection / S-001
technical safety / I-001 instrumentation; API 521 for relief philosophy),
NOT a verified clause number. A discipline engineer must confirm both the
finding and the reference before any use beyond screening — the module
says so in every output row. Findings are screening candidates, not
non-conformities.

Rules are deliberately few and conservative (structural absence only, no
sizing, no process judgement):

  R1  MISSING RELIEF PATH    section contains pressure control/measurement
                             but no PSV/PSE among its members
  R2  TRIP WITHOUT ACTION    an SHH/SLL trip function with no XV/valve
                             reachable downstream in the graph
  R3  BLIND SECTION          section with ≥4 members but no pressure
                             measurement at all

Each finding lists the REAL tags that triggered it, so the viewer can mark
the location on the drawing.
"""
from __future__ import annotations

import sys

import networkx as nx

if __name__ == "__main__" and __package__ is None:      # direct run support
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_VERIFY = "Veiledende referanse — fagingeniør må bekrefte funn og klausul."

_PRESSURE_TYPES = {"PT", "PI", "PIC", "PIT", "PDI", "PDT", "PV", "PSH", "PSL"}
_RELIEF_TYPES = {"PSV", "PSE"}
_TRIP_TYPES = {"LSHH", "PSHH", "LSH", "PSH", "LSL", "FSH"}
_ACTION_TYPES = {"XV", "ESV", "XY"}


def screen(graph: nx.DiGraph, objects, sections: dict) -> list[dict]:
    """Findings over one drawing's DEXPI model.

    graph/objects/sections come straight from hazop_dexpi.load_dexpi_model.
    Returns [{rule, title, severity, tags, section, description,
              recommendation, standard}] — tags are real extracted tags,
    usable as anchors for on-drawing markers.
    """
    by_tag = {o.tag: o for o in objects}
    findings: list[dict] = []

    # ---- R1 + R3: per section ----------------------------------------------
    for name, members in (sections or {}).items():
        types = {o.type_code for o in members if o.type_code}
        p_tags = sorted(o.tag for o in members if o.type_code in _PRESSURE_TYPES)
        relief = sorted(o.tag for o in members if o.type_code in _RELIEF_TYPES)
        if p_tags and not relief:
            findings.append({
                "rule": "R1", "title": "Mulig manglende avlastningsvei",
                "severity": "høy", "section": name, "tags": p_tags[:6],
                "description": f"Seksjonen har trykkmåling/-regulering "
                               f"({', '.join(p_tags[:4])}) men ingen "
                               f"PSV/PSE blant medlemmene.",
                "recommendation": "Verifiser på tegning/tilstøtende ark om "
                                  "avlastning finnes utenfor seksjonen, eller "
                                  "om den mangler.",
                "standard": f"NORSOK P-001 / API 521 (trykkbeskyttelse). {_VERIFY}",
            })
        if len(members) >= 4 and not (types & (_PRESSURE_TYPES | _RELIEF_TYPES)):
            findings.append({
                "rule": "R3", "title": "Seksjon uten trykkovervåking",
                "severity": "lav", "section": name,
                "tags": sorted(o.tag for o in members)[:6],
                "description": f"{len(members)} komponenter uten noen "
                               f"trykkmåling i seksjonen.",
                "recommendation": "Kan være riktig (f.eks. drenering) — "
                                  "bekreft at overvåking ikke er påkrevd.",
                "standard": f"NORSOK I-001 (instrumentering). {_VERIFY}",
            })

    # ---- R2: trip functions without an actuation path -----------------------
    for o in objects:
        if o.type_code not in _TRIP_TYPES or o.tag not in graph:
            continue
        down = nx.descendants(graph, o.tag)
        acts = sorted(t for t in down
                      if by_tag.get(t) and by_tag[t].type_code in _ACTION_TYPES)
        if not acts:
            findings.append({
                "rule": "R2", "title": "Sikkerhetsfunksjon uten aksjonsvei",
                "severity": "høy", "section": "",
                "tags": [o.tag],
                "description": f"{o.tag} ({o.type_code}) har ingen "
                               f"XV/ESV nedstrøms i modellen.",
                "recommendation": "Aksjonen kan ligge i SCD-logikk eller på "
                                  "annet ark — verifiser at funksjonen "
                                  "faktisk utløser en aksjon.",
                "standard": "NORSOK I-005:2013+AC:2016, B.2.3.2 — "
                            "shutdown-funksjoner skal implementeres på SCD "
                            "som logiske forbindelser mellom relevante "
                            "utganger og innganger (parafrasert). "
                            "Klausul verifisert mot standardteksten.",
            })

    order = {"høy": 0, "middels": 1, "lav": 2}
    return sorted(findings, key=lambda f: (order[f["severity"]], f["rule"]))


if __name__ == "__main__":
    import os, sys
    from pathlib import Path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from analysis.hazop_dexpi import load_dexpi_model
    for xml in sorted(Path("data/raw").rglob("*.DGN.xml")):
        m = load_dexpi_model(xml)
        fs = screen(m["tag_graph"], m["objects"], m["sections"])
        if fs:
            print(f"\n{xml.stem.replace('.DGN', '')}: {len(fs)} funn")
            for f in fs[:4]:
                print(f"  [{f['rule']}/{f['severity']}] {f['title']} — "
                      f"{', '.join(f['tags'][:3])}")


# ---------------------------------------------------------------------------
# I-005 Annex B coverage rules: P&ID vs SCD (verified clause references)
# ---------------------------------------------------------------------------
# These clauses were read directly from NORSOK I-005:2013+AC:2016 and are
# PARAPHRASED here (the standard text is copyright protected). References
# below are therefore VERIFIED — unlike the indicative P-001/I-001 pointers
# above. Honest caveat baked into every finding: a tag "missing on the SCD"
# may be a real coverage gap OR a text-layer extraction miss on the SCD
# sheet; the finding is a screening candidate either way.

_MEASURING = None      # category == "input" is the proxy (transmitters etc.)
_ACTUATED_VALVES = {"XV", "ESV", "XY", "PV", "LV", "FV", "HV", "TV"}
_SHUTDOWN_FUNCS = {"LSHH", "PSHH", "LSH", "LSL", "PSH", "FSH"}


def screen_scd_coverage(pid_objects, scd_objects) -> list[dict]:
    """Findings for I-005 Annex B coverage: what the P&ID shows that the
    SCD (extraction) does not. Inputs are EngineeringObject lists from the
    two sources separately."""
    scd_tags = {o.tag for o in scd_objects}
    findings: list[dict] = []

    def _gap(objs, title, rule, clause, paraphrase):
        missing = sorted(o.tag for o in objs if o.tag not in scd_tags)
        if missing:
            findings.append({
                "rule": rule, "title": title, "severity": "middels",
                "section": "P&ID↔SCD", "tags": missing[:8],
                "description": f"{len(missing)} komponenter på P&ID-en "
                               f"gjenfinnes ikke i SCD-uttrekket: "
                               f"{', '.join(missing[:5])}"
                               + (" …" if len(missing) > 5 else "") + ".",
                "recommendation": "Enten reelt dekningsavvik fra klausulen "
                                  "eller uttrekkstap på SCD-arket — "
                                  "verifiser mot SCD-tegningen.",
                "standard": f"NORSOK I-005:2013+AC:2016, {clause} — "
                            f"{paraphrase} (parafrasert). Klausul verifisert "
                            f"mot standardteksten.",
            })

    # B.2.2 gjelder instrumenter MED input til kontrollsystemet — lokale
    # indikatorer (PI/FI/TI/LI/PDI uten transmitter) holdes utenfor for å
    # unngå falske funn; konservativt valg, dokumentert her.
    _LOCAL_ONLY = {"PI", "FI", "TI", "LI", "PDI"}
    _gap([o for o in pid_objects if o.category == "input"
          and o.type_code not in _LOCAL_ONLY],
         "Måleinstrument ikke gjenfunnet på SCD", "R4", "B.2.2",
         "alle måleinstrumenter med input til kontrollsystemet skal vises "
         "på SCD-en")
    _gap([o for o in pid_objects if o.type_code in _ACTUATED_VALVES],
         "Aktuert ventil ikke gjenfunnet på SCD", "R5", "B.2.1.3",
         "fjernopererte ventiler med aktuator, inkl. on/off- og "
         "reguleringsventiler, skal inkluderes på SCD-en")
    _gap([o for o in pid_objects if o.type_code in _SHUTDOWN_FUNCS],
         "Shutdown-funksjon ikke gjenfunnet på SCD", "R6", "B.2.3.2",
         "alle shutdown-funksjoner innen PCS og PSD skal implementeres på "
         "SCD-ene")
    # reguleringsfunksjoner: typekoder som ender på IC (PIC, LIC, FIC, TIC …)
    import re as _re
    _gap([o for o in pid_objects
          if o.type_code and _re.match(r"^[A-Z]{1,3}IC$", o.type_code)],
         "Reguleringsfunksjon ikke gjenfunnet på SCD", "R7", "B.2.3.1",
         "SCD-en skal inkludere alle reguleringsfunksjoner og deres "
         "innbyrdes utveksling av status, målevariabler, forriglinger og "
         "undertrykking")
    return findings