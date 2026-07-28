"""
Vision-uttrekk av CAUSE & EFFECT (styringslogikk) fra SCD-arkene.

Hvorfor dette finnes: `analysis/cause_effect.py` sier det selv — avhengighets-
grafen forteller hva som KAN henge sammen, mens SCD-ens cause-and-effect-logikk
forteller hva som er DESIGNET til å skje ("LAHH trips -> close XV"). Den logikken
står trykt på SCD-arkene, og har til nå måttet fylles inn for hånd i en CSV.
Denne modulen er den automatiserte broen docstringen der etterlyser.

Det er lag 3 i systemforståelsen:

    1. inventar    hva finnes            tag-registeret            (målt)
    2. topologi    hva henger sammen     plant_model/DEXPI-grafen  (finnes)
    3. logikk      hva SKAL skje         C&E fra SCD               <- her

Uten lag 3 kan verktøyene bare si «dette er strukturelt nåbart». Med lag 3 kan
de si «dette er designet til å skje» — som er forskjellen på et hint og et svar
i et kontrollrom.

Metoden er prosjektets vanlige: LLM FORESLÅR, REGISTERET VERIFISERER. Modellen
leser arket og foreslår cause→effect-par; hvert tag klassifiseres mot
tag-registeret med nøyaktig samme (type, nummer)-logikk som ai/hazop_vision.py
bruker, slik at skrivemåte-varianter (`27-PSH 4811` ≡ `27-PSH4811`) ikke telles
som feil. Ingenting slippes ut som sannhet:

  * hver rad skrives med `verified=nei` — en ingeniør må kvittere den ut
  * `note` bærer verifiseringsstatus for begge tags inn i CSV-en, så statusen
    overlever helt fram til appen
  * rader der et tag ikke engang HAR tag-form (`suspect`) slippes ikke inn, men
    telles og rapporteres — feilmodusen skal være synlig, ikke skjult

Hvorfor en C&E-matrise er en rimelig vision-oppgave — i motsetning til
topologi, som `PID_TO_STRUCTURE.md` dokumenterer som mislykket: matrisen er et
RUTENETT med trykt tekst i cellene. Det er transkripsjon, ikke geometrisk
rekonstruksjon av linjer over et raster.

Resultatet lander i `data/cause_effect/`, som `kontrollrom.py` allerede leser —
uttrekket slår altså på operatør-briefens designed-response-visning uten at noe
annet må endres.

Cache: reports/vision_cache/cause_effect/<stem>.json, kun vellykkede kall (samme
regel som extraction/vision_extract.py — en ucachet feil er det som gjør at
neste kjøring prøver arket på nytt).

Bruk:
    python src/ai/ce_vision.py <scd.pdf>          # les ark -> CSV + sammendrag
    python src/ai/ce_vision.py --selftest         # hele kjeden uten API-nøkkel
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ is None:      # direct run support
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# Gjenbruk av verifiseringslogikken framfor duplisering: _type_number/_classify
# er prosjektets kanoniske tag-normalisering (håndterer type-først, nummer-først
# og bar-konvensjonen). De er "private" i hazop_vision, men å kopiere dem hit
# ville gitt to sannheter om hva et gyldig tag er — det er verre.
from ai.hazop_vision import _classify, _type_number      # noqa: F401

CACHE_DIR = Path("reports") / "vision_cache" / "cause_effect"
OUT_DIR = Path("data") / "cause_effect"

# kolonnene analysis/cause_effect.py forventer, i rekkefølge
CE_COLS = ["drawing", "cause_tag", "effect_tag", "function", "source",
           "verified", "note"]

_BADGE = {"verified": "✅", "verified_loose": "☑️",
          "new_candidate": "🟠", "suspect": "❓"}


PROMPT = """\
This image is an offshore System Control Diagram (SCD) / cause & effect sheet.
Your job is to read the DESIGNED CONTROL AND SHUTDOWN LOGIC off the sheet:
which initiating function (cause) drives which action on which element (effect).

The logic can appear in either or both of two forms — report BOTH:
  A. a CAUSE & EFFECT MATRIX: causes as rows, effects as columns, a mark
     (X, a code, a letter) at the intersections that apply.
  B. LOGIC DRAWN GRAPHICALLY: a signal line from an instrument/switch, through
     a logic block (PSD/ESD/trip/interlock), to an actuated element.

Return ONLY JSON with this exact shape:
{
 "sheet": "1-2 sentences: what this sheet controls, and whether the logic is
   drawn as a matrix, as graphical logic, or both",
 "rows": [
   {"cause_tag": "the initiating tag EXACTLY as printed, e.g. 27-PSH4811",
    "effect_tag": "the actuated tag EXACTLY as printed, e.g. 27-XV4813",
    "function": "the action as printed, short, e.g. 'PSD: close inlet'",
    "location": "where on the sheet you read it, e.g. 'C&E matrix row 4' or
      'logic block ESD-2, left of the vessel'"}
 ]
}

Rules — these decide whether the output is usable at all:
- Transcribe tags EXACTLY as printed. Tag formats in this dataset look like
  27-PT4805, 27-XV4813, 27-4561PV, 27-KA50. NEVER invent or complete a tag you
  cannot actually read; leave the row out instead.
- Report ONLY logic you can SEE on this sheet. Do NOT infer a cause-effect
  relation from process piping, from physical proximity, or from what would be
  typical for this kind of system. If in doubt, leave it out.
- One row per cause-effect PAIR. A cause that drives four effects becomes four
  rows with the same cause_tag.
- "function": use the wording printed on the sheet. If the sheet only marks the
  intersection with an X and the column header names the action, use the column
  header. If there is no readable action text, use "".
- Max 60 rows. If the sheet has no readable control logic, return "rows": [].
- No text outside the JSON object.
"""


# ---------------------------------------------------------------------------
# Ren logikk — testbar uten nettverk
# ---------------------------------------------------------------------------

def _known_sets(known_tags) -> tuple[set, set]:
    """(normaliserte tags, (type, nummer)-par) — samme grunnlag som
    hazop_vision.verify_tags bygger, trukket ut så begge klassifiserer likt."""
    known = {re.sub(r"\s+", "", str(t).strip().upper()) for t in known_tags}
    pairs = {p for t in known if (p := _type_number(t))}
    return known, pairs


def _canon_maps(known_tags) -> tuple[dict, dict]:
    """Oppslag fra lest tag til REGISTERETS skrivemåte.

    Hvorfor dette trengs: `cause_effect.validate_ce` løser tags med streng
    normalisering (kun mellomrom + store bokstaver). Leser modellen `27-4814XV`
    der registeret skriver `27-XV4814`, er lesingen KORREKT, men raden faller
    ut av indeksen som «ukjent tag» — ekte styringslogikk går tapt på en
    skrivemåteforskjell. Ved å skrive registerets form i CSV-en (og beholde
    råtranskripsjonen i `note`) løses raden nedstrøms uten at noe i
    cause_effect.py må endres.

    `by_pair` inneholder BARE entydige par: har registeret både `27-PI4805A`
    og `27-PI4805B`, faller paret ('PI','4805') ut, fordi _type_number ikke
    skiller suffiks. Da er det tryggere å la raden stå ukanonisert og bli
    flagget for gjennomgang enn å gjette A når det kunne vært B.
    """
    by_norm: dict[str, str] = {}
    pair_hits: dict[tuple, set] = {}
    for t in known_tags:
        s = str(t).strip().upper()
        by_norm.setdefault(re.sub(r"\s+", "", s), s)
        if p := _type_number(s):
            pair_hits.setdefault(p, set()).add(re.sub(r"\s+", "", s))
    by_pair = {p: by_norm[next(iter(v))]
               for p, v in pair_hits.items() if len(v) == 1}
    return by_norm, by_pair


def _canonical(tag: str, by_norm: dict, by_pair: dict) -> str | None:
    """Registerets skrivemåte for `tag`, eller None om den ikke kan avgjøres."""
    n = re.sub(r"\s+", "", str(tag).strip().upper())
    if n in by_norm:
        return by_norm[n]
    p = _type_number(n)
    return by_pair.get(p) if p else None


def build_ce_rows(payload: dict, known_tags, drawing: str,
                  model: str = "") -> dict:
    """Modellsvar -> verifiserte C&E-rader. REN funksjon: ingen API, ingen disk.

    Hver rad klassifiseres på begge tags. Rader der et av tagene er `suspect`
    (ikke tag-formet i det hele tatt — hallusinasjon eller feillesing) holdes
    utenfor CSV-en, men telles i `stats.dropped_suspect` og beholdes i
    `rejected` slik at feilmodusen kan vises fram.

    `new_candidate` slippes derimot INN: et velformet tag som ikke står i
    registeret kan være symbol-only-innhold tekstuttrekket aldri så (de 45 %),
    og det er nettopp der vision har verdi. Statusen følger med i `note`, og
    `validate_ce` flagger uansett raden som uoppløst nedstrøms.
    """
    known, pairs = _known_sets(known_tags)
    by_norm, by_pair = _canon_maps(known_tags)
    rows: list[dict] = []
    rejected: list[dict] = []
    counts = {"verified": 0, "verified_loose": 0, "new_candidate": 0, "suspect": 0}
    seen: set[tuple[str, str]] = set()
    self_loops = 0

    for r in (payload.get("rows") or [])[:60]:
        cause = str(r.get("cause_tag", "")).strip().upper()
        effect = str(r.get("effect_tag", "")).strip().upper()
        if not cause or not effect:
            continue
        cs = _classify(cause, known, pairs)
        es = _classify(effect, known, pairs)
        counts[cs] += 1
        counts[es] += 1

        # skriv registerets skrivemåte der den kan avgjøres entydig, så raden
        # løses av validate_ce nedstrøms; råtranskripsjonen bevares i `note`
        cause_out = _canonical(cause, by_norm, by_pair) or cause
        effect_out = _canonical(effect, by_norm, by_pair) or effect
        reread = [f'lest "{raw}"' for raw, out in
                  ((cause, cause_out), (effect, effect_out)) if raw != out]

        entry = {
            "drawing": drawing,
            "cause_tag": cause_out,
            "effect_tag": effect_out,
            "function": str(r.get("function", "")).strip()[:120],
            "source": _source_text(drawing, str(r.get("location", "")).strip()),
            "verified": "nei",          # aldri annet: mennesket kvitterer ut
            "note": _note_text(cs, es, model, reread),
            "cause_status": cs,
            "effect_status": es,
        }

        if "suspect" in (cs, es):
            rejected.append(entry)
            continue
        key = (re.sub(r"\s+", "", cause_out), re.sub(r"\s+", "", effect_out))
        if key[0] == key[1]:            # X trigger X — lesefeil, ikke logikk
            self_loops += 1
            continue
        if key in seen:                 # samme par lest to steder på arket
            continue
        seen.add(key)
        rows.append(entry)

    stats = {
        "rows": len(rows),
        "dropped_suspect": len(rejected),
        "dropped_self_loop": self_loops,
        "tag_totals": counts,
        "causes": len({r["cause_tag"] for r in rows}),
        "effects": len({r["effect_tag"] for r in rows}),
        "fully_verified_rows": sum(
            1 for r in rows
            if r["cause_status"].startswith("verified")
            and r["effect_status"].startswith("verified")),
    }
    return {"drawing": drawing, "sheet": str(payload.get("sheet", "")).strip(),
            "rows": rows, "rejected": rejected, "stats": stats, "model": model}


def _source_text(drawing: str, location: str) -> str:
    """`source`-feltet cause_effect.py viser i briefen — må peke tilbake til
    arket så en ingeniør kan slå opp og kvittere."""
    loc = location[:80] if location else "ulokalisert"
    return f"SCD {drawing} — {loc} (vision)"


def _note_text(cause_status: str, effect_status: str, model: str,
               reread: list[str] | None = None) -> str:
    """Verifiseringsstatus + evt. råtranskripsjon, så sporet fra modellens
    faktiske lesing til registerets skrivemåte overlever inn i CSV-en."""
    note = (f"vision{'/' + model if model else ''}; "
            f"cause={cause_status}, effect={effect_status}")
    return f"{note}; {', '.join(reread)}" if reread else note


def to_csv_rows(result: dict) -> list[dict]:
    """Rader i nøyaktig det skjemaet analysis/cause_effect.py leser."""
    return [{c: r[c] for c in CE_COLS} for r in result["rows"]]


def write_csv(result: dict, out_dir: Path | str = OUT_DIR) -> Path:
    """Skriv til data/cause_effect/vision_<stem>.csv — der kontrollrom.py
    allerede leter. Filnavnprefikset `vision_` gjør det trivielt å skille
    maskinforeslåtte ark fra håndførte."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"vision_{_slug(result['drawing'])}.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CE_COLS)
        w.writeheader()
        w.writerows(to_csv_rows(result))
    return path


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text))


def to_markdown(result: dict) -> str:
    """Streamlit-/CLI-vennlig sammendrag med verifiseringsmerker."""
    s = result["stats"]
    lines = [f"**Arket (modellens lesning):** {result.get('sheet', '') or '—'}", ""]
    if not result["rows"]:
        lines.append("_Ingen lesbar styringslogikk funnet på dette arket._")
    for r in result["rows"][:40]:
        cb, eb = _BADGE[r["cause_status"]], _BADGE[r["effect_status"]]
        fn = r["function"] or "aksjon ikke lesbar"
        lines.append(f"- {cb}`{r['cause_tag']}` → {eb}`{r['effect_tag']}` — {fn}")
    if len(result["rows"]) > 40:
        lines.append(f"- … og {len(result['rows']) - 40} rader til")
    c = s["tag_totals"]
    lines += [
        "",
        f"**{s['rows']} cause→effect-rader** fra {s['causes']} årsaker til "
        f"{s['effects']} effekter · {s['fully_verified_rows']} rader har begge "
        f"tags bekreftet i registeret",
        "",
        f"Tag-verifisering: ✅ {c['verified']} bekreftet · "
        f"☑️ {c['verified_loose']} bekreftet via (type, nummer) · "
        f"🟠 {c['new_candidate']} nye kandidater (sjekk arket) · "
        f"❓ {c['suspect']} ukjent format",
    ]
    if s["dropped_suspect"] or s["dropped_self_loop"]:
        lines.append(
            f"Forkastet: {s['dropped_suspect']} rad(er) med ikke-tag-formet "
            f"tag, {s['dropped_self_loop']} selvreferanse(r).")
    lines += ["",
              "*Vision-forslag verifisert mot tag-registeret. Alle rader "
              "skrives som `verified=nei` — de er utkast til en ingeniør-"
              "gjennomgang, ikke lest styringslogikk.*"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Måling mot håndført fasit — scaffolding, se README-notatet
# ---------------------------------------------------------------------------

def _canon_tag(tag: str) -> str:
    """Konvensjons-uavhengig nøkkel for sammenligning:
    `27-XV4814` ≡ `27-4814XV` ≡ `27-XV 4814` -> `27:XV4814`.

    Systemprefiks og eventuell suffiksbokstav BEHOLDES, i motsetning til
    hazop_vision._type_number som med vilje er løsere. Grunnen er at dette
    brukes til MÅLING: `27-PI4805A` og `27-PI4805B` er to forskjellige
    instrumenter, og en måling som slår sammen A og B skjuler nettopp de
    redundans-feilene en C&E-matrise handler om.
    """
    t = re.sub(r"[\s\-]+", "", str(tag).strip().upper())

    def _parse(sysp: str, rest: str) -> str | None:
        m = re.match(r"^([A-Z]{1,4})(\d{2,4})([A-Z]?)$", rest)      # type-først
        if m:
            return f"{sysp}:{m.group(1)}{m.group(2)}{m.group(3)}"
        m = re.match(r"^(\d{2,4})([A-Z]{1,4})$", rest)              # nummer-først
        if m:
            return f"{sysp}:{m.group(2)}{m.group(1)}"
        return None

    m = re.match(r"^(\d{2})(.+)$", t)
    if m and (key := _parse(m.group(1), m.group(2))):
        return key
    return _parse("", t) or t          # uten prefiks, ellers rå streng


def compare_to_manual(result: dict, manual_rows: list[dict]) -> dict:
    """Presisjon/recall på (cause, effect)-par mot håndførte rader.

    Sammenligner på konvensjons-normaliserte tag-par, ikke på aksjonstekst —
    det er relasjonen som er den harde delen; ordlyden i `function` er
    transkripsjon. Normaliseringen er nødvendig, ikke kosmetisk: uten den
    telles `27-4814XV` mot fasitens `27-XV4814` som både en bom OG et falskt
    positivt, og målingen underrapporterer systematisk.

    Returnerer også parene som skiller seg, så en diff kan leses (samme
    arbeidsmåte som løftet recall fra 26 % til 55 % i uttrekket).
    """
    def _pairs(rows, ck="cause_tag", ek="effect_tag"):
        return {(_canon_tag(r[ck]), _canon_tag(r[ek]))
                for r in rows if r.get(ck)}

    got = _pairs(result["rows"])
    want = _pairs(manual_rows)
    tp = got & want
    prec = len(tp) / len(got) if got else 0.0
    rec = len(tp) / len(want) if want else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"precision": prec, "recall": rec, "f1": f1,
            "true_positive": len(tp), "false_positive": sorted(got - want),
            "missed": sorted(want - got), "n_manual": len(want), "n_vision": len(got)}


# ---------------------------------------------------------------------------
# Diskcache — kun vellykkede kall (samme regel som vision_extract)
# ---------------------------------------------------------------------------

def _cache_path(drawing: str) -> Path:
    return CACHE_DIR / f"{_slug(drawing)}.json"


def _cache_load(drawing: str) -> dict | None:
    if os.getenv("HULDRA_VISION_FRESH") == "1":
        return None
    p = _cache_path(drawing)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(payload.get("raw"), dict):
            print(f"[ce-vision] {drawing}: cache hit "
                  f"(lagret {payload.get('saved_at', '?')[:16]})")
            return payload["raw"]
    except Exception as e:                                  # noqa: BLE001
        print(f"[ce-vision] {drawing}: ulesbar cache ignorert ({e})")
    return None


def _cache_save(drawing: str, raw: dict, model: str, dpi: int) -> None:
    """Cacher RÅSVARET, ikke det verifiserte resultatet — da kan registeret
    bygges om og verifiseringen kjøres på nytt uten å bruke kvote."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(drawing).write_text(json.dumps({
            "drawing": drawing, "raw": raw, "model": model, "dpi": dpi,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:                                  # noqa: BLE001
        print(f"[ce-vision] {drawing}: kunne ikke skrive cache ({e})")


_QUOTA_EXHAUSTED = False


def extract_ce_vision(pdf_path: str | Path, known_tags, dpi: int = 300,
                      model: str | None = None, page: int = 0) -> dict:
    """Les C&E-logikken av SCD-arket og verifiser hvert tag mot registeret.

    dpi=300 (mot 200 ellers i prosjektet): en C&E-matrise har liten trykt tekst
    i tette celler, og transkripsjonen er hele poenget her.

    API-feil (kvote, nett) løftes til kalleren og caches ALDRI — det er det som
    gjør en kjøring gjenopptagbar.
    """
    global _QUOTA_EXHAUSTED
    pdf_path = Path(pdf_path)
    drawing = pdf_path.stem
    model_name = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    raw = _cache_load(drawing)
    if raw is None:
        if _QUOTA_EXHAUSTED:
            raise RuntimeError("daglig vision-kvote brukt opp tidligere i denne "
                               "kjøringen — arket hoppes over, prøv neste kjøring")
        from google.genai import types
        from extraction.vision_extract import render_png
        from ai.gemini_client import generate

        img = Path(render_png(pdf_path, dpi, page)).read_bytes()
        try:
            resp = generate(
                [types.Part.from_bytes(data=img, mime_type="image/png"), PROMPT],
                model=model_name,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0,      # transkripsjon, ikke kreativitet
                ),
            )
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                _QUOTA_EXHAUSTED = True
                print("[ce-vision] daglig kvote brukt opp — hopper over "
                      "resten av kjøringen (cachede ark lastes fortsatt)")
            raise
        raw = _parse_json(resp.text or "")
        if raw.get("rows") or raw.get("sheet"):
            _cache_save(drawing, raw, model_name, dpi)

    return build_ce_rows(raw, known_tags, drawing, model_name)


def _parse_json(text: str) -> dict:
    """Tolerant parse: strip markdown-gjerder, krev objekt."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"sheet": "(kunne ikke tolke modellsvaret)", "rows": []}
    return data if isinstance(data, dict) else {"sheet": "", "rows": []}


# ---------------------------------------------------------------------------
# Selvtest — hele den deterministiske kjeden uten API-nøkkel
# ---------------------------------------------------------------------------

_SELFTEST_PAYLOAD = {
    "sheet": "Inlet separator 27-VG4801, shutdown logic drawn as a C&E matrix "
             "with PSD/ESD columns.",
    "rows": [
        # begge tags i registeret -> verified
        {"cause_tag": "27-PSH4811", "effect_tag": "27-XV4813",
         "function": "PSD: close inlet", "location": "C&E matrix row 4"},
        # samme par en gang til, lest et annet sted -> deduplisert
        {"cause_tag": "27-PSH 4811", "effect_tag": "27-XV 4813",
         "function": "PSD: close inlet", "location": "logic block ESD-2"},
        # annen skrivemåte av kjent tag -> verified_loose
        {"cause_tag": "27-LSHH 4802", "effect_tag": "27-4814XV",
         "function": "PSD: close outlet", "location": "C&E matrix row 5"},
        # velformet, men ikke i registeret -> new_candidate (slippes inn)
        {"cause_tag": "27-PSHH4899", "effect_tag": "27-XV4813",
         "function": "ESD: blowdown", "location": "C&E matrix row 6"},
        # ikke tag-formet -> suspect, raden forkastes og telles
        {"cause_tag": "SEE NOTE 3", "effect_tag": "27-XV4813",
         "function": "", "location": "note field"},
        # selvreferanse -> forkastes
        {"cause_tag": "27-XV4813", "effect_tag": "27-XV4813",
         "function": "", "location": "misread"},
    ],
}

_SELFTEST_KNOWN = ["27-PSH4811", "27-XV4813", "27-LSHH4802", "27-XV4814",
                   "27-PT4805", "27-VG4801"]

_SELFTEST_MANUAL = [
    {"cause_tag": "27-PSH4811", "effect_tag": "27-XV4813"},
    {"cause_tag": "27-LSHH4802", "effect_tag": "27-XV4814"},
    {"cause_tag": "27-PT4805", "effect_tag": "27-XV4813"},     # bommet av vision
]


def _selftest() -> int:
    res = build_ce_rows(_SELFTEST_PAYLOAD, _SELFTEST_KNOWN, "C025-V-HO27-J-_E-101-01",
                        model="selftest")
    s = res["stats"]
    checks = [
        ("3 rader beholdt (dedup + 2 forkastet)", s["rows"] == 3),
        ("1 rad forkastet som suspect", s["dropped_suspect"] == 1),
        ("1 selvreferanse forkastet", s["dropped_self_loop"] == 1),
        ("dedup traff duplikatparet", len({(r["cause_tag"], r["effect_tag"])
                                           for r in res["rows"]}) == 3),
        ("løs match gjenkjent (27-4814XV ≡ 27-XV4814)",
         any(r["effect_status"] == "verified_loose" for r in res["rows"])),
        ("ny kandidat sluppet inn", any(r["cause_status"] == "new_candidate"
                                        for r in res["rows"])),
        ("alle rader verified=nei", all(r["verified"] == "nei" for r in res["rows"])),
        ("CSV-skjema matcher cause_effect.py",
         all(set(r) == set(CE_COLS) for r in to_csv_rows(res))),
    ]
    # skjemaet må matche det analysis/cause_effect.py faktisk leser
    from analysis.cause_effect import _COLS as CE_MODULE_COLS
    checks.append(("kolonner identiske med cause_effect._COLS",
                   CE_COLS == list(CE_MODULE_COLS)))

    print(to_markdown(res))
    print("\n--- selvtest ---")
    ok = True
    for name, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok &= passed

    m = compare_to_manual(res, _SELFTEST_MANUAL)
    # Regresjonsvakt: fasiten skriver 27-XV4814, vision leste 27-4814XV. Samme
    # instrument, to konvensjoner. Teller målingen det som bom, underrapporterer
    # den systematisk — den feilen satt her først, og skal ikke tilbake.
    conv = [("konvensjonsfolding i målingen (27-4814XV ≡ 27-XV4814)",
             ("27:LSHH4802", "27:XV4814") not in
             {(_canon_tag(a), _canon_tag(b)) for a, b in m["missed"]}),
            ("A/B-suffiks holdes fra hverandre i målingen",
             _canon_tag("27-PI4805A") != _canon_tag("27-PI4805B"))]
    for name, passed in conv:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok &= passed

    print(f"\n  måling mot håndført fasit (syntetisk): "
          f"presisjon {m['precision']:.0%}, recall {m['recall']:.0%}, "
          f"F1 {m['f1']:.0%}  ({m['true_positive']}/{m['n_vision']} treff, "
          f"{len(m['missed'])} bommet)")
    print(f"  bommet: {m['missed']}")
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if not args or args[0] in ("-h", "--help"):
        sys.exit("bruk: python src/ai/ce_vision.py <scd.pdf> | --selftest")
    if args[0] == "--selftest":
        sys.exit(_selftest())

    from extraction.tag_extractor import extract_tags
    pdf = Path(args[0])
    if not pdf.exists():
        sys.exit(f"finner ikke {pdf}")
    # registeret å verifisere mot: tags fra arket selv + evt. søsterark
    known = list(extract_tags(str(pdf)))
    print(f"[ce-vision] {len(known)} tag(s) i registeret for verifisering")
    try:
        result = extract_ce_vision(pdf, known)
    except Exception as e:                                  # noqa: BLE001
        msg = str(e)
        if "API key" in msg or "API_KEY" in msg:
            sys.exit("Mangler GEMINI_API_KEY. Legg den i .env i prosjektroten "
                     "(gratis nøkkel fra Google AI Studio holder).\n"
                     "Den deterministiske kjeden kan testes uten nøkkel: "
                     "python src/ai/ce_vision.py --selftest")
        sys.exit(f"Vision-kallet feilet: {msg}")
    print(to_markdown(result))
    if result["rows"]:
        out = write_csv(result)
        print(f"\nSkrevet {len(result['rows'])} rad(er) til {out}")
        print("Alle rader står som verified=nei — gjennomgå og sett 'ja' "
              "på de radene en ingeniør har bekreftet mot arket.")
