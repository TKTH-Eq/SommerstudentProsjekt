"""
Alarm-/sensorpunkt  ->  tegningstag. Broen oppgavens spørsmål 2 spør etter.

*Kan P&ID/SCD-logikk kobles til sensor- eller alarmdata for rotårsaksanalyse
i drift?* Prosjektet har begge endene: den sammenslåtte anleggsgrafen med
designet C&E-logikk, og en rotårsaksmotor som er målt (hit1 100 % ideelt,
94 % med 40 % tapte alarmer). Det som manglet er selve SKJØTEN — og det er
der ekte integrasjoner faktisk ryker.

Et alarmpunkt i SAS/IMS/historian heter sjelden det tegningen kaller det:

    27PT4805            separatorer droppet
    27-PT-4805          ekstra bindestrek
    HO27_PT_4805        anleggsprefiks + understrek
    27PT4805.PV         attributtsuffiks
    TAG:27-PT4805:PV    kildeprefiks OG attributt
    27PT4805.PAHH       alarmpunktet PÅ instrumentet
    27-4561PV           nummer-først (finnes i dette datasettet)

Tegningen sier `27-PT4805`. Uten en oppløser er kjeden brutt uansett hvor
god grafen er.

DESIGNPOSISJON — dette er et sikkerhetskritisk oppslag, så modulen GJETTER
ALDRI. Der et punktnavn peker på flere registertags (typisk A/B-redundans)
returneres `ambiguous` med kandidatene, ikke et valg. En feilkobling er
verre enn en manglende kobling: den flytter en alarm til feil sted i grafen
og gir rotårsaksmotoren feil premiss.

Tre regler holder den ærlig:

  * REDUNDANSBEIN BÆRER IDENTITET. 27-PI4805A og 27-PI4805B er to
    instrumenter. Suffiks A/B/C/D foldes aldri bort.
  * SYSTEMPREFIKS BÆRER IDENTITET. 27-PT4805 og 13-PT4805 er ikke samme
    punkt. Systemet må stemme.
  * ALARMANNOTASJON BÆRER MENING, IKKE IDENTITET. HH/LL/H/L på slutten er
    alarmnivået PÅ instrumentet — den skilles ut og leveres som semantikk
    (via analysis.alarm_priority), ikke som en del av taggen.

MÅLING UTEN IMS-TILGANG — poenget med modulen er at den kan tallfestes nå.
`evaluate()` genererer realistiske punktnavn-varianter fra det EKTE
tag-registeret, kjører oppløseren og rapporterer treff, uoppløste OG
feilkoblinger separat. Negative kontroller (fremmed system, søppel) er med,
fordi «løser alt» er trivielt å oppnå og verdiløst — det er feilkoblings-
raten som avgjør om dette kan settes i drift. Samme grep som recall-tak-
analysen: mål taket med syntetiske data av kjent form.

Rene funksjoner, ingen nettverk, ingen Streamlit — testbar headless.

    python src/analysis/alarm_bridge.py --selftest    # determinstisk kjede
    python src/analysis/alarm_bridge.py 27            # mål på ekte register
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if __name__ == "__main__" and __package__ is None:      # direct run support
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Punktnavn-parsing
# ---------------------------------------------------------------------------

_SEP = re.compile(r"[\s_\-./:\\]+")

# attributter en historian henger på punktet — bærer ingen identitet
_ATTRIBUTES = {"PV", "MEAS", "VALUE", "VAL", "AI", "AO", "OUT", "IN", "SP",
               "CV", "STAT", "STATUS", "ALM", "ALARM", "MODE", "QUAL", "EU"}

# kildeprefikser i eksportfiler
_SOURCE_WORDS = {"TAG", "POINT", "PT_ID", "ITEM", "PLANT", "HULDRA", "SAS", "IMS"}

# alarmnivå-annotasjon: valgfri parameter-/alarmbokstav + retning
_ALARM_TOKEN = re.compile(r"^[PLTFZXA]{0,2}(HH|LL|H|L)$")

# redundansbein — IDENTITETSBÆRENDE, foldes aldri bort
_LEGS = {"A", "B", "C", "D"}
# retningsbokstaver som IKKE er bein når de står som suffiks
_LEVELS = {"H", "HH", "L", "LL"}

_TYPE_FIRST = re.compile(r"^(\d{2})([A-Z]{1,4})(\d{2,4})([A-Z]{0,2})$")
_NUM_FIRST = re.compile(r"^(\d{2})(\d{2,4})([A-Z]{1,4})$")
_NO_SYSTEM = re.compile(r"^([A-Z]{1,4})(\d{2,4})([A-Z]{0,2})$")

# anleggsprefiks foran systemnummeret: HO27 -> 27, HA24 -> 24
_FACILITY = re.compile(r"^[A-Z]{1,3}(?=\d{2})")


@dataclass(frozen=True)
class PointKey:
    """Identiteten til et punkt, konvensjonsuavhengig."""
    system: str
    type_code: str
    number: str
    leg: str = ""                  # A/B/C/D — del av identiteten

    def as_tag(self) -> str:
        return f"{self.system}-{self.type_code}{self.number}{self.leg}"


@dataclass
class Resolution:
    """Ett oppslag. `tag` er None med mindre status er exact/resolved."""
    raw: str
    tag: str | None = None
    status: str = "unresolved"     # exact | resolved | ambiguous | unresolved
    key: PointKey | None = None
    alarm_level: str | None = None  # HH/LL/H/L lest av punktnavnet
    attribute: str | None = None    # .PV / .MEAS ...
    candidates: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("exact", "resolved")


def parse_point(raw: str) -> Resolution:
    """Del et rått punktnavn i identitet + annotasjon. Ingen registeroppslag.

    Konservativt der det teller: en annotasjon skilles bare ut når den står
    som EGEN token (`27PT4805.PAHH`) eller som et rent retningssuffiks
    (`27PT4805HH`). Bokstaver limt til taggen ellers regnes som redundans-
    bein, aldri som støy — å ta feil der ville slått sammen A- og B-siden.
    """
    res = Resolution(raw=str(raw))
    s = str(raw).strip().upper()
    if not s:
        return res

    parts = [p for p in _SEP.split(s) if p]
    # dropp kildeprefiks foran ("TAG:27-PT4805")
    while len(parts) > 1 and parts[0] in _SOURCE_WORDS:
        parts.pop(0)
    # dropp attributt/alarm bak, bakfra
    while len(parts) > 1:
        last = parts[-1]
        if last in _ATTRIBUTES:
            res.attribute = last
            parts.pop()
        elif (m := _ALARM_TOKEN.match(last)):
            res.alarm_level = m.group(1)
            parts.pop()
        else:
            break

    compact = "".join(parts)
    compact = _FACILITY.sub("", compact)              # HO27PT4805 -> 27PT4805
    if not compact:
        return res

    system = type_code = number = leg = ""
    if (m := _TYPE_FIRST.match(compact)):
        system, type_code, number, leg = m.groups()
    elif (m := _NUM_FIRST.match(compact)):
        system, number, type_code = m.groups()
    elif (m := _NO_SYSTEM.match(compact)):
        type_code, number, leg = m.groups()
    else:
        res.note = "ikke gjenkjent som tagform"
        return res

    # et retningssuffiks limt til taggen er alarmnivå, ikke redundansbein
    if leg in _LEVELS:
        res.alarm_level = res.alarm_level or leg
        leg = ""
    elif leg and leg not in _LEGS:
        res.note = f"ukjent suffiks {leg!r} beholdt som del av identiteten"

    res.key = PointKey(system, type_code, number, leg)
    return res


# ---------------------------------------------------------------------------
# Register-indeks og oppslag
# ---------------------------------------------------------------------------

def build_index(register) -> dict:
    """Indeks fra tag-registeret. Tar EngineeringObject-er eller rene tags.

    Returnerer {"exact": {normalisert streng: tag},
                "by_key": {PointKey: [tag, ...]},
                "by_stem": {(system, type, number): [tag, ...]}}
    `by_stem` brukes KUN til å oppdage tvetydighet (A/B), aldri til å velge.
    """
    exact: dict[str, str] = {}
    by_key: dict[PointKey, list[str]] = {}
    by_stem: dict[tuple, list[str]] = {}
    for item in register:
        tag = getattr(item, "tag", item)
        tag = str(tag).strip().upper()
        if not tag:
            continue
        exact.setdefault(re.sub(r"[\s\-]+", "", tag), tag)
        sysm = getattr(item, "system", None)
        if sysm and getattr(item, "type_code", None) and getattr(item, "number", None):
            key = PointKey(item.system, item.type_code, item.number,
                           getattr(item, "suffix", "") or "")
        else:
            p = parse_point(tag)
            if not p.key:
                continue
            key = p.key
        by_key.setdefault(key, [])
        if tag not in by_key[key]:
            by_key[key].append(tag)
        stem = (key.system, key.type_code, key.number)
        by_stem.setdefault(stem, [])
        if tag not in by_stem[stem]:
            by_stem[stem].append(tag)
    return {"exact": exact, "by_key": by_key, "by_stem": by_stem}


def resolve_point(raw: str, index: dict) -> Resolution:
    """Løs ett punktnavn mot registeret. Gjetter aldri.

    Rekkefølge: streng-treff -> strukturert nøkkel -> tvetydighetssjekk.
    Et punkt uten bein som treffer flere bein i registeret er `ambiguous`
    med kandidatene; det er A/B-tilfellet, og å velge ett av dem ville
    koblet halvparten av alarmene til feil instrument.
    """
    res = parse_point(raw)
    plain = str(raw).strip().upper()
    norm = re.sub(r"[\s\-]+", "", plain)
    if norm in index["exact"]:
        hit = index["exact"][norm]
        # `exact` reserveres for et punktnavn som ER registertaggen; kom
        # treffet via normalisering (småbokstaver, droppede bindestreker) er
        # det en oppløsning som alle andre, og skal telles som det
        res.tag = hit
        res.status = "exact" if str(raw).strip() == hit else "resolved"
        return res
    if not res.key:
        return res

    hits = index["by_key"].get(res.key, [])
    if len(hits) == 1:
        res.tag, res.status = hits[0], "resolved"
        return res
    if len(hits) > 1:                                # samme nøkkel, flere tags
        res.status, res.candidates = "ambiguous", sorted(hits)
        res.note = "flere registertags deler denne nøkkelen"
        return res

    stem = (res.key.system, res.key.type_code, res.key.number)
    legged = sorted(index["by_stem"].get(stem, []))
    if not legged:
        res.note = res.note or "ingen kandidat i registeret"
        return res
    if res.key.leg:
        # punktet har bein, registeret har det ikke under denne nøkkelen
        res.status, res.candidates = "ambiguous", legged
        res.note = (f"punktet har bein {res.key.leg!r}, registeret har "
                    f"{len(legged)} tag(s) uten samsvarende bein")
        return res
    # Her er punktet beinløst og INGEN beinløs registertag matchet (den ville
    # truffet by_key over), så alle kandidatene bærer bein. Nekt uansett om
    # det bare er én: uttrekket har målt 55 % recall, så «registeret kjenner
    # bare B» betyr ikke «bare B finnes». Å koble til den ene kjente siden
    # ville vært selvsikkert og potensielt feil — og en feilkoblet alarm gir
    # rotårsaksmotoren feil premiss.
    res.status, res.candidates = "ambiguous", legged
    res.note = ("punktet mangler bein; alle kandidater er redundansbein "
                f"({len(legged)} kjent) — uttrekket kan mangle søskenbeinet")
    return res


def resolve_feed(raws, index) -> dict:
    """Løs en hel alarmfeed. Returnerer {resolutions, stats}."""
    out = [resolve_point(r, index) for r in raws]
    stats = {"points": len(out),
             "exact": sum(1 for r in out if r.status == "exact"),
             "resolved": sum(1 for r in out if r.status == "resolved"),
             "ambiguous": sum(1 for r in out if r.status == "ambiguous"),
             "unresolved": sum(1 for r in out if r.status == "unresolved")}
    stats["linked"] = stats["exact"] + stats["resolved"]
    stats["link_rate"] = stats["linked"] / len(out) if out else 0.0
    return {"resolutions": out, "stats": stats}


def alarm_context(res: Resolution, by_tag: dict | None = None) -> dict:
    """Nyttelasten: et oppløst punkt + alarmsemantikken fra taggen.

    Dette er hele poenget med broen — når punktet er koblet til registeret
    arver det prioritet/retning/nivå fra analysis.alarm_priority, og kan
    mates rett inn i root_cause/control_room uten videre oversetting.
    """
    if not res.ok:
        return {"ok": False, "status": res.status, "raw": res.raw,
                "candidates": res.candidates, "note": res.note}
    from analysis.alarm_priority import alarm_semantics
    type_code = res.key.type_code if res.key else ""
    if by_tag and res.tag in by_tag:
        type_code = getattr(by_tag[res.tag], "type_code", type_code)
    sem = alarm_semantics(type_code)
    # nivå lest av punktnavnet vinner over det taggen selv antyder: et
    # `.PAHH`-punkt PÅ en PT er en trip-alarm selv om PT-en er uannotert
    level = sem.get("level")
    if res.alarm_level:
        level = "trip" if res.alarm_level in ("HH", "LL") else "alarm"
    return {"ok": True, "raw": res.raw, "tag": res.tag, "status": res.status,
            "type_code": type_code, "level": level,
            "direction": sem.get("direction"),
            "priority": sem.get("priority"),
            "priority_label": sem.get("priority_label"),
            "from_point_name": res.alarm_level, "attribute": res.attribute}


# ---------------------------------------------------------------------------
# Måling — realistiske varianter fra det ekte registeret
# ---------------------------------------------------------------------------

def _split_tag(tag: str) -> tuple[str, str, str, str] | None:
    p = parse_point(tag)
    if not p.key:
        return None
    return p.key.system, p.key.type_code, p.key.number, p.key.leg


VARIANT_STYLES = ("plain", "nosep", "hyphenated", "underscore", "facility",
                  "attribute", "alarm_suffix", "alarm_token", "source_prefix",
                  "lowercase", "numfirst")


def generate_variants(tag: str, styles=VARIANT_STYLES) -> dict:
    """Realistiske punktnavn for ett registertag: {stil: punktnavn}.

    Formene er hentet fra hvordan SAS-/historian-eksporter faktisk ser ut,
    ikke funnet på for å være lette å løse — `numfirst` og `facility` er med
    nettopp fordi de er de vanskelige.
    """
    s = _split_tag(tag)
    if not s:
        return {}
    sysm, tc, num, leg = s
    core = f"{tc}{num}{leg}"
    out = {
        "plain": tag,
        "nosep": f"{sysm}{core}",
        "hyphenated": f"{sysm}-{tc}-{num}{leg}",
        "underscore": f"{sysm}_{tc}_{num}{leg}",
        "facility": f"HO{sysm}_{tc}_{num}{leg}",
        "attribute": f"{sysm}{core}.PV",
        "alarm_suffix": f"{sysm}{core}.PAHH",
        "alarm_token": f"{sysm}{core}_HH",
        "source_prefix": f"TAG:{sysm}-{core}:PV",
        "lowercase": f"{sysm}-{core}".lower(),
    }
    # nummer-først finnes i datasettet som 27-4561PV — men ALDRI med
    # redundansbein. Å finne opp `27-4806PIA` for å måle på det ville vært å
    # score seg selv mot en form ingen kilde viser; legg-taggene får derfor
    # ingen numfirst-variant i stedet for en oppdiktet en.
    if not leg:
        out["numfirst"] = f"{sysm}-{num}{tc}"
    return {k: v for k, v in out.items() if k in styles}


def negative_controls(index: dict, limit: int = 40) -> list[str]:
    """Punktnavn som IKKE skal løses. Uten disse er en høy koblingsrate
    verdiløs — «løser alt» er trivielt hvis man tillater seg å gjette."""
    out = ["", "N/A", "SUM_TOTAL", "AVG.1H", "OPC.Server.Status",
           "27", "PT", "----", "SEE NOTE 3", "FLOW TOTALISER"]
    # ekte tags, men fra et system som ikke finnes i dette registeret
    seen_systems = {k.system for k in index["by_key"]}
    ghost = next((s for s in ("91", "92", "93") if s not in seen_systems), "99")
    for key in list(index["by_key"])[:limit]:
        out.append(f"{ghost}-{key.type_code}{key.number}{key.leg}")
    return out


def evaluate_legless(index: dict) -> dict:
    """Hva skjer når historian-punktet mangler redundansbeinet?

    Dette er tilfellet variantgeneratoren over IKKE dekker, fordi den bygger
    punktnavn FRA taggen og dermed alltid har beinet med. En ekte feed har
    ofte bare `24LV2162`. Da finnes det ingen ett riktig svar, så dette
    måles ikke som treff/bom — det måles som OPPFØRSEL:

      resolved   registeret har et beinløst tag; punktet peker på det
      ambiguous  bare bein finnes; oppløseren nekter å velge  <- ønsket
      wrong      oppløseren valgte ett bein                   <- skal være 0

    Den siste kolonnen er den som avgjør om modulen kan settes i drift.
    """
    legged = {stem: tags for stem, tags in index["by_stem"].items()
              if any(t for t in tags if _split_tag(t) and _split_tag(t)[3])}
    out = {"stems": len(legged), "resolved": 0, "ambiguous": 0, "picked_a_leg": 0,
           "unresolved": 0, "examples": []}
    for (sysm, tc, num), tags in sorted(legged.items()):
        r = resolve_point(f"{sysm}{tc}{num}", index)
        legless_exists = any(_split_tag(t) and not _split_tag(t)[3] for t in tags)
        if r.status == "ambiguous":
            out["ambiguous"] += 1
        elif r.ok and legless_exists and _split_tag(r.tag) and not _split_tag(r.tag)[3]:
            out["resolved"] += 1                 # pekte på det beinløse tagget
        elif r.ok:
            out["picked_a_leg"] += 1             # valgte A eller B — feil
            if len(out["examples"]) < 5:
                out["examples"].append((f"{sysm}{tc}{num}", r.tag, sorted(tags)))
        else:
            out["unresolved"] += 1
    return out


def evaluate(register, styles=VARIANT_STYLES) -> dict:
    """Mål oppløseren på det ekte registeret. Ingen IMS-tilgang nødvendig.

    Rapporterer treff, tvetydige, uoppløste og — viktigst — FEILKOBLINGER
    separat. En feilkobling er den eneste kategorien som gjør skade i drift,
    så den telles for seg og skal være null.
    """
    register = list(register)
    index = build_index(register)
    tags = sorted(index["exact"].values())
    per_style = {s: {"n": 0, "hit": 0, "wrong": 0, "ambiguous": 0, "miss": 0}
                 for s in styles}
    wrong_examples, ambiguous_examples = [], []

    for tag in tags:
        for style, point in generate_variants(tag, styles).items():
            st = per_style[style]
            st["n"] += 1
            r = resolve_point(point, index)
            if r.ok and r.tag == tag:
                st["hit"] += 1
            elif r.ok:
                st["wrong"] += 1
                if len(wrong_examples) < 10:
                    wrong_examples.append((point, tag, r.tag))
            elif r.status == "ambiguous":
                st["ambiguous"] += 1
                if len(ambiguous_examples) < 10:
                    ambiguous_examples.append((point, tag, r.candidates))
            else:
                st["miss"] += 1

    neg = negative_controls(index)
    neg_res = [resolve_point(p, index) for p in neg]
    false_links = [(p, r.tag) for p, r in zip(neg, neg_res) if r.ok]

    n = sum(s["n"] for s in per_style.values())
    hit = sum(s["hit"] for s in per_style.values())
    wrong = sum(s["wrong"] for s in per_style.values())
    return {
        "register_items": len(register), "tags": len(tags), "points": n,
        "unparseable": sorted(t for t in tags if _split_tag(t) is None)[:10],
        "legless": evaluate_legless(index),
        "hit": hit, "wrong": wrong,
        "ambiguous": sum(s["ambiguous"] for s in per_style.values()),
        "miss": sum(s["miss"] for s in per_style.values()),
        "accuracy": hit / n if n else 0.0,
        "wrong_rate": wrong / n if n else 0.0,
        "per_style": per_style,
        "wrong_examples": wrong_examples,
        "ambiguous_examples": ambiguous_examples,
        "negatives": len(neg), "false_links": false_links,
    }


def format_report(ev: dict) -> str:
    dup = ev.get("register_items", ev["tags"]) - ev["tags"]
    lines = [
        f"{ev['points']} punktnavn generert fra {ev['tags']} unike registertags"
        + (f"  ({dup} duplikat(er) slått sammen)" if dup else ""),
        f"  koblet riktig : {ev['hit']:5}  ({ev['accuracy']:.1%})",
        f"  FEILKOBLET    : {ev['wrong']:5}  ({ev['wrong_rate']:.2%})  <- skal være 0",
        f"  tvetydig      : {ev['ambiguous']:5}  (kandidater vist, ikke valgt)",
        f"  uoppløst      : {ev['miss']:5}",
        "",
        f"  {'stil':<15}{'n':>6}{'treff':>8}{'feil':>7}{'tvetyd':>8}{'bom':>6}",
    ]
    for style, s in ev["per_style"].items():
        lines.append(f"  {style:<15}{s['n']:>6}{s['hit']:>8}{s['wrong']:>7}"
                     f"{s['ambiguous']:>8}{s['miss']:>6}")
    lg = ev.get("legless")
    if lg and lg["stems"]:
        lines += ["",
                  f"  punkt uten redundansbein ({lg['stems']} stammer med A/B):",
                  f"    pekte på beinløst tag : {lg['resolved']}",
                  f"    nektet å velge        : {lg['ambiguous']}  <- ønsket",
                  f"    VALGTE ETT BEIN       : {lg['picked_a_leg']}  <- skal være 0",
                  f"    uoppløst              : {lg['unresolved']}"]
        for e in lg["examples"]:
            lines.append(f"      {e}")
    if ev.get("unparseable"):
        lines.append(f"  uparsebare registertags (utelatt fra målingen): "
                     f"{ev['unparseable']}")
    lines += ["",
              f"  negative kontroller: {ev['negatives']}, "
              f"falske koblinger: {len(ev['false_links'])}  <- skal være 0"]
    if ev["false_links"]:
        lines.append(f"    {ev['false_links'][:5]}")
    if ev["wrong_examples"]:
        lines.append("  feilkoblinger (punkt, fasit, fikk):")
        for w in ev["wrong_examples"][:5]:
            lines.append(f"    {w}")
    if ev["ambiguous_examples"]:
        lines.append("  tvetydige (punkt, fasit, kandidater):")
        for a in ev["ambiguous_examples"][:3]:
            lines.append(f"    {a}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Selvtest — hele kjeden uten data eller nettverk
# ---------------------------------------------------------------------------

_SELFTEST_REGISTER = ["27-PT4805", "27-XV4813", "27-LAHH4802", "27-4561PV",
                      "27-PI4806A", "27-PI4806B", "13-PT4805", "24-LSH2005",
                      # bare ETT bein kjent — søskenbeinet kan mangle i
                      # uttrekket (55 % recall), så et beinløst punkt hit
                      # skal nektes, ikke kobles
                      "45-ER54A"]


def _selftest() -> int:
    index = build_index(_SELFTEST_REGISTER)
    cases = [
        # (punktnavn, forventet tag, forventet status)
        ("27-PT4805",           "27-PT4805", "exact"),
        ("27PT4805",            "27-PT4805", "resolved"),
        ("27-PT-4805",          "27-PT4805", "resolved"),
        ("27_PT_4805",          "27-PT4805", "resolved"),
        ("HO27_PT_4805",        "27-PT4805", "resolved"),
        ("27PT4805.PV",         "27-PT4805", "resolved"),
        ("27PT4805.PAHH",       "27-PT4805", "resolved"),
        ("27PT4805_HH",         "27-PT4805", "resolved"),
        ("TAG:27-PT4805:PV",    "27-PT4805", "resolved"),
        ("27-pt4805",           "27-PT4805", "resolved"),
        ("27-4805PT",           "27-PT4805", "resolved"),
        ("27-4561PV",           "27-4561PV", "exact"),
        ("274561PV",            "27-4561PV", "resolved"),
        ("27-LAHH4802",         "27-LAHH4802", "exact"),
        ("24-LSH2005.PV",       "24-LSH2005", "resolved"),
        # identitet som IKKE skal foldes bort
        ("27-PI4806A",          "27-PI4806A", "exact"),
        ("27PI4806B",           "27-PI4806B", "resolved"),
        ("13PT4805",            "13-PT4805", "resolved"),
        # skal aldri løses
        ("27PI4806",            None, "ambiguous"),     # A eller B?
        ("45ER54",              None, "ambiguous"),     # kun A kjent — nekt
        ("45-ER54A",            "45-ER54A", "exact"),   # med bein: greit
        ("91-PT4805",           None, "unresolved"),    # ukjent system
        ("SEE NOTE 3",          None, "unresolved"),
        ("",                    None, "unresolved"),
        ("OPC.Server.Status",   None, "unresolved"),
    ]
    print("  punktnavn              -> tag            status")
    ok = True
    for point, want_tag, want_status in cases:
        r = resolve_point(point, index)
        good = (r.tag == want_tag) and (r.status == want_status)
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'} {point!r:24} -> "
              f"{str(r.tag):15} {r.status}"
              + ("" if good else f"   [ventet {want_tag} / {want_status}]"))

    # alarmsemantikk arves, og punktnavnets nivå vinner
    ctx = alarm_context(resolve_point("27PT4805.PAHH", index))
    checks = [
        ("alarmnivå lest av punktnavnet", ctx["from_point_name"] == "HH"),
        ("PAHH-punkt på PT blir trip-nivå", ctx["level"] == "trip"),
        ("attributt skilt ut", alarm_context(
            resolve_point("27PT4805.PV", index))["attribute"] == "PV"),
        ("tvetydig gir kandidater, ikke valg",
         resolve_point("27PI4806", index).candidates == ["27-PI4806A", "27-PI4806B"]),
    ]
    ev = evaluate(_SELFTEST_REGISTER)
    checks += [("ingen feilkoblinger i målingen", ev["wrong"] == 0),
               ("ingen falske koblinger på negative kontroller",
                len(ev["false_links"]) == 0),
               ("velger aldri et redundansbein for et beinløst punkt",
                ev["legless"]["picked_a_leg"] == 0),
               ("enslig kjent bein gir nektelse, ikke kobling",
                resolve_point("45ER54", index).candidates == ["45-ER54A"])]
    print()
    for name, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok &= passed
    print()
    print(format_report(ev))
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        sys.exit(_selftest())
    if not args:
        sys.exit("bruk: python src/analysis/alarm_bridge.py "
                 "--selftest | --plant | <system>")

    from extraction.tag_extractor import extract_tags, create_objects
    from main import resolve_inputs

    if args[0] == "--plant":
        # den harde prøven: alle systemer i ETT register, der 27-PT4805 og
        # 13-PT4805 finnes samtidig. Systemprefikset er det eneste som
        # skiller dem, så en oppløser som folder det bort avsløres her.
        systems = ["13", "20", "24", "27", "45", "63", "82"]
        objs, seen = [], set()
        for s in systems:
            try:
                pid, scd, _ = resolve_inputs(["x", s])
            except Exception as e:                          # noqa: BLE001
                print(f"  system {s} hoppet over: {e}")
                continue
            for o in (create_objects(extract_tags(pid), "P&ID")
                      + create_objects(extract_tags(scd), "SCD")):
                if o.tag not in seen:
                    seen.add(o.tag)
                    objs.append(o)
        print(f"Anleggsdekkende: {len(objs)} unike tags over "
              f"{len(systems)} systemer\n")
        print(format_report(evaluate(objs)))
        sys.exit(0)

    pid, scd, system = resolve_inputs(["x", args[0]])
    objs = sorted(set(create_objects(extract_tags(pid), "P&ID"))
                  | set(create_objects(extract_tags(scd), "SCD")), key=lambda o: o.tag)
    print(f"System {system}: {len(objs)} registertags\n")
    print(format_report(evaluate(objs)))
