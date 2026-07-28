"""
Tid til settpunkt — fra «hva er nedstrøms» til «hvor lang tid har du».

Kontrollrom-assistenten svarer i dag strukturelt: 27-XV4813 er nedstrøms,
27-PSHH4811 er barrieren. Den sier ingenting om NÅR. For en operatør er det
forskjellen på informasjon og beslutningsstøtte:

    før    «27-PSHH4811 er en relevant barriere i kjeden»
    etter  «ved oppgitt rate nås 27-PSHH4811 sitt settpunkt om 2-4 min»

Denne modulen regner ut det tallet, og NeqSim er der fordi den fortjener
plassen: ved 50 bara er Z ≈ 0,91, så idealgass bommer med ~9 % — og feilen
vokser med trykket.

HVA TEGNINGEN GIR, OG HVA DEN IKKE GIR
--------------------------------------
Dette er hele grunnen til at modulen ser ut som den gjør. Fra uttrekket får
vi STRUKTUREN: hvilken trip som vokter avviket, hva som isoleres, og
fluidkoden på linja. Vi får IKKE tallene fysikken trenger:

  settpunkt      analysis/alarm_priority.py sier det rett ut — settpunkt og
                 tillatt responstid ligger i alarmfilosofien/alarmdatabasen,
                 ikke i åpne Huldra-data
  volum          beholdervolum står ikke på et P&ID
  innstrømning   driftspunktet er ikke en tegningsegenskap
  sammensetning  fluid_lookup.py er ærlig på at presetene er BEGRUNNEDE
                 GJETNINGER — DEXPI standardiserer ikke fluidkoder

Derfor: tegningen sier HVA som ryker, brukeren/feeden oppgir driftspunktet,
NeqSim sier NÅR. Hver antakelse følger med i svaret og skal leses.

TO MODELLER, OG HVORFOR BEGGE
-----------------------------
  isoterm     temperaturen holdes fast. Enkel — men gass som fyller en stiv
              beholder VARMES av kompresjonsarbeidet, så trykket stiger
              raskere enn dette. Isoterm alene OVERVURDERER tilgjengelig
              tid, og det er feil vei å bomme i et kontrollrom.
  adiabatisk  ingen varmeutveksling med omgivelsene, energibalansen løst med
              NeqSim sin VU-flash. Raskere trykkstigning, kortere tid.

Virkeligheten ligger mellom (litt varme går til stålet), så svaret oppgis
som et BÅND, og den adiabatiske enden vises som den styrende. Å presentere
ett tall her ville vært å late som presisjonen er bedre enn den er.

DETTE ER IKKE EN MÅLING. Det er et størrelsesordensanslag som skal fortelle
en operatør om han har sekunder eller titalls minutter. Settpunktet skal
verifiseres mot alarmdatabasen, ikke mot dette.

    python src/analysis/time_to_trip.py --selftest    # uten NeqSim/Java
    python src/analysis/time_to_trip.py --demo        # med NeqSim
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

if __name__ == "__main__" and __package__ is None:      # direct run support
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

R = 8.314462618           # J/(mol·K)
_BAR = 1e5                # Pa per bar


# ---------------------------------------------------------------------------
# Fluid-egenskaper — NeqSim når den finnes, idealgass som tydelig merket reserve
# ---------------------------------------------------------------------------

@dataclass
class FluidState:
    """Egenskaper ved ett driftspunkt, med kilden til dem."""
    density: float                  # kg/m3
    molar_mass: float               # kg/mol
    z: float                        # kompressibilitetsfaktor
    phase: str                      # "gas" / "liquid" / "ukjent"
    source: str                     # "neqsim" / "idealgass"
    note: str = ""


_IDEAL_M = 0.0179          # kg/mol — lett hydrokarbongass, kun for reserven


def fluid_state(fluid_code: str, p_bara: float, t_c: float) -> FluidState:
    """Tetthet/Z ved (P, T). Faller tilbake til idealgass hvis NeqSim mangler.

    Reserven er MERKET, ikke skjult: et anslag bygget på Z=1 er systematisk
    optimistisk om tilgjengelig tid ved høyt trykk, og det må leseren se.
    """
    try:
        if os.getenv("HULDRA_NO_NEQSIM") == "1":
            raise RuntimeError("NeqSim slått av med HULDRA_NO_NEQSIM=1")
        from neqsim.thermo import TPflash
        from neqsim_tools.fluid_lookup import get_preset, build_neqsim_fluid
        preset = get_preset(fluid_code)
        f = build_neqsim_fluid(preset)
        f.setPressure(float(p_bara), "bara")
        f.setTemperature(float(t_c), "C")
        TPflash(f)
        # Tettheten regnes som total masse / totalt volum, IKKE via
        # getDensity(): den returnerer 0,0 for CPA-systemene presetene bruker,
        # og getPhase(0).getDensity() ville gitt GASSFASENS tetthet — feil
        # størrelse når fluidet er tofase (PV-presetet har 5 % vann som
        # kondenserer ved 40 °C / 50 bara). Massebalansen trenger alt stoffet
        # i beholderen, uansett fase.
        volume = float(f.getVolume("m3"))
        moles = float(f.getNumberOfMoles())
        molar_mass = float(f.getMolarMass())
        n_phases = int(f.getNumberOfPhases())
        if volume <= 0:
            raise ValueError("NeqSim ga ikke-positivt volum")
        phase = str(f.getPhase(0).getPhaseTypeName())
        if n_phases > 1:
            phase = f"{phase} + {n_phases - 1} til"
        return FluidState(
            density=moles * molar_mass / volume,
            molar_mass=molar_mass,
            z=float(f.getPhase(0).getZ()),
            phase=phase,
            source="neqsim",
            note=preset.get("warning", "") or preset.get("description", ""))
    except Exception as e:                                  # noqa: BLE001
        rho = (p_bara * _BAR) * _IDEAL_M / (R * (t_c + 273.15))
        return FluidState(density=rho, molar_mass=_IDEAL_M, z=1.0, phase="gas",
                          source="idealgass",
                          note=f"NeqSim utilgjengelig ({type(e).__name__}) — "
                               f"Z=1 antatt, som UNDERVURDERER trykkstigningen "
                               f"ved høyt trykk og altså overvurderer tiden")


# ---------------------------------------------------------------------------
# Isoterm oppfylling — massedifferanse fra ekte gasstetthet
# ---------------------------------------------------------------------------

def time_isothermal(fluid_code: str, p0_bara: float, p_set_bara: float,
                    t_c: float, volume_m3: float, inflow_kg_h: float) -> dict:
    """Sekunder til settpunkt ved konstant temperatur.

    Ingen idealgass-antakelse i selve regnestykket: massen i beholderen ved
    hvert trykk kommer fra tettheten NeqSim gir, så
    t = (m(P_settpunkt) - m(P_start)) / massestrøm.
    """
    if inflow_kg_h <= 0 or volume_m3 <= 0 or p_set_bara <= p0_bara:
        return {"ok": False, "reason": "krever positiv strøm, volum og "
                                       "settpunkt over starttrykket"}
    s0 = fluid_state(fluid_code, p0_bara, t_c)
    s1 = fluid_state(fluid_code, p_set_bara, t_c)
    dm = (s1.density - s0.density) * volume_m3
    return {"ok": True, "seconds": dm / (inflow_kg_h / 3600.0),
            "added_kg": dm, "start": s0, "end": s1}


# ---------------------------------------------------------------------------
# Adiabatisk oppfylling — energibalanse via NeqSim VU-flash
# ---------------------------------------------------------------------------

def time_adiabatic(fluid_code: str, p0_bara: float, p_set_bara: float,
                   t_c: float, volume_m3: float, inflow_kg_h: float,
                   tol: float = 0.01, max_iter: int = 40) -> dict:
    """Sekunder til settpunkt uten varmeutveksling — den styrende enden.

    Stiv beholder, energibalanse U_slutt = U_start + m_tilført · h_inn.
    Innstrømningen antas å komme inn ved (p0, t_c); strømmer den inn varmere
    stiger trykket enda raskere, så anslaget forblir på den forsiktige siden
    av den antakelsen.

    Løses ved halvering på tilført molmengde, med VU-flash i hvert steg.
    Krever NeqSim/Java; returnerer ok=False ellers, og kalleren faller
    tilbake til det isoterme båndet alene.
    """
    try:
        if os.getenv("HULDRA_NO_NEQSIM") == "1":
            raise RuntimeError("slått av med HULDRA_NO_NEQSIM=1")
        from neqsim.thermo import TPflash, VUflash
        from neqsim_tools.fluid_lookup import get_preset, build_neqsim_fluid
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "reason": f"NeqSim utilgjengelig ({type(e).__name__})"}
    if inflow_kg_h <= 0 or volume_m3 <= 0 or p_set_bara <= p0_bara:
        return {"ok": False, "reason": "ugyldige prosessinput"}

    preset = get_preset(fluid_code)

    def _build(scale: float):
        """Fluid med komposisjonen skalert direkte.

        Skalering av komponentmengdene — ikke setTotalNumberOfMoles(). Den
        siste ga ikke-monotone og fysisk umulige resultater (settpunktsøket
        endte på 595 bara / 3190 °C); skalert komposisjon er monotont og
        holder sammensetningen konstant, som er det oppfyllingen faktisk gjør.
        """
        f = build_neqsim_fluid({**preset,
                                "components": [(c, m * scale)
                                               for c, m in preset["components"]]})
        f.setPressure(float(p0_bara), "bara")
        f.setTemperature(float(t_c), "C")
        TPflash(f)
        return f

    try:
        probe = _build(1.0)
        v_probe = float(probe.getVolume("m3"))
        if v_probe <= 0:
            return {"ok": False, "reason": "NeqSim ga ikke-positivt volum"}
        scale = volume_m3 / v_probe               # skaler opp til beholderen
        f0 = _build(scale)
        n0 = float(f0.getNumberOfMoles())
        u0 = float(f0.getInternalEnergy())
        h_in = float(f0.getEnthalpy()) / n0       # J/mol ved innløpsbetingelsen
        molar_mass = float(f0.getMolarMass())

        def pressure_after(frac: float) -> float:
            f = _build(scale * (1.0 + frac))
            VUflash(f, volume_m3, u0 + n0 * frac * h_in, "m3", "J")
            return float(f.getPressure("bara"))

        lo, hi = 0.0, 0.05
        for _ in range(max_iter):                 # utvid til settpunkt passeres
            if pressure_after(hi) >= p_set_bara:
                break
            lo, hi = hi, hi * 2
            if hi > 50.0:                         # 50x fylling — urealistisk
                return {"ok": False, "reason": "nådde ikke settpunktet innen "
                                               "realistisk tilført masse"}
        else:
            return {"ok": False, "reason": "settpunktsøket konvergerte ikke"}
        for _ in range(max_iter):
            mid = 0.5 * (lo + hi)
            if pressure_after(mid) < p_set_bara:
                lo = mid
            else:
                hi = mid
            if (hi - lo) <= tol * max(hi, 1e-9):
                break
        frac = 0.5 * (lo + hi)
        dm = n0 * frac * molar_mass
        f_end = _build(scale * (1.0 + frac))
        VUflash(f_end, volume_m3, u0 + n0 * frac * h_in, "m3", "J")
        return {"ok": True, "seconds": dm / (inflow_kg_h / 3600.0),
                "added_kg": dm,
                "end_temperature_c": float(f_end.getTemperature("C")),
                "end_pressure_bara": float(f_end.getPressure("bara"))}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}


# ---------------------------------------------------------------------------
# Væskefylling — nivåstigning, ingen termodynamikk nødvendig
# ---------------------------------------------------------------------------

def time_to_level(volume_to_fill_m3: float, inflow_kg_h: float,
                  fluid_code: str = "", p_bara: float = 1.0,
                  t_c: float = 20.0, density_kg_m3: float | None = None) -> dict:
    """Sekunder til nivåsettpunkt. Rent volumetrisk — tettheten brukes bare
    til å gjøre en massestrøm om til volumstrøm."""
    if volume_to_fill_m3 <= 0 or inflow_kg_h <= 0:
        return {"ok": False, "reason": "krever positivt volum og strøm"}
    if density_kg_m3 is None:
        st = fluid_state(fluid_code, p_bara, t_c)
        density_kg_m3, src = st.density, st.source
    else:
        src = "oppgitt"
    if density_kg_m3 <= 0:
        return {"ok": False, "reason": "ikke-positiv tetthet"}
    q_m3_s = (inflow_kg_h / 3600.0) / density_kg_m3
    return {"ok": True, "seconds": volume_to_fill_m3 / q_m3_s,
            "density_source": src, "density": density_kg_m3}


# ---------------------------------------------------------------------------
# Samlet anslag med antakelser og forbehold
# ---------------------------------------------------------------------------

@dataclass
class Estimate:
    ok: bool
    trip_tag: str = ""
    seconds_low: float | None = None      # adiabatisk — styrende
    seconds_high: float | None = None     # isoterm
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def estimate_pressure_trip(trip_tag: str, fluid_code: str, p0_bara: float,
                           p_set_bara: float, t_c: float, volume_m3: float,
                           inflow_kg_h: float) -> Estimate:
    """Båndet operatøren skal se, med hver antakelse eksplisitt."""
    iso = time_isothermal(fluid_code, p0_bara, p_set_bara, t_c,
                          volume_m3, inflow_kg_h)
    if not iso["ok"]:
        return Estimate(ok=False, trip_tag=trip_tag, warnings=[iso["reason"]])
    adi = time_adiabatic(fluid_code, p0_bara, p_set_bara, t_c,
                         volume_m3, inflow_kg_h)

    st = iso["start"]
    assumptions = [
        f"volum {volume_m3:g} m³, netto innstrømning {inflow_kg_h:g} kg/h — "
        f"OPPGITT, ikke lest fra tegningen",
        f"settpunkt {p_set_bara:g} bara — OPPGITT; verifiser mot alarmdatabasen",
        f"start {p0_bara:g} bara / {t_c:g} °C, fluidkode {fluid_code or '(ingen)'}",
        f"egenskaper fra {st.source} (Z={st.z:.3f}, {st.density:.1f} kg/m³, "
        f"fase: {st.phase})",
        "konstant innstrømning; ingen utstrømning; beholderen er stiv",
    ]
    warnings = []
    if st.note:
        warnings.append(f"fluidsammensetning: {st.note[:180]}")
    if st.source != "neqsim":
        warnings.append("NeqSim ikke brukt — anslaget er optimistisk om tid")
    if st.phase and "gas" not in st.phase.lower():
        warnings.append(f"fasen ved startpunktet er «{st.phase}» — "
                        f"gassmodellen passer dårlig, tolk med forsiktighet")
    if not adi["ok"]:
        warnings.append(f"adiabatisk grense ikke beregnet ({adi['reason']}) — "
                        f"kun isoterm vist, som OVERVURDERER tilgjengelig tid")

    return Estimate(
        ok=True, trip_tag=trip_tag,
        seconds_low=adi["seconds"] if adi["ok"] else None,
        seconds_high=iso["seconds"],
        assumptions=assumptions, warnings=warnings,
        detail={"isothermal": iso, "adiabatic": adi})


def format_estimate(e: Estimate) -> str:
    if not e.ok:
        return "Kunne ikke beregne: " + "; ".join(e.warnings)

    def _t(s):
        return f"{s:.0f} s" if s < 90 else f"{s/60:.1f} min"

    if e.seconds_low is not None:
        head = (f"{e.trip_tag}: settpunkt nås om **{_t(e.seconds_low)} – "
                f"{_t(e.seconds_high)}**")
        sub = (f"  adiabatisk {_t(e.seconds_low)} (styrende) · "
               f"isoterm {_t(e.seconds_high)} (øvre grense)")
    else:
        head = f"{e.trip_tag}: settpunkt nås om ~{_t(e.seconds_high)} (isoterm)"
        sub = "  kun øvre grense beregnet"
    lines = [head, sub, "", "  Antakelser:"]
    lines += [f"    · {a}" for a in e.assumptions]
    if e.warnings:
        lines += ["", "  Forbehold:"] + [f"    ⚠ {w}" for w in e.warnings]
    lines += ["", "  Størrelsesordensanslag for beslutningsstøtte — ikke en "
                  "måling. Virkelig tid ligger nær den adiabatiske enden."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Koblingen til tegningen — hvilken trip er det vi regner mot?
# ---------------------------------------------------------------------------

_RELIEF_TYPES = {"PSV", "PSE"}


def pressure_protection_for(graph, by_tag, tag: str) -> list[dict]:
    """Trykkbeskyttelse som vokter `tag`: [{'tag': ..., 'kind': ...}].

    Dette er delen tegningen FAKTISK svarer på. Gjenbruker kontrollrommets
    barriere-søk og retningslogikken fra hazop_prep, så «hvilken beskyttelse»
    er konsistent med det HAZOP-arket og operatør-briefen sier — ett svar,
    ikke tre. Settpunktet må fortsatt oppgis; det står ikke på tegningen.

    BEGGE typer tas med, og det er ikke pedanteri: i dette datasettet finnes
    2 PSHH og 1 LSH mot 11 PSV og 6 PSE blant 885 tags. Trykkbeskyttelsen er
    altså i praksis AVLASTNING, ikke trip. Så «hvor lenge til PSV-en løfter»
    er det operasjonelt meningsfulle spørsmålet her, mens en ren trip-søking
    ville returnert nesten ingenting og sett ut som en kodefeil.

    Fysikken er den samme — et settpunkt i trykk er et settpunkt — men
    konsekvensen er ulik, så `kind` følger med: en trip stenger, en
    avlastning slipper ut.
    """
    from analysis.control_room import relevant_barriers
    from analysis.hazop_prep import _deviations_guarded
    out = {}
    for t in relevant_barriers(graph, by_tag, tag):
        tc = getattr(by_tag.get(t), "type_code", "") or ""
        if tc in _RELIEF_TYPES:
            out[t] = "avlastning"
        elif "High pressure" in _deviations_guarded(tc):
            out[t] = "trip"
    return [{"tag": t, "kind": k} for t, k in sorted(out.items())]


# ---------------------------------------------------------------------------
# Selvtest — analytisk kontrollerbar, kjører uten NeqSim/Java
# ---------------------------------------------------------------------------

def _selftest() -> int:
    ok = True
    checks = []

    # 1) idealgass-reserven skal treffe den analytiske løsningen
    #    m = P·V·M/(R·T);  t = Δm / ṁ
    V, T_c, p0, p1, w = 10.0, 27.0, 10.0, 20.0, 100.0
    T = T_c + 273.15
    dm_analytic = (p1 - p0) * _BAR * V * _IDEAL_M / (R * T)
    t_analytic = dm_analytic / (w / 3600.0)
    r = time_isothermal("__finnes_ikke__", p0, p1, T_c, V, w)
    # (med NeqSim tilgjengelig treffer denne ekte gass, ikke idealgass, så
    #  sammenlign bare når reserven faktisk ble brukt)
    if r["ok"] and r["start"].source == "idealgass":
        checks.append(("idealgass-reserve matcher analytisk løsning",
                       abs(r["seconds"] - t_analytic) / t_analytic < 1e-9))
    else:
        checks.append(("idealgass-sjekk hoppet over (NeqSim tilgjengelig)", True))

    # 2) monotoni: høyere settpunkt -> lengre tid
    a = time_isothermal("PV", 10.0, 20.0, 27.0, 10.0, 100.0)
    b = time_isothermal("PV", 10.0, 40.0, 27.0, 10.0, 100.0)
    checks.append(("høyere settpunkt gir lengre tid",
                   a["ok"] and b["ok"] and b["seconds"] > a["seconds"]))

    # 3) dobbelt volum -> dobbelt tid;  dobbel strøm -> halv tid
    c = time_isothermal("PV", 10.0, 20.0, 27.0, 20.0, 100.0)
    d = time_isothermal("PV", 10.0, 20.0, 27.0, 10.0, 200.0)
    checks.append(("dobbelt volum gir dobbelt tid",
                   abs(c["seconds"] - 2 * a["seconds"]) < 1e-6 * c["seconds"]))
    checks.append(("dobbel strøm gir halv tid",
                   abs(d["seconds"] - a["seconds"] / 2) < 1e-6 * a["seconds"]))

    # 4) ugyldige input avvises, ikke gjettes
    for bad in (time_isothermal("PV", 10.0, 5.0, 27.0, 10.0, 100.0),
                time_isothermal("PV", 10.0, 20.0, 27.0, 0.0, 100.0),
                time_isothermal("PV", 10.0, 20.0, 27.0, 10.0, 0.0)):
        checks.append(("ugyldig input avvist", bad["ok"] is False))

    # 5) væskefylling er ren volumetrikk
    lv = time_to_level(2.0, 3600.0, density_kg_m3=1000.0)
    checks.append(("nivåtid = volum / volumstrøm",
                   lv["ok"] and abs(lv["seconds"] - 2000.0) < 1e-6))

    # 6) formatteringen skjuler ikke forbehold
    e = estimate_pressure_trip("27-PSHH4811", "PV", 10.0, 20.0, 27.0, 10.0, 100.0)
    txt = format_estimate(e)
    checks.append(("antakelser vises i utskriften", "Antakelser:" in txt))
    checks.append(("settpunkt merket som oppgitt", "OPPGITT" in txt))

    # 7) fysisk invariant: adiabatisk fylling varmer innholdet, så settpunktet
    #    nås TIDLIGERE enn isotermt. Slår denne feil, er fortegnet et sted galt
    #    — og feilen ville pekt i den farlige retningen (lovet for mye tid).
    if e.seconds_low is not None:
        checks.append(("adiabatisk <= isoterm (oppvarming korter ned tiden)",
                       e.seconds_low <= e.seconds_high))
        checks.append(("båndet er ikke absurd bredt (< 3x)",
                       e.seconds_high / max(e.seconds_low, 1e-9) < 3.0))
    else:
        checks.append(("adiabatisk hoppet over (NeqSim utilgjengelig)", True))

    # 8) tettheten er systemets, ikke gassfasens — tofase-fluid skal gi en
    #    tetthet MELLOM gass og væske, ikke gassfasens alene
    st = fluid_state("PV", 50.0, 40.0)
    if st.source == "neqsim":
        checks.append(("systemtetthet brukt (positiv, ikke 0 fra CPA)",
                       st.density > 1.0))

    for name, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok &= bool(passed)
    return 0 if ok else 1


def _demo() -> int:
    """Hele kjeden på ekte anleggsdata: tegningen peker ut beskyttelsen,
    oppgitte driftstall gir fysikken, NeqSim gir tiden."""
    print("Scenario: blokkert utløp. Tegningen peker ut beskyttelsen;\n"
          "driftstallene er OPPGITT (de står ikke på et P&ID).\n")
    target, prot = None, None
    try:
        from pathlib import Path as _P
        from analysis.plant_model import build_plant_model
        m = build_plant_model(_P("data/raw"))
        g, by_tag = m["graph"], {o.tag: o for o in m["objects"]}
        for t in sorted(g.nodes):
            pr = pressure_protection_for(g, by_tag, t)
            if pr:
                target, prot = t, pr[0]
                break
    except Exception as e:                                  # noqa: BLE001
        print(f"  (anleggsmodell utilgjengelig: {type(e).__name__} — "
              f"bruker et frittstående eksempel)\n")

    if target:
        print(f"  {target} er blokkert. Grafen finner beskyttelsen: "
              f"{prot['tag']} ({prot['kind']}).\n")
        trip = prot["tag"]
    else:
        trip = "27-PSV4809"

    e = estimate_pressure_trip(trip_tag=trip, fluid_code="PV",
                               p0_bara=50.0, p_set_bara=65.0, t_c=40.0,
                               volume_m3=8.0, inflow_kg_h=1200.0)
    print(format_estimate(e))
    d = e.detail.get("adiabatic", {})
    if d.get("ok"):
        print(f"\n  (adiabatisk slutt-tilstand: {d['end_pressure_bara']:.1f} bara, "
              f"{d['end_temperature_c']:.1f} °C — oppvarmingen er grunnen til at "
              f"denne enden er kortere)")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--demo":
        sys.exit(_demo())
    if args and args[0] == "--selftest":
        sys.exit(_selftest())
    sys.exit("bruk: python src/analysis/time_to_trip.py --selftest | --demo")
