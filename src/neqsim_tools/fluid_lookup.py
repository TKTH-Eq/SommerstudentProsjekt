# src/neqsim_tools/fluid_lookup.py
"""
Kobler DEXPI sin FluidCodeAssignmentClass (en kort kode, f.eks. "PV", "VF",
"PL", "DC", "WS", "DO", "OL") til en konkret NeqSim-fluidsammensetning.

VIKTIG — DETTE MAA VERIFISERES MOT DERES EGEN P&ID LEGEND:

Sjekket mot DEXPI sin offisielle spesifikasjon (v1.3/v1.4,
dexpi.org/static/pid_specification_1.4/reference/Piping/...): attributtet
er dokumentert med teksten "So far, DEXPI does not define restrictions for
valid values" — det finnes altsaa INGEN global standard aa slaa opp mot.
Fluidkoder er en fri tekststreng, definert prosjekt for prosjekt. Vi har
ogsaa bekreftet at dette IKKE stod i "P&ID Legend Huldra"-symbolserien
(U999-1-000-PT-100 til PT-114 ble systematisk gjennomgaatt uten treff).

Presetene under er derfor BEGRUNNEDE GJETNINGER, med to ulike
begrunnelsesnivaaer merket eksplisitt per kode:

  [MOENSTER]  Basert paa vanlig bransjepraksis: fluidkoder paa en
              roerlinjeliste foelger ofte moensteret "forkortelse av
              fluidnavn + fasebokstav" (f.eks. SW=Sea Water, AL=Ammonia
              Liquid, AG=Ammonia Gas — se diskusjon paa Eng-Tips-forumet
              for rørleggingsingeniorer, "ASME Fluid codes" 2016).
  [INTERN]    Basert paa at koden danner et naturlig PAR med en kode vi
              allerede har sett paa samme tegningssett (f.eks. DO ved
              siden av DC).

Ingen av disse er bekreftet — kun konsistente gjetninger. Sjekk deres egen
roerlinjeliste ("line list") eller tilsvarende dokument, om tilgjengelig,
og korriger FLUID_PRESETS under foer dette brukes til noe som helst reelt.

Sammensetningene selv (mol%) er ogsaa PLACEHOLDER-eksempler, ikke hentet
fra et ekte prosess-datablad. Bytt ut med reelle tall fra prosessdatabladet/
design basis naar/hvis dere har tilgang til det — DEXPI-dataen inneholder
dessverre ikke sammensetning eller drifts-trykk/temperatur i det hele tatt
(bekreftet: ingen slike GenericAttribute-felt finnes i eksporten).
"""

from __future__ import annotations

# kode -> (beskrivelse, NeqSim-komponenter [(navn, mol%), ...], typisk fase)
FLUID_PRESETS: dict[str, dict] = {
    "PV": {
        "description": "Process Vapour/gass (ANTATT — verifiser mot legend)",
        "eos": "srk",
        "components": [
            ("nitrogen", 1.0), ("CO2", 2.0), ("methane", 85.0),
            ("ethane", 7.0), ("propane", 3.0), ("i-butane", 1.0), ("n-butane", 1.0),
        ],
        "phase": "gass",
    },
    "PL": {
        "description": "Process Liquid/kondensat (ANTATT — verifiser mot legend)",
        "eos": "srk",
        "components": [
            ("methane", 5.0), ("ethane", 5.0), ("propane", 10.0),
            ("n-butane", 15.0), ("n-pentane", 20.0), ("n-hexane", 45.0),
        ],
        "phase": "vaeske",
    },
    "VF": {
        "description": "Vent/Flare-gass (ANTATT — verifiser mot legend)",
        "eos": "srk",
        "components": [
            ("nitrogen", 3.0), ("CO2", 3.0), ("methane", 80.0),
            ("ethane", 8.0), ("propane", 4.0), ("i-butane", 1.0), ("n-butane", 1.0),
        ],
        "phase": "gass",
    },
    "DC": {
        "description": "Drain Closed / lukket drenering — ofte vaeske+vann "
                       "(ANTATT — verifiser mot legend)",
        "eos": "cpa",
        "components": [
            ("methane", 2.0), ("propane", 3.0), ("n-hexane", 25.0), ("water", 70.0),
        ],
        "phase": "blandet",
    },
    "DO": {
        "description": "[INTERN] Drain Open / aapen drenering — antatt som par til DC "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "cpa",
        "components": [
            ("methane", 1.0), ("propane", 2.0), ("n-hexane", 17.0), ("water", 80.0),
        ],
        "phase": "blandet",
    },
    "WS": {
        "description": "[MOENSTER] Water Service/sjovann — basert paa vanlig "
                       "'W...'-fluidkode-moenster for vannbaserte systemer "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "OL": {
        "description": "[MOENSTER] Oil Line/smoereolje — basert paa vanlig "
                       "'O...'-fluidkode-moenster for oljebaserte systemer. "
                       "Bruker n-nonane i stedet for n-decane, siden NeqSim "
                       "sin database ikke har 'n-decane' som navngitt "
                       "komponent (bekreftet ved test) "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "srk",
        "components": [
            ("n-nonane", 40.0), ("n-hexane", 20.0), ("n-heptane", 40.0),
        ],
        "phase": "vaeske",
    },
    "VA": {
        "description": "[INTERN] Vent Atmosphere — antatt som par til VF (Vent/Flare): "
                       "vent til atmosfaere i stedet for til flare "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "srk",
        "components": [
            ("nitrogen", 5.0), ("CO2", 4.0), ("methane", 75.0),
            ("ethane", 9.0), ("propane", 5.0), ("i-butane", 1.0), ("n-butane", 1.0),
        ],
        "phase": "gass",
    },
    "WD": {
        "description": "[INTERN] Water Drain — antatt som par til WS (Water Service): "
                       "drenering av vannbaserte systemer "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "WF": {
        "description": "[INTERN] Water Fresh (ferskvann) — antatt som tredje kode i "
                       "'W...'-moensteret ved siden av WS (Water Service) og "
                       "WD (Water Drain); skiller trolig ferskvann fra sjovann/"
                       "prosessvann "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "WI": {
        "description": "[INTERN — sterk] Water Injection — direkte parallell til "
                       "GI (Gas Injection): vanninjeksjon og gassinjeksjon er ofte "
                       "tvillingsystemer for trykkstoette offshore "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "WC": {
        "description": "[INTERN/MOENSTER] Water, Cooling (kjolevann) — 'W'-prefiks "
                       "etablert, kjolevann er et svaert vanlig industrisystem "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "AP": {
        "description": "[INTERN] Air, Plant (prosessluft) — naturlig par til AI "
                       "(Air, Instrument); plattformer har ofte begge "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "srk",
        "components": [
            ("nitrogen", 78.0), ("oxygen", 21.0), ("argon", 1.0),
        ],
        "phase": "gass",
    },
    "CA": {
        "description": "[MOENSTER — kjent forkortelse] Compressed Air (trykkluft) — "
                       "vanlig, gjenkjennelig forkortelse, overlapper i betydning "
                       "med AP/AI "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "srk",
        "components": [
            ("nitrogen", 78.0), ("oxygen", 21.0), ("argon", 1.0),
        ],
        "phase": "gass",
    },
    "CG": {
        "description": "[MOENSTER — svak] Condensate/Chemical Glycol — usikker "
                       "tolkning, kunne ogsaa vaert 'Chemical Gas'. "
                       "(ANTATT — IKKE bekreftet, lav tillit)",
        "eos": "srk",
        "components": [
            ("methane", 3.0), ("ethane", 3.0), ("n-hexane", 30.0),
            ("n-heptane", 64.0),
        ],
        "phase": "vaeske",
    },
    "CC": {
        "description": "[MOENSTER — svak] Chemical, Corrosion inhibitor — ren "
                       "gjetning basert paa vanlige kjemikalietilsetninger offshore "
                       "(ANTATT — IKKE bekreftet, lav tillit)",
        "eos": "cpa",
        "components": [("water", 90.0), ("MEG", 10.0)],
        "phase": "vaeske",
    },
    "MK": {
        "description": "[MOENSTER] Make-up (paafyllingsvaeske/-vann) — vanlig "
                       "prosessterm for vaeske som erstatter tap i et system "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "OF": {
        "description": "[MOENSTER — tvetydig] Open Flare ELLER Oil Flow — to "
                       "rimelige tolkninger, ingen klart bedre. Antar her Open "
                       "Flare (parallell til VA=Vent Atmosphere) "
                       "(ANTATT — IKKE bekreftet, SAERLIG usikker)",
        "eos": "srk",
        "components": [
            ("nitrogen", 3.0), ("CO2", 3.0), ("methane", 80.0),
            ("ethane", 8.0), ("propane", 4.0), ("i-butane", 1.0), ("n-butane", 1.0),
        ],
        "phase": "gass",
    },
    "PT": {
        "description": "[MOENSTER — alternativ konvensjon] Pressure Test — vanlig "
                       "statuskode for roerlinjer under/etter trykktesting i "
                       "roerleggingsdokumentasjon. VIKTIG: dette er IKKE relatert "
                       "til instrument-typekoden 'PT' (Trykktransmitter) brukt "
                       "andre steder i prosjektet — samme bokstaver, to ulike "
                       "kontekster (bekreftet ved at 'PT' faktisk forekommer som "
                       "FluidCodeAssignmentClass paa ekte segmenter) "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "srk",
        "components": [
            ("nitrogen", 1.0), ("CO2", 2.0), ("methane", 85.0),
            ("ethane", 7.0), ("propane", 3.0), ("i-butane", 1.0), ("n-butane", 1.0),
        ],
        "phase": "gass",
    },
    "PI": {
        "description": "[MOENSTER — SAERLIG usikker] Ingen god tolkning funnet. "
                       "Bekreftet aa forekomme som ekte FluidCodeAssignmentClass-"
                       "verdi (se PT), men uten en plausibel fluid-betydning aa "
                       "gjette paa — bruker generisk gass som stand-in inntil "
                       "videre. IKKE relatert til instrument-typekoden 'PI' "
                       "(Trykkindikator) "
                       "(ANTATT — svaert lav tillit)",
        "eos": "srk",
        "components": [
            ("nitrogen", 1.0), ("CO2", 2.0), ("methane", 85.0),
            ("ethane", 7.0), ("propane", 3.0), ("i-butane", 1.0), ("n-butane", 1.0),
        ],
        "phase": "gass",
    },
    "GI": {
        "description": "[MOENSTER] Gas Injection — vanlig offshore-system "
                       "(gassloeft/trykkstoette til reservoar), 'G'=Gas-prefiks "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "srk",
        "components": [
            ("nitrogen", 1.0), ("CO2", 2.0), ("methane", 88.0),
            ("ethane", 6.0), ("propane", 2.0), ("i-butane", 0.5), ("n-butane", 0.5),
        ],
        "phase": "gass",
    },
    "AI": {
        "description": "[MOENSTER — kjent bransjeforkortelse] Air, Instrument "
                       "(instrumentluft) — 'AI'/'IA' er en svaert vanlig forkortelse "
                       "i olje/gass-P&ID-er. FYSISK ANNERLEDES fluid enn resten "
                       "(ren luft, ikke hydrokarboner). "
                       "(ANTATT type — sammensetning IKKE bekreftet mot legend)",
        "eos": "srk",
        "components": [
            ("nitrogen", 78.0), ("oxygen", 21.0), ("argon", 1.0),
        ],
        "phase": "gass",
    },
    "GF": {
        "description": "[MOENSTER] Gas Fuel (brenngass) — svaert vanlig eget "
                       "delsystem paa plattformer, 'G'=Gas-prefiks "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "srk",
        "components": [
            ("nitrogen", 1.0), ("CO2", 1.0), ("methane", 90.0),
            ("ethane", 5.0), ("propane", 2.0), ("i-butane", 0.5), ("n-butane", 0.5),
        ],
        "phase": "gass",
    },
    "OH": {
        "description": "[INTERN] Oil Header — antatt som utvidelse av OL "
                       "(Oil Line): samlerør/hovedledning for olje. Bruker "
                       "n-nonane i stedet for n-decane, se OL-forklaring "
                       "(ANTATT — IKKE bekreftet, ingen ekstern kilde funnet)",
        "eos": "srk",
        "components": [
            ("n-nonane", 35.0), ("n-hexane", 25.0), ("n-heptane", 40.0),
        ],
        "phase": "vaeske",
    },
    "GE": {
        "description": "[MOENSTER + kontekst] Gas Export — Huldra er et gassfelt, "
                       "saa gasseksport er trolig et hovedsystem paa anlegget; "
                       "noe sterkere kontekstuell stoette enn ren bokstav-gjetning, "
                       "men FORTSATT IKKE bekreftet mot legend",
        "eos": "srk",
        "components": [
            ("nitrogen", 0.5), ("CO2", 1.5), ("methane", 92.0),
            ("ethane", 4.5), ("propane", 1.0), ("i-butane", 0.25), ("n-butane", 0.25),
        ],
        "phase": "gass",
    },
}

DEFAULT_PRESET = "PV"  # brukes naar fluidkoden er ukjent/mangler


def get_preset(fluid_code: str | None) -> dict:
    """Hent NeqSim-preset for en DEXPI-fluidkode. Faller tilbake til
    DEFAULT_PRESET (med tydelig markering OGSAA i beskrivelsesteksten,
    ikke bare i 'matched'-flagget) hvis koden er ukjent."""
    if fluid_code and fluid_code in FLUID_PRESETS:
        return {**FLUID_PRESETS[fluid_code], "matched": True, "code": fluid_code}
    fallback = FLUID_PRESETS[DEFAULT_PRESET]
    return {
        **fallback,
        "matched": False,
        "code": fluid_code or "(ingen kode funnet)",
        "description": (
            f"Ukjent fluidkode '{fluid_code}' — bruker {DEFAULT_PRESET}-sammensetning "
            f"som midlertidig stand-in (IKKE en identifikasjon av hva '{fluid_code}' "
            f"faktisk er — se docstring i fluid_lookup.py)"
        ),
    }


def build_neqsim_fluid(preset: dict):
    """Bygg et NeqSim fluid-objekt fra en preset-dict. Krever NeqSim/Java."""
    from neqsim.thermo import fluid
    f = fluid(preset["eos"])
    for comp, mol in preset["components"]:
        f.addComponent(comp, mol)
    if preset["eos"] == "cpa":
        f.setMixingRule(10)
        f.setMultiPhaseCheck(True)
    else:
        f.setMixingRule("classic")
    return f