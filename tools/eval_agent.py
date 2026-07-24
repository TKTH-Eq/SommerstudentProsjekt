"""Evaluate the control-room agent against a set of HARD synthetic
scenarios — the test rig behind the pilot argument ("the agent pointed
right in N of M scenarios, X s before the operator could have").

Replays each scenario second by second through the SAME engine the app
uses (candidate_brief, agent_watch_events, trend_watch_events,
chatter_events, structure_time_verdict) and scores:

  hit           top candidate at completion == true root (or its first
                alarming symptom when the root is silent)
  t_correct     first time the leading hypothesis became — and stayed —
                correct (s after first alarm; lower is better)
  warn/premat   early warnings issued / issued >3 s before the true
                drift onset (false-positive proxy under noise)
  events        watch-event icons that fired

Scenario axes: clean single cascade · noisy trends (level 1.5) · harsh
noise (2.5) · noise alarm FIRST (first-up trap) · double independent
fault · slow drift. Deterministic; runs headless anywhere:

    python tools/eval_agent.py
    python tools/eval_agent.py --noise 2.0 --json results.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import networkx as nx  # noqa: E402


def _model():
    """Self-contained two-train mini flowsheet + noise pool (18 tags)."""
    from analysis.alarm_priority import alarm_semantics

    class Obj:
        def __init__(self, tag, category="input"):
            self.tag, self.category = tag, category
            self.type_code = tag.split("-")[1][:3].rstrip("0123456789")
            sem = alarm_semantics(self.type_code)
            self.priority = sem.get("priority", 3)
            self.alarm_direction = sem.get("direction")
            self.loop = tag.split("-")[1]

    chain_a = ["13-PT101", "13-PIC101", "13-PSH101", "13-FT102", "13-LT103"]
    chain_b = ["27-PT301", "27-TT302", "27-PSL303", "27-FT304"]
    noise = ["71-LT710", "45-FT450", "82-TT820", "20-PT205", "66-LT660"]
    by_tag = {t: Obj(t, "logic" if "IC" in t else "input")
              for t in chain_a + chain_b + noise}
    g = nx.DiGraph()
    g.add_nodes_from(by_tag)
    for c in (chain_a, chain_b):
        for a, b in zip(c, c[1:]):
            g.add_edge(a, b)
    return g, by_tag, chain_a[0], chain_b[0]


def _shift(timeline: dict, tags, dt: float) -> dict:
    out = dict(timeline)
    for t in tags:
        out[t] = round(out[t] + dt, 2)
    base = min(out.values())
    return {t: round(v - base, 2) for t, v in out.items()}


def build_scenarios(noise_override: float | None = None):
    from analysis.control_room import alarm_shower
    g, by_tag, root_a, root_b = _model()
    seed = 7
    sc = []

    def mk(name, fault, truth, timeline, noise_tags, level, note=""):
        sc.append({"name": name, "fault": fault, "truth": set(truth),
                   "timeline": timeline, "noise": noise_tags,
                   "level": (noise_override if noise_override is not None
                             else level), "note": note})

    s1 = alarm_shower(g, root_a, noise=2, seed=seed, by_tag=by_tag, step=2.5)
    mk("single_clean", root_a, [root_a], s1["timeline"], s1["noise"], 0.0)
    mk("single_noisy", root_a, [root_a], s1["timeline"], s1["noise"], 1.5)
    mk("single_harsh", root_a, [root_a], s1["timeline"], s1["noise"], 2.5)

    # first-up trap: a noise alarm rings BEFORE the cascade root
    if s1["noise"]:
        tl = _shift(s1["timeline"], [t for t in s1["timeline"]
                                     if t not in s1["noise"]], +2.0)
        tl[s1["noise"][0]] = 0.0
        mk("noise_first", root_a, [root_a], tl, s1["noise"], 1.0,
           "first-up is noise")

    # double independent fault: train B starts 4 s after train A
    s2 = alarm_shower(g, root_b, noise=0, seed=seed, by_tag=by_tag, step=2.5)
    tl = dict(s1["timeline"])
    for t, v in s2["timeline"].items():
        tl[t] = round(v + 4.0, 2)
    mk("double_fault", root_a, [root_a, root_b], tl, s1["noise"], 1.0,
       "two roots must both surface as candidates")

    # slow drift: same cascade over a much longer window
    s3 = alarm_shower(g, root_a, noise=2, seed=seed, by_tag=by_tag, step=6.0)
    mk("slow_drift", root_a, [root_a], s3["timeline"], s3["noise"], 1.0)
    return g, by_tag, sc


def run_one(g, by_tag, sc, tick: float = 0.5) -> dict:
    from analysis.control_room import (agent_watch_events, candidate_brief,
                                       chatter_events, structure_time_verdict,
                                       synthetic_chatter, synthetic_trends,
                                       trend_watch_events)
    tl = sc["timeline"]
    window = max(tl.values())
    order = sorted(tl, key=tl.get)
    trends = synthetic_trends(tl, window, by_tag, seed=sc["name"],
                              noise_level=sc["level"])
    chatter = synthetic_chatter(sc["noise"], tl, window, seed=sc["name"])
    aw = tw = ch = None
    log, warns = [], []
    leader_ok_from = None
    el = 0.0
    briefs = []
    while el <= window + 1.0:
        active = [t for t in order if tl[t] <= el] or order[:1]
        briefs = candidate_brief(g, by_tag, active)
        aw, e1 = agent_watch_events(aw, active, briefs, by_tag, tl, window,
                                    order[0])
        tw, e2 = trend_watch_events(tw, trends, tl, el)
        ch, e3 = chatter_events(ch, chatter, el)
        log += e1 + e2 + e3
        warns += [(el, e) for e in e2]
        leader = briefs[0]["tag"] if briefs else None
        if leader in sc["truth"]:
            if leader_ok_from is None:
                leader_ok_from = el
        else:
            leader_ok_from = None
        el = round(el + tick, 2)
    log += structure_time_verdict(briefs, trends, tl)

    cand_tags = {b["tag"] for b in briefs}
    hit = (briefs[0]["tag"] in sc["truth"]) if briefs else False
    both = sc["truth"] <= cand_tags
    premature = 0
    for w_el, e in warns:
        tag = e["text"].split("**")[1]
        onset = tl[tag] - trends["lead"].get(tag, 8.0)
        if w_el < onset - 3.0:
            premature += 1
    return {"name": sc["name"], "level": sc["level"], "note": sc["note"],
            "alarms": len(tl), "hit": hit, "all_roots_found": both,
            "t_correct": leader_ok_from, "leader": briefs[0]["tag"]
            if briefs else None, "warnings": len(warns),
            "premature": premature,
            "events": "".join(sorted({e["icon"] for e in log}))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--noise", type=float, default=None,
                    help="override noise level for ALL scenarios")
    ap.add_argument("--json", default=None, help="write results to file")
    a = ap.parse_args()
    g, by_tag, scenarios = build_scenarios(a.noise)
    rows = [run_one(g, by_tag, sc) for sc in scenarios]
    hdr = f"{'scenario':<14}{'lvl':>4}{'alm':>4}{'hit':>4}{'roots':>6}" \
          f"{'t_ok':>6}{'warn':>5}{'prem':>5}  events / note"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['name']:<14}{r['level']:>4.1f}{r['alarms']:>4}"
              f"{'  ✓' if r['hit'] else '  ✗'}"
              f"{'    ✓' if r['all_roots_found'] else '    ✗'}"
              f"{(f'{r0:.1f}' if (r0 := r['t_correct']) is not None else '—'):>6}"
              f"{r['warnings']:>5}{r['premature']:>5}  "
              f"{r['events']}  {r['note']}")
    n_hit = sum(r["hit"] for r in rows)
    print(f"\nsummary: {n_hit}/{len(rows)} correct leading hypothesis at "
          f"completion; {sum(r['premature'] for r in rows)} premature "
          f"warnings across the set")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"wrote {a.json}")


if __name__ == "__main__":
    main()