# src/neqsim/fluid_lookup.py
"""
Kobler DEXPI sin FluidCodeAssignmentClass (en kort kode, f.eks. "PV", "VF",
"PL", "DC") til en konkret NeqSim-fluidsammensetning.

VIKTIG — DETTE MAA VERIFISERES MOT DERES EGEN P&ID LEGEND:
Fluidkodene er prosjektspesifikke forkortelser (Huldra sin egen konvensjon),
IKKE en universell standard. Jeg har IKKE tilgang til "P&ID Legend Huldra"-
dokumentet som definerer hva hver kode faktisk betyr, saa presetene under er
BEGRUNNEDE GJETNINGER basert paa vanlig norsk sokkel-navnekonvensjon
(PV=Process Vapour/gass, PL=Process Liquid, VF=Vent/Flare, DC=Drain Closed),
IKKE bekreftet mot deres faktiske legend. Sjekk "P&ID Legend Huldra"-mappen
og korriger FLUID_PRESETS under foer dette brukes til noe som helst reelt.

Sammensetningene selv (mol%) er ogsaa PLACEHOLDER-eksempler (samme
generiske brønnstrømsgass som resten av prosjektet har brukt saa langt),
ikke hentet fra et ekte prosess-datablad. Bytt ut med reelle tall fra
prosessdatabladet/design basis naar/hvis dere har tilgang til det — DEXPI-
dataen inneholder dessverre ikke sammensetning eller drifts-trykk/temperatur
i det hele tatt (bekreftet: ingen slike GenericAttribute-felt finnes i
eksporten), saa dette MAA hentes fra en annen kilde uansett.
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
}

DEFAULT_PRESET = "PV"  # brukes naar fluidkoden er ukjent/mangler


def get_preset(fluid_code: str | None) -> dict:
    """Hent NeqSim-preset for en DEXPI-fluidkode. Faller tilbake til
    DEFAULT_PRESET (med tydelig markering) hvis koden er ukjent."""
    if fluid_code and fluid_code in FLUID_PRESETS:
        return {**FLUID_PRESETS[fluid_code], "matched": True, "code": fluid_code}
    fallback = FLUID_PRESETS[DEFAULT_PRESET]
    return {**fallback, "matched": False, "code": fluid_code or "(ingen kode funnet)"}


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