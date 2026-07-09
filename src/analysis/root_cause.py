"""
Alarm -> root-cause analysis.

Given a set of tags currently in alarm (a simulated 'alarm shower'), use the
dependency graph to separate CAUSE from CONSEQUENCE:

  - a ROOT CAUSE is an alarming tag with no other alarm upstream of it
    (nothing that could have caused it is also alarming);
  - a CONSEQUENCE is an alarming tag that lies downstream of a root.

This is exactly what an operator needs when twenty alarms fire at once: which
one is the origin, and which nineteen are just following from it.

Honest limits: it runs on the loop-based graph (real cross-loop propagation
needs traced connectivity), and it takes a SIMULATED alarm set - wiring it to
the live alarm/historian feed is the integration step that turns this into an
operations tool. It is decision support: it proposes a likely origin for an
engineer to confirm, it does not diagnose.
"""
from __future__ import annotations
import networkx as nx


def root_cause(graph: nx.DiGraph, active_alarms) -> dict:
    A = {a for a in active_alarms if a in graph}
    if not A:
        return {"active": [], "roots": [], "explains": {}, "classification": {}}

    # roots: alarming tags with nothing upstream also in alarm
    roots = [a for a in A if not (set(nx.ancestors(graph, a)) & A)]
    explains = {r: sorted((set(nx.descendants(graph, r)) & A) - {r}) for r in roots}
    roots = sorted(roots, key=lambda r: (-len(explains[r]), r))

    classification = {}
    for r in roots:
        classification[r] = "root cause"
        for c in explains[r]:
            classification.setdefault(c, f"consequence of {r}")
    # any alarm not reached from a root (shouldn't happen, but be safe)
    for a in sorted(A):
        classification.setdefault(a, "root cause")

    return {"active": sorted(A), "roots": roots,
            "explains": explains, "classification": classification}


def format_report(res: dict) -> str:
    if not res["active"]:
        return "No active alarms in the graph."
    lines = [f"ACTIVE ALARMS ({len(res['active'])}): {', '.join(res['active'])}", ""]
    if res["roots"]:
        primary = res["roots"][0]
        lines.append(f"PROBABLE ROOT CAUSE: {primary}"
                     + (f"  → explains {len(res['explains'][primary])} downstream alarm(s): "
                        f"{', '.join(res['explains'][primary])}"
                        if res['explains'][primary] else "  (isolated alarm)"))
        if len(res["roots"]) > 1:
            lines.append("OTHER INDEPENDENT ROOTS: "
                         + ", ".join(res["roots"][1:]))
    lines.append("")
    lines.append("CLASSIFICATION:")
    for a in res["active"]:
        lines.append(f"  {a:14} {res['classification'][a]}")
    lines.append("")
    lines.append("NOTE: Simulated alarms on the loop-based graph. Decision support — "
                 "proposes a likely origin for an engineer to confirm, not a diagnosis.")
    return "\n".join(lines)


if __name__ == "__main__":
    # demo: build an alarm shower on one loop of a system and disentangle it.
    #   python src/analysis/root_cause.py 27
    #   python src/analysis/root_cause.py 27 27-PT4803 27-PV4803   # explicit alarms
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from extraction.tag_extractor import extract_tags, create_objects
    from analysis.build_dependency_graph import build_graph
    from main import resolve_inputs

    system = sys.argv[1] if len(sys.argv) > 1 else "27"
    pid, scd, system = resolve_inputs(["x", system])
    objs = sorted(set(create_objects(extract_tags(pid), "P&ID"))
                  | set(create_objects(extract_tags(scd), "SCD")), key=lambda o: o.tag)
    g = build_graph(objs)

    if len(sys.argv) > 2:
        alarms = sys.argv[2:]
    else:
        # auto-pick a loop that has a full input->...->downstream chain
        alarms = []
        for n in g.nodes:
            down = list(nx.descendants(g, n))
            if len(down) >= 2 and not list(nx.ancestors(g, n)):
                alarms = [n] + down
                break
        print(f"(simulated alarm shower on loop of {alarms[0] if alarms else '—'})\n")

    print(format_report(root_cause(g, alarms)))