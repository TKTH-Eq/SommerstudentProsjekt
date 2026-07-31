# src/neqsim_tools/fluid_lookup.py
"""
Maps DEXPI's FluidCodeAssignmentClass (a short code such as "PV", "VF",
"PL", "DC", "WS", "DO", "OL") to a concrete NeqSim fluid composition.

IMPORTANT - THIS MUST BE VERIFIED AGAINST THE PROJECT'S OWN P&ID LEGEND:

Checked against the DEXPI specification (v1.3/v1.4,
dexpi.org/static/pid_specification_1.4/reference/Piping/...): the attribute
is documented with the text "So far, DEXPI does not define restrictions for
valid values" - so there is NO global standard to look these up against.
Fluid codes are a free text string, defined project by project. We also
confirmed they are not defined in the "P&ID Legend Huldra" symbol series
(U999-1-000-PT-100 to PT-114 were reviewed systematically without a hit).

The presets below are therefore REASONED GUESSES, with the basis flagged
explicitly per code at one of two levels:

  [CONVENTION]        From common industry practice: fluid codes on a line
                      list often follow the pattern "abbreviation of the
                      fluid name plus a phase letter" (SW = Sea Water,
                      AL = Ammonia Liquid, AG = Ammonia Gas - see the
                      Eng-Tips piping forum discussion, "ASME Fluid codes",
                      2016).
  [PATTERN-INTERNAL]  From the code forming a natural PAIR with one already
                      seen in the same drawing set (DO alongside DC, for
                      example).

None of these is confirmed - they are consistent guesses and nothing more.
Check the project's own line list or equivalent document if one is
available, and correct FLUID_PRESETS below before this is used for anything
real.

The compositions themselves (mol%) are also PLACEHOLDER examples, not taken
from a process datasheet. Replace them with real figures from the datasheet
or design basis if access is obtained - the DEXPI data contains neither
composition nor operating pressure and temperature at all (confirmed: no
such GenericAttribute fields exist in the export).
"""

from __future__ import annotations

# kode -> (beskrivelse, NeqSim-komponenter [(navn, mol%), ...], typisk fase)
FLUID_PRESETS: dict[str, dict] = {
    "PV": {
        "description": "Process Vapour / gas (ASSUMED - verify against the legend)",
        "eos": "cpa",
        "components": [
            ("nitrogen", 1.0), ("CO2", 2.0), ("methane", 85.0),
            ("ethane", 7.0), ("propane", 3.0), ("i-butane", 1.0), ("n-butane", 1.0), ("water", 5.0),
        ],
        "phase": "gass",
    },
    "PL": {
        "description": "Process Liquid / condensate (ASSUMED - verify against the legend)",
        "eos": "srk",
        "components": [
            ("methane", 5.0), ("ethane", 5.0), ("propane", 10.0),
            ("n-butane", 15.0), ("n-pentane", 20.0), ("n-hexane", 45.0),
        ],
        "phase": "vaeske",
    },
    "VF": {
        "description": "Vent / Flare gas (ASSUMED - verify against the legend)",
        "eos": "cpa",
        "components": [
            ("nitrogen", 3.0), ("CO2", 3.0), ("methane", 80.0),
            ("ethane", 8.0), ("propane", 4.0), ("i-butane", 1.0), ("n-butane", 1.0), ("water", 5.0),
        ],
        "phase": "gass",
    },
    "DC": {
        "description": "Drain Closed - often liquid plus water "
                       "(ASSUMED - verify against the legend)",
        "eos": "cpa",
        "components": [
            ("methane", 2.0), ("propane", 3.0), ("n-hexane", 25.0), ("water", 70.0),
        ],
        "phase": "blandet",
    },
    "DO": {
        "description": "[PATTERN-INTERNAL] Drain Open - assumed as the counterpart to DC "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [
            ("methane", 1.0), ("propane", 2.0), ("n-hexane", 17.0), ("water", 80.0),
        ],
        "phase": "blandet",
    },
    "WS": {
        "description": "[CONVENTION] Water Service / sea water - from the common "
                       "'W...' fluid-code pattern for water systems "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "OL": {
        "description": "[CONVENTION] Oil Line / lube oil - from the common "
                       "'O...' fluid-code pattern for oil systems. "
                       "Uses n-nonane rather than n-decane, because NeqSim's "
                       "component database has no named 'n-decane' "
                       "(confirmed by running it) "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "srk",
        "components": [
            ("n-nonane", 40.0), ("n-hexane", 20.0), ("n-heptane", 40.0),
        ],
        "phase": "vaeske",
    },
    "VA": {
        "description": "[PATTERN-INTERNAL] Vent Atmosphere - assumed counterpart to VF (Vent/Flare): "
                       "venting to atmosphere rather than to flare "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [
            ("nitrogen", 5.0), ("CO2", 4.0), ("methane", 75.0),
            ("ethane", 9.0), ("propane", 5.0), ("i-butane", 1.0), ("n-butane", 1.0), ("water", 5.0),
        ],
        "phase": "gass",
    },
    "WD": {
        "description": "[PATTERN-INTERNAL] Water Drain - assumed counterpart to WS (Water Service): "
                       "draining of water systems "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "WF": {
        "description": "[PATTERN-INTERNAL] Water Fresh - assumed third code in the "
                       "'W...' pattern alongside WS (Water Service) and "
                       "WD (Water Drain); probably separates fresh water from sea or "
                       "process water "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "WI": {
        "description": "[PATTERN-INTERNAL - strong] Water Injection - direct parallel to "
                       "GI (Gas Injection): water and gas injection are often "
                       "twin systems for pressure support offshore "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "WC": {
        "description": "[PATTERN-INTERNAL / CONVENTION] Water, Cooling - the 'W' prefix is "
                       "established, and cooling water is a very common system "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "AP": {
        "description": "[PATTERN-INTERNAL] Air, Plant - natural counterpart to AI "
                       "(Air, Instrument); platforms often have both "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "srk",
        "components": [
            ("nitrogen", 78.0), ("oxygen", 21.0), ("argon", 1.0),
        ],
        "phase": "gass",
    },
    "CA": {
        "description": "[CONVENTION - well-known abbreviation] Compressed Air - a "
                       "common, recognisable abbreviation, overlapping in meaning "
                       "with AP and AI "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "srk",
        "components": [
            ("nitrogen", 78.0), ("oxygen", 21.0), ("argon", 1.0),
        ],
        "phase": "gass",
    },
    "CG": {
        "description": "[CONVENTION - weak] Condensate / Chemical Glycol - uncertain "
                       "reading; could equally be 'Chemical Gas'. "
                       "(ASSUMED - NOT confirmed, low confidence)",
        "eos": "srk",
        "components": [
            ("methane", 3.0), ("ethane", 3.0), ("n-hexane", 30.0),
            ("n-heptane", 64.0),
        ],
        "phase": "vaeske",
    },
    "CC": {
        "description": "[CONVENTION - weak] Chemical, Corrosion inhibitor - a guess "
                       "based on common chemical injections offshore "
                       "(ASSUMED - NOT confirmed, low confidence)",
        "eos": "cpa",
        "components": [("water", 90.0), ("MEG", 10.0)],
        "phase": "vaeske",
    },
    "MK": {
        "description": "[CONVENTION] Make-up (replacement liquid or water) - a common "
                       "process term for liquid replacing losses in a system "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [("water", 100.0)],
        "phase": "vaeske",
    },
    "OF": {
        "description": "[CONVENTION - ambiguous] Open Flare OR Oil Flow - two "
                       "reasonable readings, neither clearly better. Assumes Open "
                       "Flare here (parallel to VA = Vent Atmosphere) "
                       "(ASSUMED - NOT confirmed, especially uncertain)",
        "eos": "cpa",
        "components": [
            ("nitrogen", 3.0), ("CO2", 3.0), ("methane", 80.0),
            ("ethane", 8.0), ("propane", 4.0), ("i-butane", 1.0), ("n-butane", 1.0), ("water", 5.0),
        ],
        "phase": "gass",
    },
    "PT": {
        "description": "[CONVENTION - alternative reading] Pressure Test - a common "
                       "status code for piping under or after pressure testing in "
                       "piping documentation. NOTE: this is NOT related "
                       "to the instrument type code 'PT' (Pressure Transmitter) used "
                       "elsewhere in this project - same letters, two different "
                       "contexts (confirmed: 'PT' does occur as a "
                       "FluidCodeAssignmentClass on real segments) "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [
            ("nitrogen", 1.0), ("CO2", 2.0), ("methane", 85.0),
            ("ethane", 7.0), ("propane", 3.0), ("i-butane", 1.0), ("n-butane", 1.0), ("water", 5.0),
        ],
        "phase": "gass",
    },
    "PI": {
        "description": "[CONVENTION - especially uncertain] No good reading found. "
                       "Confirmed to occur as a real FluidCodeAssignmentClass "
                       "value (see PT), but with no plausible fluid meaning to "
                       "guess at - uses a generic gas as a stand-in for now. "
                       "NOT related to the instrument type code 'PI' "
                       "(Pressure Indicator) "
                       "(ASSUMED - very low confidence)",
        "eos": "cpa",
        "components": [
            ("nitrogen", 1.0), ("CO2", 2.0), ("methane", 85.0),
            ("ethane", 7.0), ("propane", 3.0), ("i-butane", 1.0), ("n-butane", 1.0), ("water", 5.0),
        ],
        "phase": "gass",
    },
    "GI": {
        "description": "[CONVENTION] Gas Injection - a common offshore system "
                       "(gas lift or reservoir pressure support), 'G' = gas prefix "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [
            ("nitrogen", 1.0), ("CO2", 2.0), ("methane", 88.0),
            ("ethane", 6.0), ("propane", 2.0), ("i-butane", 0.5), ("n-butane", 0.5), ("water", 5.0),
        ],
        "phase": "gass",
    },
    "AI": {
        "description": "[CONVENTION - well-known industry abbreviation] Air, Instrument "
                       "- 'AI' or 'IA' is a very common abbreviation "
                       "in oil and gas P&IDs. PHYSICALLY DIFFERENT from the rest "
                       "(pure air, not hydrocarbons). "
                       "(ASSUMED type - composition NOT confirmed against the legend)",
        "eos": "srk",
        "components": [
            ("nitrogen", 78.0), ("oxygen", 21.0), ("argon", 1.0),
        ],
        "phase": "gass",
    },
    "GF": {
        "description": "[CONVENTION] Gas Fuel - very commonly its own "
                       "subsystem on platforms, 'G' = gas prefix "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "cpa",
        "components": [
            ("nitrogen", 1.0), ("CO2", 1.0), ("methane", 90.0),
            ("ethane", 5.0), ("propane", 2.0), ("i-butane", 0.5), ("n-butane", 0.5), ("water", 5.0),
        ],
        "phase": "gass",
    },
    "OH": {
        "description": "[PATTERN-INTERNAL] Oil Header - assumed as an extension of OL "
                       "(Oil Line): a collecting or main oil line. Uses "
                       "n-nonane rather than n-decane, see the OL note "
                       "(ASSUMED - NOT confirmed, no external source found)",
        "eos": "srk",
        "components": [
            ("n-nonane", 35.0), ("n-hexane", 25.0), ("n-heptane", 40.0),
        ],
        "phase": "vaeske",
    },
    "GE": {
        "description": "[CONVENTION + field context] Gas Export - Huldra is a gas field, "
                       "so gas export is likely a main system on the plant; "
                       "somewhat stronger contextual support than a pure letter "
                       "guess, but STILL NOT confirmed against the legend",
        "eos": "cpa",
        "components": [
            ("nitrogen", 0.5), ("CO2", 1.5), ("methane", 92.0),
            ("ethane", 4.5), ("propane", 1.0), ("i-butane", 0.25), ("n-butane", 0.25), ("water", 5.0),
        ],
        "phase": "gass",
    },
}

DEFAULT_PRESET = "PV"  # used when the fluid code is unknown or absent


def get_preset(fluid_code: str | None) -> dict:
    """NeqSim preset for a DEXPI fluid code.

    Falls back to DEFAULT_PRESET when the code is unknown, and says so in the
    description text as well as in the 'matched' flag — a caller that only
    renders the description should still see that nothing was identified."""
    if fluid_code and fluid_code in FLUID_PRESETS:
        return {**FLUID_PRESETS[fluid_code], "matched": True, "code": fluid_code}
    fallback = FLUID_PRESETS[DEFAULT_PRESET]
    return {
        **fallback,
        "matched": False,
        "code": fluid_code or "(no code found)",
        "description": (
            f"Unknown fluid code '{fluid_code}' - using the {DEFAULT_PRESET} "
            f"composition as a stand-in. This is NOT an identification of what "
            f"'{fluid_code}' actually is; see the docstring in fluid_lookup.py"
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