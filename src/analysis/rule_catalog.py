"""
Regelkatalog: flere regler, sporbare klausulreferanser og forslag til tiltak.

Utvider analysis/rule_screening.py UTEN å røre den — `screen()` og
`screen_scd_coverage()` gir bit-identisk resultat som før, så hazop.py,
compliance_dashboard.py og warm_vision_checks.py er upåvirket. Alt nytt
ligger her.

TRE TING DENNE MODULEN GJØR
---------------------------
1. KLAUSULREGISTER MED PROVENIENS. Hver regel må oppgi hvor referansen
   kommer fra, og det finnes ingen vei utenom — `cite()` reiser feil på en
   ukjent proveniens. Tre nivåer, med vilje ubehagelig tydelige:

     verified    klausulteksten er lest i standarden og parafrasert.
                 I-005 Annex B-reglene (R4-R7) er de eneste som har dette
                 i dag, og de ble verifisert av forfatterne av
                 rule_screening.py — ikke av denne modulen.
     indicative  peker på riktig standardfamilie, men klausulnummeret er
                 IKKE verifisert. Må bekreftes før bruk utover screening.
     practice    ingen standardreferanse i det hele tatt. Regelen er
                 utledet av ingeniørlogikk eller av dataene selv, og sier
                 det rett ut.

   Hvorfor så strengt: en oppdiktet klausulreferanse er verre enn ingen
   referanse. Den ser autoritativ ut, og noen handler på den. Katalogen er
   bygget for at den som HAR standarden foran seg kan oppgradere en regel
   fra `indicative` til `verified` ved å fylle inn parafrasen — uten å røre
   kode som utfører sjekken.

2. SJU NYE REGLER (R10-R16) som doblet katalogen. Ingen av dem påstår en
   klausul jeg ikke kan belegge; de er merket `practice` eller
   `indicative` deretter. Tre av dem (R10-R12) ble først mulige da C&E-
   laget kom på plass — de sjekker om den designede logikken henger sammen,
   ikke bare om komponentene finnes.

3. TILTAKSFORSLAG. For hvert funn: hva gjør man med det. Se propose_fixes()
   for hvorfor «sjekk uttrekket» ofte må komme før «endre designet».

    python src/analysis/rule_catalog.py --selftest
    python src/analysis/rule_catalog.py --catalog     # hele registeret
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

if __name__ == "__main__" and __package__ is None:      # direct run support
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx

PROVENANCE = ("verified", "indicative", "practice")

_UNVERIFIED = ("Clause number NOT verified — a discipline engineer must "
               "confirm it.")
_NO_CLAUSE = ("No standard reference — the rule is derived, not cited.")


# ---------------------------------------------------------------------------
# Klausulregister
# ---------------------------------------------------------------------------
# `paraphrase` fylles inn av den som har standarden foran seg. Så lenge den
# står tom, KAN ikke provenance settes til "verified" — cite() håndhever det.

CLAUSES: dict[str, dict] = {
    # --- eksisterende regler i rule_screening.py, registrert med proveniens --
    "R1": {"family": "NORSOK P-001 / API 521", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "pressure protection / relief path"},
    "R2": {"family": "NORSOK S-001 / IEC 61511", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "a shutdown function must act on something"},
    "R3": {"family": "NORSOK P-001", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "pressure monitoring of a section"},
    "R4": {"family": "NORSOK I-005:2013+AC:2016", "clause": "B.2.2",
           "provenance": "verified",
           "paraphrase": "all measuring instruments with an input to the "
                         "control system shall be shown on the SCD",
           "topic": "SCD coverage: measuring instruments"},
    "R5": {"family": "NORSOK I-005:2013+AC:2016", "clause": "B.2.1.3",
           "provenance": "verified",
           "paraphrase": "remotely operated valves with an actuator, "
                         "including on/off and control valves, shall be "
                         "included on the SCD",
           "topic": "SCD coverage: actuated valves"},
    "R6": {"family": "NORSOK I-005:2013+AC:2016", "clause": "B.2.3.2",
           "provenance": "verified",
           "paraphrase": "all shutdown functions within PCS and PSD shall be "
                         "implemented on the SCDs",
           "topic": "SCD coverage: shutdown functions"},
    "R7": {"family": "NORSOK I-005:2013+AC:2016", "clause": "B.2.3.1",
           "provenance": "verified",
           "paraphrase": "the SCD shall include all control functions and "
                         "their mutual exchange of status, measured "
                         "variables, interlocks and suppression",
           "topic": "SCD coverage: control functions"},
    "R8": {"family": "NORSOK I-001 / I-005", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "position feedback from an actuated valve"},
    "R9": {"family": "IEC 61511 / NORSOK I-002", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "redundancy and voting on trips"},

    # --- new rules ----------------------------------------------------------
    "R10": {"family": "NORSOK I-005 (shutdown logic)", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "shutdown valve with no cause in cause & effect"},
    "R11": {"family": "NORSOK I-005 (shutdown logic)", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "trip with no effect in cause & effect"},
    "R12": {"family": "—", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "cause & effect references an unknown tag"},
    "R13": {"family": "NORSOK P-001 / API 521", "clause": "",
            "provenance": "indicative", "paraphrase": "",
            "topic": "relief device without pressure monitoring"},
    "R14": {"family": "NORSOK I-005 / P-002", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "control loop without a final element"},
    "R15": {"family": "IEC 61511 (redundancy)", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "redundancy pair where only one leg is known"},
    "R16": {"family": "NORSOK Z-001 (documentation/tagging)", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "near-duplicate tags (numbering convention)"},
}


def cite(rule: str) -> str:
    """Referansestreng for en regel, med proveniens synlig i teksten.

    Reiser feil hvis en regel er merket `verified` uten faktisk parafrase —
    den kombinasjonen er nettopp den som ville sett troverdig ut og vært
    tom.
    """
    c = CLAUSES.get(rule)
    if not c:
        return f"{rule}: unknown rule in the catalogue."
    prov = c.get("provenance")
    if prov not in PROVENANCE:
        raise ValueError(f"{rule}: invalid provenance {prov!r}")
    if prov == "verified" and not (c.get("clause") and c.get("paraphrase")):
        raise ValueError(f"{rule}: marked 'verified' without clause and paraphrase")
    if prov == "verified":
        return (f"{c['family']}, {c['clause']} — {c['paraphrase']} "
                f"(paraphrased). Clause verified against the standard text.")
    if prov == "indicative":
        return f"{c['family']} ({c['topic']}). {_UNVERIFIED}"
    return f"{c['topic']}. {_NO_CLAUSE}"


def catalog_status() -> dict:
    """Hvor mange regler har verifisert klausul? Tallet hører hjemme i
    rapporten — det sier hvor langt standardarbeidet faktisk er kommet."""
    out = defaultdict(list)
    for rule, c in CLAUSES.items():
        out[c["provenance"]].append(rule)
    return {k: sorted(v, key=lambda r: int(r[1:])) for k, v in out.items()}


# ---------------------------------------------------------------------------
# Nye regler — C&E-avhengige (R10-R12)
# ---------------------------------------------------------------------------

_SHUTDOWN_VALVES = {"XV", "ESV"}
_TRIP_TYPES = {"LSHH", "PSHH", "LSH", "PSH", "LSL", "FSH", "LSLL", "PSLL"}


def screen_cause_effect(objects, ce: dict | None) -> list[dict]:
    """R10-R12: henger den DESIGNEDE logikken sammen?

    Disse ble først mulige da C&E-laget kom. Uten C&E-data returneres
    ingenting — ikke tomme «alt er bra»-funn, som ville vært verre enn å
    tie: en tom sjekk som ser bestått ut er en usann sjekk.
    """
    if not ce or not ce.get("index"):
        return []
    idx = ce["index"]
    effects_of = idx.get("effects_of", {})
    causes_of = idx.get("causes_of", {})
    by_tag = {o.tag: o for o in objects}
    findings: list[dict] = []

    # R10 — nedstengingsventil som ingen trip stenger
    orphan_valves = sorted(
        t for t, o in by_tag.items()
        if o.type_code in _SHUTDOWN_VALVES and not causes_of.get(t))
    if orphan_valves:
        findings.append({
            "rule": "R10", "severity": "high", "section": "C&E",
            "title": "Shutdown valve with no cause in cause & effect",
            "tags": orphan_valves[:8],
            "description": f"{len(orphan_valves)} actuated shutdown valve(s) "
                           f"have no recorded cause that closes them: "
                           f"{', '.join(orphan_valves[:5])}"
                           + (" …" if len(orphan_valves) > 5 else "") + ".",
            "recommendation": "Either the logic is missing from the C&E "
                              "record, or the valve is not part of any "
                              "shutdown function — both need clarifying.",
            "standard": cite("R10"),
        })

    # R11 — trip som ikke gjør noe
    dead_trips = sorted(
        t for t, o in by_tag.items()
        if o.type_code in _TRIP_TYPES and not effects_of.get(t))
    if dead_trips:
        findings.append({
            "rule": "R11", "severity": "high", "section": "C&E",
            "title": "Trip with no recorded effect",
            "tags": dead_trips[:8],
            "description": f"{len(dead_trips)} trip/switch function(s) have "
                           f"no recorded effect: {', '.join(dead_trips[:5])}"
                           + (" …" if len(dead_trips) > 5 else "") + ".",
            "recommendation": "A trip with no effect does nothing. Verify "
                              "against the SCD whether the action is missing "
                              "from the record or from the design.",
            "standard": cite("R11"),
        })

    # R12 — C&E peker på tags som ikke finnes i registeret
    unknown = sorted((ce.get("stats") or {}).get("unknown_tags", []))
    if unknown:
        findings.append({
            "rule": "R12", "severity": "medium", "section": "C&E",
            "title": "Cause & effect references an unknown tag",
            "tags": unknown[:8],
            "description": f"{len(unknown)} tag(s) in the C&E record are not "
                           f"in the tag register: {', '.join(unknown[:5])}"
                           + (" …" if len(unknown) > 5 else "") + ".",
            "recommendation": "Either a typo on the C&E sheet, a tag the "
                              "extraction missed, or a genuine "
                              "cross-document inconsistency.",
            "standard": cite("R12"),
        })
    return findings


# ---------------------------------------------------------------------------
# Nye regler — strukturelle (R13-R15) og datakvalitet (R16)
# ---------------------------------------------------------------------------

_RELIEF_TYPES = {"PSV", "PSE"}
_PRESSURE_MEAS = {"PT", "PI", "PIT", "PDI", "PDT", "PIC"}
_FINAL_ELEMENTS = {"XV", "ESV", "ZV", "FV", "LV", "PV", "TV", "HV", "FO"}
_CONTROLLER_RE = re.compile(r"^[A-Z]{1,3}IC$")


def screen_structure(graph: nx.DiGraph, objects, sections: dict) -> list[dict]:
    """R13-R15 over én tegnings DEXPI-modell."""
    by_tag = {o.tag: o for o in objects}
    findings: list[dict] = []

    # R13 — avlastningsenhet uten trykkmåling i samme seksjon
    for name, members in (sections or {}).items():
        relief = sorted(o.tag for o in members if o.type_code in _RELIEF_TYPES)
        meas = [o.tag for o in members if o.type_code in _PRESSURE_MEAS]
        if relief and not meas:
            findings.append({
                "rule": "R13", "severity": "medium", "section": name,
                "title": "Relief device without pressure monitoring in the section",
                "tags": relief[:6],
                "description": f"The section has relief "
                               f"({', '.join(relief[:4])}) but no pressure "
                               f"measurement among its members.",
                "recommendation": "Without pressure indication the operator "
                                  "cannot see the set point approaching, and "
                                  "that the relief has lifted must be "
                                  "inferred indirectly.",
                "standard": cite("R13"),
            })

    # R14 — reguleringssløyfe uten pådragsorgan
    loops: dict[str, list] = defaultdict(list)
    for o in objects:
        loops[getattr(o, "loop", o.tag)].append(o)
    orphan_ctrl = []
    for loop, members in loops.items():
        ctrl = [o.tag for o in members
                if o.type_code and _CONTROLLER_RE.match(o.type_code)]
        if not ctrl:
            continue
        final = [o for o in members if o.type_code in _FINAL_ELEMENTS]
        if final:
            continue
        # utvid til nedstrøms i grafen før vi kaller det et funn
        downstream = set()
        for t in ctrl:
            if t in graph:
                downstream |= set(nx.descendants(graph, t))
        if any(by_tag.get(d) and by_tag[d].type_code in _FINAL_ELEMENTS
               for d in downstream):
            continue
        orphan_ctrl += ctrl
    if orphan_ctrl:
        findings.append({
            # NB: "section" is part of finding_id() — keep the stored value
            # stable so saved review dispositions keep matching. It is an id,
            # not display text (the UI never shows it).
            "rule": "R14", "severity": "medium", "section": "sløyfe",
            "title": "Control function without a final element",
            "tags": sorted(orphan_ctrl)[:8],
            "description": f"{len(orphan_ctrl)} control function(s) have "
                           f"neither a valve in their own loop nor one "
                           f"downstream in the graph: "
                           f"{', '.join(sorted(orphan_ctrl)[:5])}.",
            "recommendation": "A controller with nothing to act on cannot do "
                              "anything. Often a lost connection in the "
                              "extraction — verify on the drawing before "
                              "treating it as a design deviation.",
            "standard": cite("R14"),
        })

    # R15 — redundanspar der bare ett bein er kjent
    stems: dict[tuple, set] = defaultdict(set)
    for o in objects:
        if o.type_code and o.number:
            stems[(o.system, o.type_code, o.number)].add(o.suffix or "")
    lonely = sorted(
        f"{s}-{tc}{num}{next(iter(sfx))}"
        for (s, tc, num), sfx in stems.items()
        if len(sfx) == 1 and next(iter(sfx)) in {"A", "B", "C", "D"})
    if lonely:
        findings.append({
            "rule": "R15", "severity": "low", "section": "redundans",  # id, see R14
            "title": "Redundancy leg with no sibling in the extraction",
            "tags": lonely[:8],
            "description": f"{len(lonely)} tag(s) carry a redundancy suffix "
                           f"(A/B) but the sibling leg is absent: "
                           f"{', '.join(lonely[:5])}"
                           + (" …" if len(lonely) > 5 else "") + ".",
            "recommendation": "Either the sibling leg was lost in the "
                              "extraction, or the suffix is used without "
                              "redundancy being present. Also affects alarm "
                              "point matching.",
            "standard": cite("R15"),
        })
    return findings


_NUM_FIRST_TAG = re.compile(r"^\d{2}-\d{2,4}[A-Z]{1,4}$")


def _difference_kind(tags: set[str]) -> str:
    """Hva skiller skrivemåtene? Beskrivelsen må stemme med funnet.

    Første versjon antok at duplikater alltid skyldtes ledende nuller
    (LSL548/LSL0548). Anleggsdekkende kjøring fant 20-2003PT/20-PT2003 —
    samme instrument, men nummer-først mot type-først. Et funn som forklarer
    seg selv feil er verre enn et uforklart funn, så typen utledes nå.
    """
    ts = sorted(tags)
    if any(_NUM_FIRST_TAG.match(t) for t in ts) and \
       any(not _NUM_FIRST_TAG.match(t) for t in ts):
        return "nummer-først vs type-først"
    bare = {re.sub(r"[\s\-]", "", t) for t in ts}
    if len({b.lstrip("0") for b in bare}) < len(bare):
        return "leading zeros"
    if len({re.sub(r"[\s\-]", "", t) for t in ts}) < len(ts):
        return "separator/whitespace"
    return "different spelling"


def screen_tag_conventions(objects) -> list[dict]:
    """R16 — nær-duplikate tags.

    Mønsteret finnes i dette datasettet: 27-LSL548 og 27-LSL0548 er samme
    instrument skrevet på to måter, og telles som to. Det ødelegger både
    tellinger og enhver kobling mot et driftssystem.
    """
    groups: dict[tuple, set] = defaultdict(set)
    for o in objects:
        if o.type_code and o.number:
            # normaliser bort ledende nuller i nummeret
            groups[(o.system, o.type_code, o.number.lstrip("0") or "0",
                    o.suffix or "")].add(o.tag)
    dupes = sorted(g for g in groups.values() if len(g) > 1)
    if not dupes:
        return []
    pairs = [f"{'/'.join(sorted(g))} ({_difference_kind(g)})" for g in dupes]
    return [{
        "rule": "R16", "severity": "medium", "section": "merking",  # id, see R14
        "title": "Near-duplicate tags (same instrument, different spelling)",
        "tags": sorted({t for g in dupes for t in g})[:8],
        "description": f"{len(dupes)} tag pair(s) point at the same "
                       f"instrument with different spellings: "
                       f"{'; '.join(pairs[:4])}"
                       + (" …" if len(pairs) > 4 else "") + ".",
        "recommendation": "The same instrument counted twice. Decide which "
                          "spelling is correct and fix the source — this "
                          "distorts counts, reconciliation and alarm "
                          "matching.",
        "standard": cite("R16"),
    }]


def screen_extended(graph, objects, sections, ce: dict | None = None) -> list[dict]:
    """Alle nye regler samlet. Kaller IKKE rule_screening.screen() — den
    beholdes uendret, og kalleren kombinerer om den vil ha begge."""
    return (screen_structure(graph, objects, sections)
            + screen_tag_conventions(objects)
            + screen_cause_effect(objects, ce))


# Regler som MÅ kjøres på det sammenslåtte registeret, ikke per ark.
# Funnet den harde veien: R15 og R16 ga null per tegning og traff først
# anleggsdekkende, fordi søskenbeinet eller duplikatet ligger på et ANNET ark.
# En kryss-tegnings-regel kjørt per ark underrapporterer stille, som er den
# verste feilmodusen en samsvarssjekk kan ha — den ser bestått ut.
PLANT_WIDE_RULES = {"R15", "R16"}


def screen_all_extended(raw_dir, ce: dict | None = None) -> list[dict]:
    """Alle regler over hele tegningsbunken, hver merket med tegning + system.

    Per ark: rule_screening.screen() (R1-R3, R8-R9) + de nye strukturelle og
    C&E-reglene. Anleggsdekkende: R15/R16 én gang over den sammenslåtte
    modellen, merket med drawing='(anleggsdekkende)' så opprullingen ikke
    tilskriver dem et vilkårlig ark.
    """
    import re as _re
    from pathlib import Path as _P
    from analysis.hazop_dexpi import load_dexpi_model
    from analysis.rule_screening import screen, dedupe

    def _system_of(f):
        for t in f.get("tags", []):
            mm = _re.match(r"^(\d{2})", str(t))
            if mm:
                return mm.group(1)
        return "?"

    rows: list[dict] = []
    for xml in sorted(_P(raw_dir).rglob("*.DGN.xml")):
        try:
            m = load_dexpi_model(xml)
            per_sheet = dedupe(
                screen(m["tag_graph"], m["objects"], m["sections"])
                + screen_structure(m["tag_graph"], m["objects"], m["sections"])
                + screen_cause_effect(m["objects"], ce))
        except Exception:                                   # noqa: BLE001
            continue
        stem = xml.stem.replace(".DGN", "")
        for f in per_sheet:
            if f["rule"] in PLANT_WIDE_RULES:
                continue                     # håndteres anleggsdekkende under
            rows.append({**f, "drawing": stem, "system": _system_of(f)})

    try:
        from analysis.plant_model import build_plant_model
        pm = build_plant_model(raw_dir)
        wide = (screen_tag_conventions(pm["objects"])
                + [f for f in screen_structure(pm["graph"], pm["objects"], {})
                   if f["rule"] in PLANT_WIDE_RULES])
        for f in wide:
            rows.append({**f, "drawing": "(anleggsdekkende)",
                         "system": _system_of(f)})
    except Exception:                                       # noqa: BLE001
        pass                                 # anleggsmodell er valgfri
    return rows


# ---------------------------------------------------------------------------
# Tiltaksforslag
# ---------------------------------------------------------------------------

FIX_KINDS = {
    "extraction": "🔍 Verify the extraction",
    "design": "🔧 Design / drawing action",
    "deliverable": "📦 Deliverable requirement",
}

# Rekkefølgen er ikke kosmetikk. For funn utledet av PDF-uttrekk må
# «sjekk om vi bare bommet» komme FØRST: prosjektet har målt 55 % recall, og
# fraværet av en linje kan ikke skilles fra et uttrekkstap. Å foreslå en
# designendring først ville sendt en ingeniør ut på jakt etter et problem som
# kanskje ikke finnes.
_ORDER = {"extraction": 0, "design": 1, "deliverable": 2}

_FIXES: dict[str, list[tuple[str, str]]] = {
    "R1": [("extraction", "Check whether a PSV/PSE is on the drawing but "
                          "absent from the extraction (a symbol with no "
                          "readable tag is common)."),
           ("design", "If there genuinely is no relief path: establish "
                      "whether the section can be over-pressured from the "
                      "source, and document the decision.")],
    "R2": [("extraction", "Check whether the action path exists on the SCD — "
                          "cross-drawing links are the weakest part of the "
                          "extraction."),
           ("design", "Trip with nothing to act on: establish which element "
                      "it should actuate, and record it in cause & effect.")],
    "R3": [("extraction", "Pressure measurement may be drawn as a symbol "
                          "with no tag."),
           ("design", "Section without pressure monitoring: consider "
                      "indication, especially if the section can be "
                      "isolated.")],
    "R4": [("extraction", "The SCD sheet may have no readable text layer — "
                          "roughly two thirds do not. Run the vision reserve "
                          "first."),
           ("design", "A real coverage gap against I-005 B.2.2: the "
                      "instrument shall be shown on the SCD."),
           ("deliverable", "Require the SCD delivered with a machine-readable "
                           "text layer, or in a structured format.")],
    "R5": [("extraction", "Same SCD text-layer problem as R4."),
           ("design", "A real coverage gap against I-005 B.2.1.3."),
           ("deliverable", "Require the SCD delivered machine-readable.")],
    "R6": [("extraction", "Same SCD text-layer problem as R4."),
           ("design", "A real coverage gap against I-005 B.2.3.2 — the "
                      "shutdown function shall be implemented on the SCD.")],
    "R7": [("extraction", "Same SCD text-layer problem as R4."),
           ("design", "A real coverage gap against I-005 B.2.3.1.")],
    "R8": [("extraction", "ZS/ZL may be drawn without a readable tag."),
           ("design", "Valve without position feedback: the safety logic "
                      "cannot confirm the valve reached position.")],
    "R9": [("extraction", "The sibling sensor may be missing from the "
                          "extraction — see R15."),
           ("design", "A single sensor leg on a trip: establish whether the "
                      "SIL requirement presumes voting.")],
    "R10": [("design", "Record which cause closes the valve, or confirm that "
                       "it is not part of a shutdown."),
            ("deliverable", "Require cause & effect delivered in "
                            "machine-readable form, not only as a field on "
                            "the sheet.")],
    "R11": [("design", "Trip with no effect: find the action on the SCD and "
                       "record it, or establish whether the trip is out of "
                       "service."),
            ("deliverable", "Same C&E deliverable requirement as R10.")],
    "R12": [("extraction", "The tag may be on the drawing but missing from "
                           "the extraction — check before calling it a "
                           "typo."),
            ("design", "Correct the typo on the C&E sheet, or resolve the "
                       "cross-document inconsistency.")],
    "R13": [("extraction", "Pressure measurement may be missing from the "
                           "extraction."),
            ("design", "Consider pressure indication in sections that have "
                       "relief.")],
    "R14": [("extraction", "The controller→valve link is the one most often "
                           "broken in the extraction — verify on the "
                           "drawing."),
            ("design", "Controller with nothing to act on: establish which "
                       "element it controls.")],
    "R15": [("extraction", "The sibling leg was probably lost in the "
                           "extraction (measured recall 55 %) — check the "
                           "drawing first."),
            ("design", "Only one leg present: establish whether the suffix "
                       "is used without redundancy being there."),
            ("deliverable", "Consistent suffix use is a minimum requirement "
                            "for linking to an operations/alarm system.")],
    "R16": [("design", "Decide which spelling is correct and fix the "
                       "source."),
            ("deliverable", "Require an unambiguous tag convention in the "
                            "deliverable — leading zeros must be "
                            "consistent.")],
}


def propose_fixes(finding: dict, source: str = "dexpi") -> list[dict]:
    """Konkrete tiltak for ett funn: [{kind, label, action, tags}].

    Tre prinsipper, alle med en grunn:

    * ALDRI ET OPPFUNNET TAG. Et forslag beskriver en HANDLING og forankrer
      den i taggene funnet allerede har. «Legg til PSV-4811» ville vært en
      hallusinasjon med ventilnummer.
    * UTTREKKSSJEKK FØRST når kilden er PDF. Fraværet av en linje kan ikke
      skilles fra et uttrekkstap ved 55 % recall, så «kanskje vi bare bommet»
      er den billigste og oftest riktige hypotesen.
    * FORSLAG, IKKE VEDTAK. Ingenting anvendes automatisk; dette er input til
      finding_disposition, der en ingeniør avgjør.
    """
    rule = finding.get("rule", "")
    tags = list(finding.get("tags", []))[:6]
    out = []
    for kind, action in _FIXES.get(rule, []):
        out.append({"kind": kind, "label": FIX_KINDS[kind],
                    "action": action, "tags": tags})
    # DEXPI-funn: strukturen er oppgitt, så uttrekkshypotesen er svakere
    # (men ikke borte — utagget utstyr finnes også i eksporten)
    key = (lambda f: (_ORDER[f["kind"]] + (1 if source == "dexpi"
                                           and f["kind"] == "extraction" else 0.5),))
    return sorted(out, key=key)


def format_fixes(finding: dict, source: str = "dexpi") -> str:
    fx = propose_fixes(finding, source)
    if not fx:
        return "  (ingen forhåndsdefinerte tiltak for denne regelen)"
    lines = []
    for f in fx:
        lines.append(f"  {f['label']}: {f['action']}")
    lines.append(f"  Forslag til gjennomgang — ikke vedtak. Tags: "
                 f"{', '.join(fx[0]['tags']) or '—'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Selvtest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    from models.engineering_object import EngineeringObject as E

    objs = [E.from_tag(t, "SCD") for t in [
        "27-XV4813", "27-XV4814", "27-PSHH4811", "27-PSV4809",
        "27-PIC4801", "27-PT4801", "27-LSL548", "27-LSL0548",
        "27-PT4552B", "24-PI2200A", "24-PI2200B"]]
    by_tag = {o.tag: o for o in objs}
    g = nx.DiGraph()
    g.add_edge("27-PT4801", "27-PIC4801")          # regulator uten ventil
    sections = {"27-sek": [by_tag["27-PSV4809"]]}  # avlastning, ingen måling

    ce = {"index": {"effects_of": {"27-PSHH4811": [{"effect": "27-XV4813"}]},
                    "causes_of": {"27-XV4813": [{"cause": "27-PSHH4811"}]}},
          "stats": {"unknown_tags": ["27-PSHH9999"]}}

    st = screen_structure(g, objs, sections)
    tc = screen_tag_conventions(objs)
    ceF = screen_cause_effect(objs, ce)
    rules = {f["rule"] for f in st + tc + ceF}

    checks = [
        ("R13 avlastning uten trykkmåling", "R13" in rules),
        ("R14 regulator uten pådrag", "R14" in rules),
        ("R15 enslig redundansbein (27-PT4552B)", "R15" in rules),
        ("R16 nær-duplikat (LSL548/LSL0548)", "R16" in rules),
        ("R10 ventil uten årsak (27-XV4814)", "R10" in rules),
        # LSL548/LSL0548 er trip-typer uten registrert effekt, så R11 SKAL
        # utløse — men den må ikke ta med 27-PSHH4811, som har en effekt
        ("R11 utløser på trip uten effekt", "R11" in rules),
        ("R11 tar ikke med en trip som HAR effekt",
         all("27-PSHH4811" not in f.get("tags", [])
             for f in ceF if f["rule"] == "R11")),
        ("R12 ukjent C&E-tag", "R12" in rules),
        ("A/B-par med begge bein gir ikke R15",
         all("24-PI2200A" not in f.get("tags", [])
             for f in st if f["rule"] == "R15")),
        ("uten C&E-data gir ingen C&E-funn",
         screen_cause_effect(objs, None) == []),
    ]

    # klausulregisteret
    checks.append(("alle regler har gyldig proveniens",
                   all(c["provenance"] in PROVENANCE for c in CLAUSES.values())))
    checks.append(("verifiserte regler har klausul OG parafrase",
                   all(c["clause"] and c["paraphrase"]
                       for c in CLAUSES.values()
                       if c["provenance"] == "verified")))
    checks.append(("cite() merker uverifisert som uverifisert",
                   _UNVERIFIED in cite("R1")))
    checks.append(("cite() merker practice som uten referanse",
                   _NO_CLAUSE in cite("R16")))
    checks.append(("cite() på verifisert gir klausulnummer",
                   "B.2.2" in cite("R4")))
    # håndhevelsen: 'verified' uten parafrase skal reise feil
    CLAUSES["__test__"] = {"family": "X", "clause": "1.1",
                           "provenance": "verified", "paraphrase": "",
                           "topic": "t"}
    try:
        cite("__test__")
        enforced = False
    except ValueError:
        enforced = True
    finally:
        del CLAUSES["__test__"]
    checks.append(("tom 'verified' avvises av cite()", enforced))

    # tiltaksforslag
    f_pdf = {"rule": "R4", "tags": ["27-PT4805"]}
    fx = propose_fixes(f_pdf, source="pdf")
    checks.append(("PDF-funn: uttrekkssjekk kommer først",
                   fx and fx[0]["kind"] == "extraction"))
    checks.append(("forslag forankres i funnets egne tags",
                   all(x["tags"] == ["27-PT4805"] for x in fx)))
    checks.append(("alle regler i katalogen har tiltak",
                   all(r in _FIXES for r in CLAUSES)))
    checks.append(("ingen tiltakstekst finner opp et tag",
                   not any(re.search(r"\b\d{2}-[A-Z]{2,4}\d{3,4}\b", a)
                           for lst in _FIXES.values() for _, a in lst)))

    ok = True
    for name, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok &= bool(passed)
    print(f"\n  katalogstatus: "
          + ", ".join(f"{k}={len(v)}" for k, v in sorted(catalog_status().items())))
    return 0 if ok else 1


def _print_catalog() -> int:
    st = catalog_status()
    print(f"{len(CLAUSES)} regler i katalogen\n")
    for prov in PROVENANCE:
        rules = st.get(prov, [])
        print(f"  {prov.upper()} ({len(rules)}):")
        for r in rules:
            c = CLAUSES[r]
            ref = f"{c['family']} {c['clause']}".strip()
            print(f"    {r:4} {c['topic']:52} {ref}")
        print()
    print("  'indicative' må verifiseres mot standardteksten før bruk utover\n"
          "  screening; 'practice' har ingen klausul og påstår ikke å ha det.\n"
          "  Fyll inn clause + paraphrase og sett provenance='verified' for å\n"
          "  oppgradere — cite() nekter tomme verifiserte referanser.")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--catalog":
        sys.exit(_print_catalog())
    if a and a[0] == "--selftest":
        sys.exit(_selftest())
    sys.exit("bruk: python src/analysis/rule_catalog.py --selftest | --catalog")
