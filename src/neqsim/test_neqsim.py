"""
Testskript for NeqSim
=====================
Kjor forst:  pip install neqsim
Krever Java 8+ installert (NeqSim er Java-basert, Python-pakken
starter en JVM i bakgrunnen via jpype).

Kjor:  python test_neqsim.py
"""

import sys

# ---------------------------------------------------------------
# TRINN 1: Sjekk at NeqSim er installert og at JVM starter
# ---------------------------------------------------------------
try:
    from neqsim.thermo import fluid, TPflash, hydt
    print("TRINN 1 OK: NeqSim importert og JVM startet\n")
except ImportError as e:
    sys.exit(f"FEIL: NeqSim ikke installert ({e}). Kjor: pip install neqsim")
except Exception as e:
    sys.exit(f"FEIL ved oppstart av JVM (er Java installert?): {e}")

# ---------------------------------------------------------------
# TRINN 2: Enkel TP-flash pa en torr gass (SRK)
# ---------------------------------------------------------------
gass = fluid("srk")
gass.addComponent("nitrogen", 1.0)      # mol%
gass.addComponent("CO2", 2.0)
gass.addComponent("methane", 85.0)
gass.addComponent("ethane", 7.0)
gass.addComponent("propane", 3.0)
gass.addComponent("i-butane", 1.0)
gass.addComponent("n-butane", 1.0)
gass.setMixingRule("classic")

gass.setTemperature(30.0, "C")
gass.setPressure(90.0, "bara")
TPflash(gass)
gass.initProperties()

print("TRINN 2 OK: TP-flash ved 90 bara / 30 C")
print(f"  Antall faser : {gass.getNumberOfPhases()}")
print(f"  Tetthet gass : {gass.getPhase('gas').getDensity('kg/m3'):.1f} kg/m3")
print(f"  Z-faktor     : {gass.getPhase('gas').getZ():.4f}")
print(f"  Molvekt      : {gass.getMolarMass('gr/mol'):.2f} g/mol\n")

# ---------------------------------------------------------------
# TRINN 3: Hydratkurve med og uten MEG (CPA)
# ---------------------------------------------------------------
def lag_vaat_gass(meg_mol=0.0):
    f = fluid("cpa")
    f.addComponent("nitrogen", 1.0)
    f.addComponent("CO2", 2.0)
    f.addComponent("methane", 85.0)
    f.addComponent("ethane", 7.0)
    f.addComponent("propane", 3.0)
    f.addComponent("i-butane", 1.0)
    f.addComponent("n-butane", 1.0)
    f.addComponent("water", 5.0)
    if meg_mol > 0:
        f.addComponent("MEG", meg_mol)
    f.setMixingRule(10)          # CPA-blandingsregel
    f.setMultiPhaseCheck(True)
    return f

trykk = [30.0, 60.0, 90.0, 120.0]
print("TRINN 3: Hydrattemperatur [C] ved ulike trykk")
print(f"  {'P [bara]':>9} | {'uten MEG':>9} | {'med MEG':>9}")
print("  " + "-" * 35)

for p in trykk:
    rad = []
    for meg in (0.0, 1.5):      # 1.5 mol MEG ~ ca. 50 wt% i vannfasen her
        f = lag_vaat_gass(meg)
        f.setPressure(p, "bara")
        f.setTemperature(10.0, "C")   # startgjett
        try:
            hydt(f)
            rad.append(f"{f.getTemperature('C'):9.1f}")
        except Exception:
            rad.append("   feilet")
    print(f"  {p:9.0f} | {rad[0]} | {rad[1]}")

print("\nAlle trinn fullfort - NeqSim fungerer!")