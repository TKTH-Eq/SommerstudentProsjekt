# src/neqsim_hydrate_viz.py
"""
Visualisering med NeqSim: hydratkurve + sanntids-animert nedblaasing.

To deler:

  1. plot_hydrate_curve()
     Statisk plott: hydrattemperatur vs. trykk, med flere MEG-konsentrasjoner
     paa samme figur. Rett frem utvidelse av Trinn 3 i test_neqsim.py, bare
     over et kontinuerlig trykkomraade i stedet for fire faste punkter.

  2. simulate_blowdown_live()
     ANIMERT: simulerer en nedblaasing (blowdown) — trykket i et system som
     faller over tid, f.eks. naar en ESV/nedblaasingsventil aapner. For hvert
     tidssteg beregner NeqSim hydrattemperaturen ved det gjeldende trykket
     (hydt()), og vi sammenligner den mot en antatt prosess-temperatur.
     Grafen oppdateres live mens simuleringen "spilles av" — naar hydrat-
     kurven krysser prosesstemperaturen, er man i hydratdannelsesomraadet.

     FORENKLING, vaer aerlig om dette: prosesstemperaturen her er en enkel
     avkjølingsmodell (eksponentiell mot en sluttemperatur), IKKE en ekte
     Joule-Thomson-beregning fra NeqSim. Det er en illustrasjon av
     PRINSIPPET (trykkfall -> hydratkurven stiger -> risiko for underkjoeling
     i vaate gasslinjer), ikke en presis prosessmodell for en ekte hendelse.
     Skal dette brukes til noe reelt, boer den erstattes med en faktisk
     NeqSim-basert throttling/energibalanse-beregning.

Kjor:  python src/neqsim_hydrate_viz.py
"""

import sys

import matplotlib.pyplot as plt
import numpy as np

try:
    from neqsim.thermo import fluid, TPflash, hydt
except ImportError as e:
    sys.exit(f"FEIL: NeqSim ikke installert ({e}). Kjor: pip install neqsim")
except Exception as e:
    sys.exit(f"FEIL ved oppstart av JVM: {e}")


# ---------------------------------------------------------------------------
# Felles: bygg en typisk vaat brønnstroemsgass (samme sammensetning som
# test_neqsim.py sin Trinn 3, gjenbrukt her for konsistens)
# ---------------------------------------------------------------------------

def lag_vaat_gass(meg_mol: float = 0.0):
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
    f.setMixingRule(10)
    f.setMultiPhaseCheck(True)
    return f


# ---------------------------------------------------------------------------
# 1. Statisk hydratkurve
# ---------------------------------------------------------------------------

def plot_hydrate_curve(trykk_min=10, trykk_maks=150, n_punkter=15,
                        meg_konsentrasjoner=(0.0, 0.75, 1.5, 3.0)):
    """Hydrattemperatur vs. trykk, en kurve per MEG-konsentrasjon."""
    trykk = np.linspace(trykk_min, trykk_maks, n_punkter)

    plt.figure(figsize=(9, 6))
    for meg in meg_konsentrasjoner:
        temps = []
        for p in trykk:
            f = lag_vaat_gass(meg)
            f.setPressure(float(p), "bara")
            f.setTemperature(10.0, "C")  # startgjett for hydt()
            try:
                hydt(f)
                temps.append(f.getTemperature("C"))
            except Exception:
                temps.append(np.nan)
        label = "uten MEG" if meg == 0 else f"{meg} mol% MEG"
        plt.plot(trykk, temps, marker="o", markersize=4, label=label)

    plt.xlabel("Trykk [bara]")
    plt.ylabel("Hydrattemperatur [°C]")
    plt.title("Hydratkurve — omraadet OVER hver linje er hydratdannelse")
    plt.legend(title="MEG-inhibering")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig("hydrate_curve.png", dpi=150)
    print("Lagret hydrate_curve.png")
    plt.show()


# ---------------------------------------------------------------------------
# 2. Sanntids-animert nedblaasing
# ---------------------------------------------------------------------------

def simulate_blowdown_live(
    start_trykk=100.0, slutt_trykk=15.0, varighet_s=40,
    start_temp=25.0, slutt_temp=-15.0, meg_mol=0.0,
):
    """
    Animert simulering av en nedblaasing: trykket faller fra start_trykk til
    slutt_trykk over varighet_s "sekunder" (simulert tid, ikke ekte klokketid
    -- animasjonen spilles av saa fort matplotlib klarer aa tegne den).

    Prosesstemperaturen faller samtidig mot slutt_temp (forenklet eksponentiell
    avkjøling, se advarsel i modulens docstring). For hvert steg beregner
    NeqSim hydrattemperaturen ved DET gjeldende trykket -- naar
    prosesstemperaturen krysser under hydratkurven, markeres hydratrisiko.
    """
    n_steg = 60
    t = np.linspace(0, varighet_s, n_steg)

    # Enkel eksponentiell tilnaerming for trykk- og temperaturfall
    trykk_serie = slutt_trykk + (start_trykk - slutt_trykk) * np.exp(-3 * t / varighet_s)
    temp_serie = slutt_temp + (start_temp - slutt_temp) * np.exp(-3 * t / varighet_s)

    print("Beregner hydrattemperatur for hvert trykksteg (kan ta litt tid)...")
    hydrat_temp_serie = []
    for p in trykk_serie:
        f = lag_vaat_gass(meg_mol)
        f.setPressure(float(p), "bara")
        f.setTemperature(10.0, "C")
        try:
            hydt(f)
            hydrat_temp_serie.append(f.getTemperature("C"))
        except Exception:
            hydrat_temp_serie.append(np.nan)
    hydrat_temp_serie = np.array(hydrat_temp_serie)

    # --- sett opp figuren med tre paneler ---
    plt.ion()
    fig, (ax_p, ax_t, ax_margin) = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    fig.suptitle("Nedblaasingssimulering — hydratrisiko i sanntid", fontsize=13)

    ax_p.set_ylabel("Trykk [bara]")
    ax_p.set_xlim(0, varighet_s)
    ax_p.set_ylim(0, start_trykk * 1.1)
    ax_p.grid(alpha=0.3)
    linje_p, = ax_p.plot([], [], color="#16233A", lw=2)

    ax_t.set_ylabel("Temperatur [°C]")
    ax_t.set_xlim(0, varighet_s)
    y_min = min(slutt_temp, np.nanmin(hydrat_temp_serie)) - 5
    y_max = max(start_temp, np.nanmax(hydrat_temp_serie)) + 5
    ax_t.set_ylim(y_min, y_max)
    ax_t.grid(alpha=0.3)
    linje_proc, = ax_t.plot([], [], color="#E8640F", lw=2, label="Prosesstemperatur")
    linje_hyd, = ax_t.plot([], [], color="#2E7D5B", lw=2, ls="--", label="Hydrattemperatur")
    ax_t.legend(loc="upper right", fontsize=9)

    ax_margin.set_ylabel("Margin [°C]")
    ax_margin.set_xlabel("Tid [s]")
    ax_margin.set_xlim(0, varighet_s)
    margin_full = temp_serie - hydrat_temp_serie
    ax_margin.set_ylim(min(margin_full.min(), -5) - 2, max(margin_full.max(), 5) + 2)
    ax_margin.axhline(0, color="red", lw=1, ls=":")
    ax_margin.grid(alpha=0.3)
    linje_margin, = ax_margin.plot([], [], color="#7A6FB0", lw=2)
    fyll = None

    status_tekst = fig.text(0.5, 0.955, "", ha="center", fontsize=10, color="red")

    xs, ps, ts, hs, ms = [], [], [], [], []
    for i in range(n_steg):
        xs.append(t[i]); ps.append(trykk_serie[i])
        ts.append(temp_serie[i]); hs.append(hydrat_temp_serie[i])
        ms.append(margin_full[i])

        linje_p.set_data(xs, ps)
        linje_proc.set_data(xs, ts)
        linje_hyd.set_data(xs, hs)
        linje_margin.set_data(xs, ms)

        i_hydratrisiko = margin_full[i] < 0
        status_tekst.set_text(
            "⚠ HYDRATRISIKO — prosesstemp under hydratkurven" if i_hydratrisiko else ""
        )
        linje_margin.set_color("red" if i_hydratrisiko else "#7A6FB0")

        fig.canvas.draw()
        fig.canvas.flush_events()
        plt.pause(varighet_s / n_steg / 8)  # spill av raskere enn "ekte" tid

    plt.ioff()
    plt.savefig("blowdown_simulation_final.png", dpi=150)
    print("Simulering ferdig. Sluttbilde lagret som blowdown_simulation_final.png")
    plt.show()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== 1) Statisk hydratkurve ===")
    plot_hydrate_curve()

    print("\n=== 2) Sanntids-animert nedblaasing (uten MEG) ===")
    simulate_blowdown_live(meg_mol=0.0)

    # Provoer gjerne aa kjore den samme simuleringen MED MEG-inhibering, og se
    # hvordan margin-panelet endrer seg naar hydratkurven presses nedover:
    # simulate_blowdown_live(meg_mol=1.5)