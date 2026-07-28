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

_UNVERIFIED = "Klausulnummer IKKE verifisert — fagingeniør må bekrefte."
_NO_CLAUSE = "Ingen standardreferanse — regelen er utledet, ikke sitert."


# ---------------------------------------------------------------------------
# Klausulregister
# ---------------------------------------------------------------------------
# `paraphrase` fylles inn av den som har standarden foran seg. Så lenge den
# står tom, KAN ikke provenance settes til "verified" — cite() håndhever det.

CLAUSES: dict[str, dict] = {
    # --- eksisterende regler i rule_screening.py, registrert med proveniens --
    "R1": {"family": "NORSOK P-001 / API 521", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "trykkbeskyttelse / avlastningsvei"},
    "R2": {"family": "NORSOK S-001 / IEC 61511", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "nedstengingsfunksjon skal ha pådrag"},
    "R3": {"family": "NORSOK P-001", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "trykkovervåking av seksjon"},
    "R4": {"family": "NORSOK I-005:2013+AC:2016", "clause": "B.2.2",
           "provenance": "verified",
           "paraphrase": "alle måleinstrumenter med input til "
                         "kontrollsystemet skal vises på SCD-en",
           "topic": "SCD-dekning: måleinstrumenter"},
    "R5": {"family": "NORSOK I-005:2013+AC:2016", "clause": "B.2.1.3",
           "provenance": "verified",
           "paraphrase": "fjernopererte ventiler med aktuator, inkl. on/off- "
                         "og reguleringsventiler, skal inkluderes på SCD-en",
           "topic": "SCD-dekning: aktuerte ventiler"},
    "R6": {"family": "NORSOK I-005:2013+AC:2016", "clause": "B.2.3.2",
           "provenance": "verified",
           "paraphrase": "alle shutdown-funksjoner innen PCS og PSD skal "
                         "implementeres på SCD-ene",
           "topic": "SCD-dekning: nedstengingsfunksjoner"},
    "R7": {"family": "NORSOK I-005:2013+AC:2016", "clause": "B.2.3.1",
           "provenance": "verified",
           "paraphrase": "SCD-en skal inkludere alle reguleringsfunksjoner "
                         "og deres innbyrdes utveksling av status, "
                         "målevariabler, forriglinger og undertrykking",
           "topic": "SCD-dekning: reguleringsfunksjoner"},
    "R8": {"family": "NORSOK I-001 / I-005", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "posisjonstilbakemelding fra aktuert ventil"},
    "R9": {"family": "IEC 61511 / NORSOK I-002", "clause": "",
           "provenance": "indicative", "paraphrase": "",
           "topic": "redundans og stemmegivning på trip"},

    # --- nye regler ---------------------------------------------------------
    "R10": {"family": "NORSOK I-005 (nedstengingslogikk)", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "nedstengingsventil uten årsak i cause & effect"},
    "R11": {"family": "NORSOK I-005 (nedstengingslogikk)", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "trip uten effekt i cause & effect"},
    "R12": {"family": "—", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "cause & effect refererer ukjent tag"},
    "R13": {"family": "NORSOK P-001 / API 521", "clause": "",
            "provenance": "indicative", "paraphrase": "",
            "topic": "avlastningsenhet uten trykkovervåking"},
    "R14": {"family": "NORSOK I-005 / P-002", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "reguleringssløyfe uten pådragsorgan"},
    "R15": {"family": "IEC 61511 (redundans)", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "redundanspar der bare ett bein er kjent"},
    "R16": {"family": "NORSOK Z-001 (dokumentasjon/merking)", "clause": "",
            "provenance": "practice", "paraphrase": "",
            "topic": "nær-duplikate tags (nummerkonvensjon)"},
}


def cite(rule: str) -> str:
    """Referansestreng for en regel, med proveniens synlig i teksten.

    Reiser feil hvis en regel er merket `verified` uten faktisk parafrase —
    den kombinasjonen er nettopp den som ville sett troverdig ut og vært
    tom.
    """
    c = CLAUSES.get(rule)
    if not c:
        return f"{rule}: ukjent regel i katalogen."
    prov = c.get("provenance")
    if prov not in PROVENANCE:
        raise ValueError(f"{rule}: ugyldig proveniens {prov!r}")
    if prov == "verified" and not (c.get("clause") and c.get("paraphrase")):
        raise ValueError(f"{rule}: merket 'verified' uten klausul og parafrase")
    if prov == "verified":
        return (f"{c['family']}, {c['clause']} — {c['paraphrase']} "
                f"(parafrasert). Klausul verifisert mot standardteksten.")
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
            "rule": "R10", "severity": "høy", "section": "C&E",
            "title": "Nedstengingsventil uten årsak i cause & effect",
            "tags": orphan_valves[:8],
            "description": f"{len(orphan_valves)} aktuert nedstengingsventil "
                           f"har ingen registrert årsak som stenger den: "
                           f"{', '.join(orphan_valves[:5])}"
                           + (" …" if len(orphan_valves) > 5 else "") + ".",
            "recommendation": "Enten mangler logikken i C&E-registreringen, "
                              "eller ventilen inngår ikke i noen "
                              "nedstengingsfunksjon — begge deler bør avklares.",
            "standard": cite("R10"),
        })

    # R11 — trip som ikke gjør noe
    dead_trips = sorted(
        t for t, o in by_tag.items()
        if o.type_code in _TRIP_TYPES and not effects_of.get(t))
    if dead_trips:
        findings.append({
            "rule": "R11", "severity": "høy", "section": "C&E",
            "title": "Trip uten registrert effekt",
            "tags": dead_trips[:8],
            "description": f"{len(dead_trips)} trip-/bryterfunksjon har ingen "
                           f"registrert effekt: {', '.join(dead_trips[:5])}"
                           + (" …" if len(dead_trips) > 5 else "") + ".",
            "recommendation": "En trip uten effekt gjør ingenting. Verifiser "
                              "mot SCD-en om aksjonen mangler i registreringen "
                              "eller i designet.",
            "standard": cite("R11"),
        })

    # R12 — C&E peker på tags som ikke finnes i registeret
    unknown = sorted((ce.get("stats") or {}).get("unknown_tags", []))
    if unknown:
        findings.append({
            "rule": "R12", "severity": "middels", "section": "C&E",
            "title": "Cause & effect refererer ukjent tag",
            "tags": unknown[:8],
            "description": f"{len(unknown)} tag i C&E-registreringen finnes "
                           f"ikke i tag-registeret: {', '.join(unknown[:5])}"
                           + (" …" if len(unknown) > 5 else "") + ".",
            "recommendation": "Enten en skrivefeil i C&E-arket, et tag "
                              "uttrekket ikke fanget, eller en reell "
                              "kryssdokument-inkonsistens.",
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
                "rule": "R13", "severity": "middels", "section": name,
                "title": "Avlastningsenhet uten trykkovervåking i seksjonen",
                "tags": relief[:6],
                "description": f"Seksjonen har avlastning "
                               f"({', '.join(relief[:4])}) men ingen "
                               f"trykkmåling blant medlemmene.",
                "recommendation": "Uten trykkindikering ser operatøren ikke at "
                                  "settpunktet nærmer seg, og at avlastningen "
                                  "har løftet må utledes indirekte.",
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
            "rule": "R14", "severity": "middels", "section": "sløyfe",
            "title": "Reguleringsfunksjon uten pådragsorgan",
            "tags": sorted(orphan_ctrl)[:8],
            "description": f"{len(orphan_ctrl)} reguleringsfunksjon har verken "
                           f"ventil i egen sløyfe eller nedstrøms i grafen: "
                           f"{', '.join(sorted(orphan_ctrl)[:5])}.",
            "recommendation": "En regulator uten pådrag kan ikke gjøre noe. "
                              "Ofte et koblingstap i uttrekket — verifiser på "
                              "tegningen før det behandles som designavvik.",
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
            "rule": "R15", "severity": "lav", "section": "redundans",
            "title": "Redundansbein uten søsken i uttrekket",
            "tags": lonely[:8],
            "description": f"{len(lonely)} tag har et redundanssuffiks (A/B) "
                           f"men søskenbeinet finnes ikke: "
                           f"{', '.join(lonely[:5])}"
                           + (" …" if len(lonely) > 5 else "") + ".",
            "recommendation": "Enten er søskenbeinet tapt i uttrekket, eller "
                              "suffikset er brukt uten at redundans finnes. "
                              "Påvirker også alarm-punktkobling.",
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
        return "ledende nuller"
    if len({re.sub(r"[\s\-]", "", t) for t in ts}) < len(ts):
        return "separator/mellomrom"
    return "ulik skrivemåte"


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
        "rule": "R16", "severity": "middels", "section": "merking",
        "title": "Nær-duplikate tags (samme instrument, ulik skrivemåte)",
        "tags": sorted({t for g in dupes for t in g})[:8],
        "description": f"{len(dupes)} tag-par peker på samme instrument med "
                       f"ulik skrivemåte: {'; '.join(pairs[:4])}"
                       + (" …" if len(pairs) > 4 else "") + ".",
        "recommendation": "Samme instrument talt som to. Avklar hvilken "
                          "skrivemåte som er riktig og rett kilden — dette "
                          "slår ut i tellinger, avstemming og alarmkobling.",
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
    "extraction": "🔍 Verifiser uttrekket",
    "design": "🔧 Design-/tegningstiltak",
    "deliverable": "📦 Leveransekrav",
}

# Rekkefølgen er ikke kosmetikk. For funn utledet av PDF-uttrekk må
# «sjekk om vi bare bommet» komme FØRST: prosjektet har målt 55 % recall, og
# fraværet av en linje kan ikke skilles fra et uttrekkstap. Å foreslå en
# designendring først ville sendt en ingeniør ut på jakt etter et problem som
# kanskje ikke finnes.
_ORDER = {"extraction": 0, "design": 1, "deliverable": 2}

_FIXES: dict[str, list[tuple[str, str]]] = {
    "R1": [("extraction", "Sjekk om PSV/PSE finnes på tegningen men mangler i "
                          "uttrekket (symbol uten lesbart tag er vanlig)."),
           ("design", "Finnes ingen avlastningsvei: avklar om seksjonen kan "
                      "overtrykkes fra kilden, og dokumenter beslutningen.")],
    "R2": [("extraction", "Sjekk om aksjonsveien finnes på SCD-en — "
                          "kryss-tegningskoblinger er de svakeste i uttrekket."),
           ("design", "Trip uten pådrag: avklar hvilket element den skal "
                      "aktuere, og registrer det i cause & effect.")],
    "R3": [("extraction", "Trykkmåling kan være tegnet som symbol uten tag."),
           ("design", "Seksjon uten trykkovervåking: vurder indikering, "
                      "særlig hvis seksjonen kan isoleres.")],
    "R4": [("extraction", "SCD-arket kan mangle lesbart tekstlag — omtrent to "
                          "tredjedeler gjør det. Kjør vision-reserven først."),
           ("design", "Reelt dekningsavvik mot I-005 B.2.2: instrumentet skal "
                      "vises på SCD-en."),
           ("deliverable", "Krev SCD levert med maskinlesbart tekstlag eller "
                           "som strukturert format.")],
    "R5": [("extraction", "Samme SCD-tekstlagsproblem som R4."),
           ("design", "Reelt dekningsavvik mot I-005 B.2.1.3."),
           ("deliverable", "Krev SCD levert maskinlesbart.")],
    "R6": [("extraction", "Samme SCD-tekstlagsproblem som R4."),
           ("design", "Reelt dekningsavvik mot I-005 B.2.3.2 — "
                      "nedstengingsfunksjonen skal implementeres på SCD.")],
    "R7": [("extraction", "Samme SCD-tekstlagsproblem som R4."),
           ("design", "Reelt dekningsavvik mot I-005 B.2.3.1.")],
    "R8": [("extraction", "ZS/ZL kan være tegnet uten lesbart tag."),
           ("design", "Ventil uten posisjonstilbakemelding: sikkerhetslogikken "
                      "kan ikke bekrefte at ventilen nådde stilling.")],
    "R9": [("extraction", "Søskensensoren kan mangle i uttrekket — se R15."),
           ("design", "Enkelt sensorbein på en trip: avklar om SIL-kravet "
                      "forutsetter stemmegivning.")],
    "R10": [("design", "Registrer hvilken årsak som stenger ventilen, eller "
                       "bekreft at den ikke inngår i nedstenging."),
            ("deliverable", "Krev cause & effect levert i maskinlesbar form, "
                            "ikke bare som felt på arket.")],
    "R11": [("design", "Trip uten effekt: finn aksjonen på SCD-en og registrer "
                       "den, eller avklar om trippen er ute av bruk."),
            ("deliverable", "Samme C&E-leveransekrav som R10.")],
    "R12": [("extraction", "Taggen kan finnes på tegningen men mangle i "
                           "uttrekket — sjekk før det kalles en skrivefeil."),
            ("design", "Rett skrivefeilen i C&E-arket, eller avklar "
                       "kryssdokument-inkonsistensen.")],
    "R13": [("extraction", "Trykkmåling kan mangle i uttrekket."),
            ("design", "Vurder trykkindikering i seksjoner med avlastning.")],
    "R14": [("extraction", "Koblingen regulator→ventil er den som oftest "
                           "brytes i uttrekket — verifiser på tegningen."),
            ("design", "Regulator uten pådrag: avklar hvilket element den "
                       "styrer.")],
    "R15": [("extraction", "Søskenbeinet er sannsynligvis tapt i uttrekket "
                           "(målt recall 55 %) — sjekk tegningen først."),
            ("design", "Finnes bare ett bein: avklar om suffikset er brukt "
                       "uten at redundans finnes."),
            ("deliverable", "Konsekvent suffiksbruk er et minimumskrav for "
                            "kobling mot drifts-/alarmsystem.")],
    "R16": [("design", "Avklar hvilken skrivemåte som er riktig og rett "
                       "kilden."),
            ("deliverable", "Krev entydig tag-konvensjon i leveransen — "
                            "ledende nuller må være konsistente.")],
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
