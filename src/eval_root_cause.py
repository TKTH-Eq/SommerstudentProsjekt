"""
Eval harness — the thesis, made measurable.

The assistant's core claim is "the root explains the most". This script turns
that into a reproducible number: over many synthetic faults, how often does
the TRUE root come out as the #1 candidate, and how often in the top 3?

For each fault it builds the staggered alarm shower (cascade + noise), runs the
same candidate_brief the UI uses, and checks the rank of the true root (the
first alarm-capable node of the cascade — the alarm that actually rings first
in causal order). Results are aggregated over noise levels and seeds.

Runs on the real Huldra DEXPI model when data/raw is present; otherwise on a
deterministic synthetic plant so the harness is always runnable.

    python eval/eval_root_cause.py                # auto: real if data, else synthetic
    python eval/eval_root_cause.py --seeds 10 --noise 0 1 2 3
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import networkx as nx
from models.engineering_object import EngineeringObject as E
from analysis.control_room import (alarm_capable, alarm_shower,
                                   candidate_brief, scenario_order)


def load_or_synthetic(raw: Path):
    """Return (graph, by_tag, label). Real plant if DEXPI data exists."""
    if raw.exists() and any(raw.rglob("*.DGN.xml")):
        from analysis.plant_model import build_plant_model
        m = build_plant_model(raw)
        return m["graph"], {o.tag: o for o in m["objects"]}, "real Huldra model"
    return (*_synthetic_big(), "synthetic fallback plant")


def _synthetic_big(n_chains: int = 8, depth: int = 6):
    """A deterministic multi-chain plant with measuring roots, controllers,
    valves and trips — enough faults to make the metric meaningful offline."""
    g = nx.DiGraph()
    by_tag = {}
    heads = ["PT", "TT", "LT", "FT"]
    for c in range(n_chains):
        sysn = f"{20 + c:02d}"
        prev = None
        chain_types = [heads[c % len(heads)], "PIC", "PV", "XV", "LAHH", "TT"]
        for d in range(depth):
            tc = chain_types[d % len(chain_types)]
            tag = f"{sysn}-{tc}{100 * c + d:04d}"
            o = E.from_tag(tag, "SCD")
            by_tag[tag] = o
            g.add_node(tag, category=o.category)
            if prev is not None:
                g.add_edge(prev, tag)
            prev = tag
    return g, by_tag


def true_root(g, by_tag, shower) -> str | None:
    for t in shower["cascade"]:
        if alarm_capable(by_tag.get(t)):
            return t
    return None


def root_rank(briefs, root) -> int | None:
    for i, b in enumerate(briefs, 1):
        if b["tag"] == root or root in b.get("group", []):
            return i
    return None


def _drop(alarms, cascade, p, rng):
    """Each CASCADE alarm fails to ring with probability p (noise stays).
    Models missed alarms / partial observability. Keeps at least one
    cascade alarm. Returns (surviving alarms, surviving cascade order)."""
    casc = [t for t in alarms if t in set(cascade)]
    keep = [t for t in casc if rng.random() >= p] or casc[:1]
    keep_set = set(keep) | {t for t in alarms if t not in set(cascade)}
    return [t for t in alarms if t in keep_set], \
           [t for t in cascade if t in keep_set]


def run(g, by_tag, seeds: int, noises: list[int], max_faults: int,
        drop: float = 0.0, dual: bool = False, offset: float = 0.0,
        use_time: bool = False) -> dict:
    """One eval condition.

    drop  : probability each cascade alarm fails to ring. The scored root is
            the EFFECTIVE root — the earliest cascade alarm that actually
            rang (if the true root's own alarm is lost, no ranking can name
            it; the fair question is whether the earliest observable symptom
            tops the list).
    dual  : a second, independent fault fires; both cascades ring.
            hit1 = the #1 candidate is one of the two true roots;
            hit3 = BOTH roots are in the top 3.
    offset: seconds between the two faults. The original harness started
            both at t=0, which is the hardest case AND an unrealistic one —
            two genuinely independent faults rarely begin in the same
            second. Sweeping this is what makes the timing question
            answerable instead of assumed.
    use_time: pass the merged arrival timeline to candidate_brief, so time
            can act as a tiebreaker. Run both ways on identical scenarios
            (same seeds, same faults) — that paired design is what makes the
            with/without comparison mean anything.
    """
    import random as _r
    faults = [n for n in g.nodes
              if alarm_capable(by_tag.get(n)) and len(scenario_order(g, n)) >= 4]
    faults = sorted(faults)[:max_faults]
    n = hit1 = hit3 = found = rank_sum = 0
    hist = {}
    for fi, fault in enumerate(faults):
        for noise in noises:
            for s in range(seeds):
                seed = 1000 + s
                shower = alarm_shower(g, fault, noise=noise, seed=seed,
                                      by_tag=by_tag)
                rng = _r.Random(seed * 7919 + fi)
                alarms, casc = shower["alarms"], shower["cascade"]
                timeline = dict(shower["timeline"])
                if drop > 0:
                    alarms, casc = _drop(alarms, casc, drop, rng)
                roots = []
                eff = next((t for t in casc
                            if alarm_capable(by_tag.get(t))), None)
                if eff:
                    roots.append(eff)
                if dual:
                    other = faults[(fi + len(faults) // 2) % len(faults)]
                    if other != fault and other not in set(shower["cascade"]):
                        sh2 = alarm_shower(g, other, noise=0, seed=seed + 1,
                                           by_tag=by_tag)
                        a2, c2 = sh2["alarms"], sh2["cascade"]
                        if drop > 0:
                            a2, c2 = _drop(a2, c2, drop, rng)
                        alarms = sorted(set(alarms) | set(a2))
                        # the second fault starts `offset` seconds later —
                        # an alarm shared by both cascades keeps its EARLIEST
                        # arrival, which is what an operator would see
                        for t, v in sh2["timeline"].items():
                            shifted = round(v + offset, 2)
                            timeline[t] = min(timeline.get(t, shifted), shifted)
                        eff2 = next((t for t in c2
                                     if alarm_capable(by_tag.get(t))), None)
                        if eff2 and eff2 not in roots:
                            roots.append(eff2)
                if not roots:
                    continue
                briefs = candidate_brief(g, by_tag, alarms,
                                         timeline=timeline if use_time else None,
                                         cluster_gap=2.0 * shower["step"])
                ranks = [root_rank(briefs, r) for r in roots]
                n += 1
                if any(r is None for r in ranks):
                    continue
                found += 1
                r_first = min(ranks)
                rank_sum += r_first
                hist[r_first] = hist.get(r_first, 0) + 1
                if dual and len(roots) > 1:
                    if r_first == 1:
                        hit1 += 1
                    if max(ranks) <= 3:
                        hit3 += 1
                else:
                    if ranks[0] == 1:
                        hit1 += 1
                    if ranks[0] <= 3:
                        hit3 += 1
    return {"scenarios": n, "faults": len(faults), "hit1": hit1, "hit3": hit3,
            "found": found, "mean_rank": (rank_sum / found) if found else None,
            "hist": hist}


CONDITIONS = [
    ("ideal", dict(drop=0.0, dual=False),
     "one fault, all alarms ring — consistency check (100 % expected by design)"),
    ("20 % dropped alarms", dict(drop=0.2, dual=False),
     "each cascade alarm is dropped with 20 % probability — effective root = earliest alarm that actually rang"),
    ("40 % dropped alarms", dict(drop=0.4, dual=False),
     "as above, 40 % — mirrors the recall gap in the PDF extraction"),
    ("double fault", dict(drop=0.0, dual=True),
     "two independent faults simultaneously — hit1: top candidate is one of the roots; hit3: BOTH roots in top 3"),
    ("double fault + 20 % drop", dict(drop=0.2, dual=True),
     "hardest condition"),
]


# How far apart the two independent faults start, in seconds. The sweep has
# to SPAN the cascade window to be informative: a cascade in this model runs
# 40-115 s, so two faults 20 s apart still overlap in time and no amount of
# timestamp reasoning can separate them — that is a fact about the incident,
# not a shortcoming of the method. 0 s is the control (the original harness's
# implicit assumption); a gain there would be an artefact, not a finding.
TIMING_OFFSETS = [0.0, 15.0, 30.0, 60.0, 120.0, 240.0]


def run_timing(g, by_tag, seeds, noises, max_faults, drop=0.0) -> list[dict]:
    """Paired experiment: does arrival time help separate two faults?

    Each offset is run TWICE over identical scenarios — same seeds, same
    faults, same dropped alarms — once ranking structurally only, once with
    the merged timeline available as a tiebreaker. Only the ranking input
    differs, so the delta is attributable.
    """
    rows = []
    for off in TIMING_OFFSETS:
        base = run(g, by_tag, seeds, noises, max_faults,
                   drop=drop, dual=True, offset=off, use_time=False)
        timed = run(g, by_tag, seeds, noises, max_faults,
                    drop=drop, dual=True, offset=off, use_time=True)
        n = base["scenarios"] or 1
        rows.append({
            "offset_s": off,
            "scenarios": base["scenarios"],
            "hit1_struct": round(100 * base["hit1"] / n, 1),
            "hit1_timed": round(100 * timed["hit1"] / n, 1),
            "hit3_struct": round(100 * base["hit3"] / n, 1),
            "hit3_timed": round(100 * timed["hit3"] / n, 1),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw", type=Path)
    ap.add_argument("--seeds", default=5, type=int)
    ap.add_argument("--noise", default=[0, 1, 2, 3], type=int, nargs="+")
    ap.add_argument("--max-faults", default=40, type=int)
    # type=str, not Path: Path("") is Path("."), which is truthy AND a
    # directory, so the documented `--out ''` skip crashed on write instead
    # of skipping.
    ap.add_argument("--out", default="reports/eval_root_cause.json", type=str,
                    help="Write the result here as JSON (read by the home page). Use --out '' to skip.")
    ap.add_argument("--timing", action="store_true",
                    help="Run the paired timing experiment (arrival time as "
                         "evidence on double faults) instead of the standard "
                         "conditions.")
    a = ap.parse_args()

    g, by_tag, label = load_or_synthetic(a.raw)
    print(f"\nRoot-cause eval  ({label})")
    print(f"  noise levels: {a.noise}   seeds/level: {a.seeds}   "
          f"max faults: {a.max_faults}\n")

    if a.timing:
        rows = run_timing(g, by_tag, a.seeds, a.noise, a.max_faults)
        print("  Does arrival time help separate two independent faults?")
        print("  Paired runs on identical scenarios; only the ranking input differs.\n")
        print(f"  {'fault gap':>10}{'n':>7}{'hit1 struct':>13}{'hit1 +tid':>11}"
              f"{'hit3 struct':>13}{'hit3 +tid':>11}")
        for r in rows:
            d1 = r["hit1_timed"] - r["hit1_struct"]
            d3 = r["hit3_timed"] - r["hit3_struct"]
            print(f"  {r['offset_s']:>8.1f} s{r['scenarios']:>7}"
                  f"{r['hit1_struct']:>12.1f}%{r['hit1_timed']:>10.1f}%"
                  f"{r['hit3_struct']:>12.1f}%{r['hit3_timed']:>10.1f}%"
                  f"   ({d1:+.1f}/{d3:+.1f})")
        print("\n  0 s is the control — simultaneous faults leave nothing for "
              "timing to exploit,\n  so a gain there would be an artefact, not a finding.\n")
        return

    rows = []
    for name, kw, desc in CONDITIONS:
        res = run(g, by_tag, a.seeds, a.noise, a.max_faults, **kw)
        n = res["scenarios"] or 1
        row = {"name": name, "desc": desc, "scenarios": res["scenarios"],
               "hit1_pct": round(100 * res["hit1"] / n, 1),
               "hit3_pct": round(100 * res["hit3"] / n, 1),
               "mean_rank": (round(res["mean_rank"], 2)
                             if res["mean_rank"] is not None else None),
               "not_candidate": res["scenarios"] - res["found"]}
        rows.append(row)
        print(f"  {name:24} hit1 {row['hit1_pct']:5.1f} %   "
              f"hit3 {row['hit3_pct']:5.1f} %   "
              f"mean rank {row['mean_rank'] if row['mean_rank'] is not None else '—'}"
              + (f"   (root not candidate: {row['not_candidate']})"
                 if row["not_candidate"] else ""))

    if a.out.strip():
        import json
        from datetime import date
        out_path = Path(a.out.strip())
        out = {"source": label, "date": str(date.today()),
               "seeds": a.seeds, "noise_levels": a.noise,
               "faults": rows[0]["scenarios"] // max(1, len(a.noise) * a.seeds),
               "conditions": rows}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        print(f"\n  written to {out_path} — displayed on the home page on next run")
    print()


if __name__ == "__main__":
    main()