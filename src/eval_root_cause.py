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
        drop: float = 0.0, dual: bool = False) -> dict:
    """One eval condition.

    drop  : probability each cascade alarm fails to ring. The scored root is
            the EFFECTIVE root — the earliest cascade alarm that actually
            rang (if the true root's own alarm is lost, no ranking can name
            it; the fair question is whether the earliest observable symptom
            tops the list).
    dual  : a second, independent fault fires simultaneously; both cascades
            ring. hit1 = the #1 candidate is one of the two true roots;
            hit3 = BOTH roots are in the top 3.
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
                        eff2 = next((t for t in c2
                                     if alarm_capable(by_tag.get(t))), None)
                        if eff2 and eff2 not in roots:
                            roots.append(eff2)
                if not roots:
                    continue
                briefs = candidate_brief(g, by_tag, alarms)
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
     "én feil, alle alarmer ringer — konsistenssjekk (100 % er forventet "
     "av konstruksjon)"),
    ("20 % tapte alarmer", dict(drop=0.2, dual=False),
     "hver kaskadealarm uteblir med 20 % sannsynlighet — effektiv rot "
     "= tidligste alarm som faktisk ringte"),
    ("40 % tapte alarmer", dict(drop=0.4, dual=False),
     "som over, 40 % — speiler recall-gapet i PDF-uttrekket"),
    ("dobbel feil", dict(drop=0.0, dual=True),
     "to uavhengige feil samtidig — hit1: toppkandidat er en av rotene; "
     "hit3: BEGGE røtter i topp 3"),
    ("dobbel feil + 20 % tap", dict(drop=0.2, dual=True),
     "hardeste betingelse"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw", type=Path)
    ap.add_argument("--seeds", default=5, type=int)
    ap.add_argument("--noise", default=[0, 1, 2, 3], type=int, nargs="+")
    ap.add_argument("--max-faults", default=40, type=int)
    ap.add_argument("--out", default="reports/eval_root_cause.json", type=Path,
                    help="Skriv resultatet hit som JSON (leses av hjem-siden). "
                         "Bruk --out '' for å hoppe over.")
    a = ap.parse_args()

    g, by_tag, label = load_or_synthetic(a.raw)
    print(f"\nRoot-cause eval  ({label})")
    print(f"  noise levels: {a.noise}   seeds/level: {a.seeds}   "
          f"max faults: {a.max_faults}\n")

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
              f"snittrang {row['mean_rank'] if row['mean_rank'] is not None else '—'}"
              + (f"   (rot ikke kandidat: {row['not_candidate']})"
                 if row["not_candidate"] else ""))

    if str(a.out):
        import json
        from datetime import date
        out = {"source": label, "date": str(date.today()),
               "seeds": a.seeds, "noise_levels": a.noise,
               "faults": rows[0]["scenarios"] // max(1, len(a.noise) * a.seeds),
               "conditions": rows}
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                         encoding="utf-8")
        print(f"\n  skrevet til {a.out} — vises på hjem-siden ved neste kjøring")
    print()


if __name__ == "__main__":
    main()