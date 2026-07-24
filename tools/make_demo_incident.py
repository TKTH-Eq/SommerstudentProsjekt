"""Generate a HISTORICAL demo incident dataset — SYNTHETIC, for demonstration.

Produces a folder that looks like an export from an alarm & event journal
plus a process historian, for ONE incident with ~15 alarms:

    demo_incident/
      alarms.csv     one row per alarm activation (A&E journal style)
      trends.csv     1 Hz process values per alarmed tag (historian style)
      incident.json  metadata + the SOLUTION (root/cascade/noise) for debrief
      README.md      what this is and what it is NOT

Two modes:

  REAL-MODEL MODE (default, run inside the project on your machine):
      python tools/make_demo_incident.py --out data/demo_incident
      python tools/make_demo_incident.py --fault 13-PT0101 --alarms 15
  Loads the plant model (all drawings), picks a fault whose cascade gives
  a rich board, runs the SAME alarm_shower + synthetic_trends engine as
  the Control Room page, and anchors it at a fictive historical night
  shift. Tags, cascade and priorities are then REAL (from the DEXPI/SCD
  model); only the timestamps and process values are synthetic.

  FALLBACK MODE (no DEXPI data available):
      python tools/make_demo_incident.py --fallback --out demo_incident
  Uses a built-in, oil&gas-plausible mini flowsheet (separator pressure
  incident) so the dataset format can be demonstrated anywhere.

Everything is deterministic for a given --seed.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

START = datetime(2024, 11, 7, 3, 14, 0, tzinfo=timezone.utc)  # night shift

TYPE_WORD = {"P": "PRESSURE", "T": "TEMPERATURE", "L": "LEVEL",
             "F": "FLOW", "X": "POSITION", "A": "ANALYSER"}


def _msg(tag: str, sem: dict) -> str:
    word = TYPE_WORD.get(tag.split("-")[-1][:1] if "-" in tag else tag[:1],
                         "PROCESS")
    d = sem.get("direction")
    lvl = {"high": "HIGH", "low": "LOW"}.get(d, "DEVIATION")
    trip = " TRIP" if sem.get("priority") == 1 else ""
    return f"{word} {lvl}{trip} ALARM"


def _fallback_model():
    """Built-in mini flowsheet: 1st-stage separator pressure incident."""
    import networkx as nx
    from analysis.alarm_priority import alarm_semantics

    class Obj:
        def __init__(self, tag, category):
            self.tag, self.category = tag, category
            self.type_code = tag.split("-")[1][:3].rstrip("0123456789")
            sem = alarm_semantics(self.type_code)
            self.priority = sem.get("priority", 3)
            self.alarm_direction = sem.get("direction")
            self.loop = tag.split("-")[1]

    spec = [  # (tag, category)  — cascade order below
        ("13-PT101", "input"), ("13-PIC101", "logic"), ("13-PV101", "output"),
        ("13-PSH101", "input"), ("13-FT102", "input"), ("20-TT201", "input"),
        ("20-TSH201", "input"), ("13-LT103", "input"), ("13-LSH103", "input"),
        ("27-PT301", "input"), ("27-PSL301", "input"),
        # noise pool (independent systems)
        ("71-LT710", "input"), ("45-FT450", "input"),
        ("27-TT4806", "input"), ("82-XA820", "logic"), ("45-PT451", "input"),
    ]
    by_tag = {t: Obj(t, c) for t, c in spec}
    g = nx.DiGraph()
    g.add_nodes_from(by_tag)
    chain = [s[0] for s in spec[:11]]
    for a, b in zip(chain, chain[1:]):
        g.add_edge(a, b)
    return g, by_tag, "13-PT101"


def _real_model():
    from analysis.plant_model import build_plant_model
    raw = Path(__file__).resolve().parent.parent / "data" / "raw"
    M = build_plant_model(raw)
    return M["graph"], {o.tag: o for o in M["objects"]}


def build(args) -> dict:
    from analysis.alarm_priority import alarm_semantics
    from analysis.control_room import alarm_shower, synthetic_trends, synthetic_chatter, eng_of

    if args.fallback:
        g, by_tag, fault = _fallback_model()
        if args.fault:
            fault = args.fault
    else:
        g, by_tag = _real_model()
        fault = args.fault
        if not fault:  # pick a fault with a rich, but not absurd, cascade —
            # and REQUIRE the root itself to be alarm-capable: a silent
            # root (e.g. a hand valve) never rings, never reaches the
            # board, and the operator could never point at it.
            from analysis.control_room import (scenario_order, alarm_capable)
            best = None
            for n in g.nodes:
                if not alarm_capable(by_tag.get(n)):
                    continue
                k = sum(1 for t in scenario_order(g, n)
                        if alarm_capable(by_tag.get(t)))
                if 8 <= k <= args.alarms and (best is None or k > best[1]):
                    best = (n, k)
            if not best:
                sys.exit("No alarm-capable fault with a suitable cascade "
                         "found; pass --fault explicitly.")
            fault = best[0]
        else:
            from analysis.control_room import alarm_capable
            if not args.fallback and not alarm_capable(by_tag.get(fault)):
                print(f"WARNING: {fault} is not alarm-capable — it will "
                      f"never ring, so the operator cannot point at it. "
                      f"The debrief will explain this, but consider an "
                      f"alarming root for training scenarios.")

    # size the noise so the board lands on ~args.alarms
    shower = alarm_shower(g, fault, noise=2, seed=args.seed, by_tag=by_tag,
                          step=args.step)
    need = max(0, args.alarms - (len(shower["alarms"]) - len(shower["noise"])))
    shower = alarm_shower(g, fault, noise=need, seed=args.seed,
                          by_tag=by_tag, step=args.step)
    alarms = shower["alarms"][:args.alarms]
    timeline = {t: shower["timeline"][t] for t in alarms}
    window = max(timeline.values())
    trends = synthetic_trends(timeline, window, by_tag,
                              seed=str(args.seed),
                              noise_level=args.noise_level)
    chatter = synthetic_chatter([t for t in shower["noise"] if t in timeline],
                                timeline, window, seed=str(args.seed))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with (out / "alarms.csv").open("w", newline="", encoding="utf-8") as f:
        wcsv = csv.writer(f)
        wcsv.writerow(["time_iso", "offset_s", "tag", "type_code",
                       "priority", "direction", "message", "state"])
        events = []                      # (t, tag, state)
        for tag in timeline:
            if tag in chatter:
                for a in chatter[tag]["alm"]:
                    events.append((a, tag, "ALM"))
                for r in chatter[tag]["rtn"]:
                    events.append((r, tag, "RTN"))
            else:
                events.append((timeline[tag], tag, "ALM"))
        for t, tag, state in sorted(events):
            o = by_tag.get(tag)
            sem = alarm_semantics(getattr(o, "type_code", "")) if o else {}
            wcsv.writerow([(START + timedelta(seconds=t)).isoformat(),
                           f"{t:.1f}", tag,
                           getattr(o, "type_code", ""),
                           f"P{sem.get('priority', '?')}",
                           sem.get("direction") or "",
                           _msg(tag, sem), state])

    with (out / "trends.csv").open("w", newline="", encoding="utf-8") as f:
        wcsv = csv.writer(f)
        wcsv.writerow(["time_iso", "offset_s", "tag", "value_pct",
                       "value_eng", "unit"])
        for tag in sorted(timeline, key=timeline.get):
            for tt, v in zip(trends["t"], trends["series"][tag]):
                ev, eu = eng_of(tag, v, by_tag)
                wcsv.writerow([(START + timedelta(seconds=tt)).isoformat(),
                               f"{tt:.1f}", tag, v, f"{ev:.2f}", eu])

    meta = {
        "title": "Demo incident — 1st stage separator pressure excursion",
        "site": "Huldra (SYNTHETIC demonstration data)",
        "synthetic": True,
        "note": ("Alarm ORDER and cascade come from the structural model "
                 "(real in real-model mode); timestamps and process values "
                 "are generated. Not measured plant data."),
        "start_iso": START.isoformat(),
        "window_s": window,
        "alarm_count": len(alarms),
        "first_up": shower.get("first_up"),
        "sample_rate_hz": 1,
        "chatter": {t: len(d["alm"]) for t, d in chatter.items()},
        "generator": {"seed": args.seed, "step_s": args.step,
                      "noise_level": args.noise_level,
                      "mode": "fallback" if args.fallback else "real-model"},
        "solution": {"fault": fault,
                     "cascade": [t for t in alarms
                                 if t not in shower["noise"]],
                     "noise": [t for t in alarms if t in shower["noise"]]},
    }
    (out / "incident.json").write_text(json.dumps(meta, indent=2),
                                       encoding="utf-8")

    (out / "README.md").write_text(
        "# Demo incident dataset (SYNTHETIC)\n\n"
        f"One historical-style incident, {len(alarms)} alarms over "
        f"{window:.0f} s, anchored {START.isoformat()} (fictive night "
        "shift).\n\n"
        "| file | content |\n|---|---|\n"
        "| `alarms.csv` | alarm & event journal: one row per activation |\n"
        "| `trends.csv` | historian export: 1 Hz values per alarmed tag, "
        "0–100 % of range, HI limit 80 / LO limit 20 |\n"
        "| `incident.json` | metadata + the solution (root/cascade/noise) "
        "— keep hidden during the exercise |\n\n"
        "**This is demonstration data.** The alarm order and cascade follow "
        "the structural model; the timestamps and process values are "
        "generated (each tag drifts from baseline before its alarm and "
        "crosses its limit at the alarm time). It shows the *format and "
        "workflow* of a historian-connected pilot — it is not measured "
        "plant data.\n", encoding="utf-8")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/demo_incident")
    ap.add_argument("--fault", default=None,
                    help="root tag (default: auto-pick / built-in)")
    ap.add_argument("--alarms", type=int, default=15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--step", type=float, default=3.0,
                    help="seconds between cascade alarms")
    ap.add_argument("--noise-level", type=float, default=0.0,
                    help="trend imperfection: 0=clean, ~1=realistic, "
                         "~2=harsh (robustness testing)")
    ap.add_argument("--fallback", action="store_true",
                    help="use built-in mini flowsheet (no DEXPI needed)")
    a = ap.parse_args()
    m = build(a)
    print(f"Wrote {a.out}: {m['alarm_count']} alarms, "
          f"window {m['window_s']:.0f}s, first-up {m['first_up']}, "
          f"root {m['solution']['fault']}")