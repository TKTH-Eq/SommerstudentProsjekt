"""
Control-room decision support: given active alarms and the dependency
graph, propose (1) the probable root cause, (2) what to CROSS-CHECK before
acting, and (3) which barriers/actions are relevant — every suggestion
referencing real extracted tags only.

Design position (matches the rest of the project): this is decision
SUPPORT, not decision making. The assistant triages an alarm shower into
"look here first, verify with these, these are your handles" — the
operator confirms against the drawing and procedures. The graph gives
structural reachability, not process consequence: redundancy, bypasses and
operating mode are not in the model, and the advice says so.

Pure functions over (graph, objects) so the module is unit-testable
headless and works identically on the loop-based PDF graph and the stated
DEXPI topology — though the advice is only as good as the connectivity,
which is the recurring point.
"""
from __future__ import annotations

import networkx as nx

from config import SAFETY_TYPES
from analysis.root_cause import root_cause


def scenario_order(graph: nx.DiGraph, fault: str) -> list[str]:
    """The alarm cascade a fault at `fault` would produce, in BFS order —
    the 'hidden truth' the training scenario plays back step by step."""
    return [fault] + [n for n in nx.bfs_tree(graph, fault) if n != fault]


def cross_checks(graph: nx.DiGraph, by_tag, candidate: str) -> dict:
    """What an operator should verify BEFORE trusting/acting on `candidate`
    as the root: redundant loop-mates (does the B-instrument agree?),
    upstream sensors (is the disturbance real and coming from there?), and
    immediate downstream readings (is it propagating as expected?)."""
    o = by_tag.get(candidate)
    loop_mates = sorted(t for t, x in by_tag.items()
                        if o and x.loop == o.loop and t != candidate
                        and x.category == "input")
    upstream = sorted(t for t in graph.predecessors(candidate)
                      if by_tag.get(t) and by_tag[t].category == "input") \
        if candidate in graph else []
    downstream = sorted(list(graph.successors(candidate)))[:6] \
        if candidate in graph else []
    return {"loop_mates": loop_mates, "upstream_sensors": upstream,
            "downstream_next": downstream}


def relevant_barriers(graph: nx.DiGraph, by_tag, candidate: str) -> list[str]:
    """Safety-typed tags in the candidate's loop or downstream — the
    operator's structural 'handles' (which barriers guard this path)."""
    o = by_tag.get(candidate)
    pool = {t for t, x in by_tag.items() if o and x.loop == o.loop}
    if candidate in graph:
        pool |= set(nx.descendants(graph, candidate))
    return sorted(t for t in pool
                  if by_tag.get(t) and by_tag[t].type_code in SAFETY_TYPES)


def assist(graph: nx.DiGraph, by_tag, active: list[str]) -> dict:
    """One advisory snapshot for the current alarm picture."""
    res = root_cause(graph, active)
    primary = res["roots"][0] if res["roots"] else None
    out = {"root_cause": res, "primary": primary,
           "checks": None, "barriers": None, "advice": []}
    if primary:
        out["checks"] = cross_checks(graph, by_tag, primary)
        out["barriers"] = relevant_barriers(graph, by_tag, primary)
        ch = out["checks"]
        if ch["loop_mates"]:
            out["advice"].append(
                f"Kryssjekk redundante målinger i samme løkke før aksjon: "
                f"{', '.join(ch['loop_mates'])} — er avviket reelt?")
        if ch["upstream_sensors"]:
            out["advice"].append(
                f"Verifiser oppstrøms: {', '.join(ch['upstream_sensors'])} — "
                f"kommer forstyrrelsen derfra, er {primary} et symptom, "
                f"ikke årsaken.")
        if out["barriers"]:
            out["advice"].append(
                f"Relevante barrierer i kjeden: {', '.join(out['barriers'])} — "
                f"bekreft status/tilgjengelighet.")
        out["advice"].append(
            "Grafen viser strukturell nåbarhet, ikke prosesskonsekvens — "
            "bekreft mot tegning, redundans og driftsmodus før inngrep.")
    return out


def alarm_capable(obj) -> bool:
    """Can this component actually raise an alarm in the SAS?

    Only measuring/logic functions and safety functions alarm (a PT via
    PAH/PALL, an LSHH, a controller deviation) — a hand valve, an orifice
    or a heat exchanger has no alarm of its own. Structural exposure and
    alarm generation are different things, and the shower must show the
    second while the debrief can still report the first."""
    if obj is None:
        return False
    return obj.category in ("input", "logic") or obj.type_code in SAFETY_TYPES


def alarm_shower(graph: nx.DiGraph, fault: str, noise: int = 2,
                 seed: int | None = None, by_tag=None) -> dict:
    """A realistic incident picture: the fault's whole cascade fires AT ONCE,
    mixed (shuffled) with a couple of unrelated 'noise' alarms — chatter from
    elsewhere in the plant, independent of the fault. The operator's task is
    to separate root from symptom from noise, which is exactly what a real
    alarm flood demands.

    If by_tag is given, the alarm BOARD is filtered to alarm-capable
    components only (see alarm_capable) — everything downstream is still
    reported as 'exposed', but a hand valve does not ring."""
    import random as _r
    rng = _r.Random(seed)
    cascade = scenario_order(graph, fault)
    if by_tag is not None:
        board = [t for t in cascade if alarm_capable(by_tag.get(t))]
    else:
        board = list(cascade)
    related = set(cascade) | set(nx.ancestors(graph, fault))
    pool = [n for n in graph.nodes if n not in related
            and (by_tag is None or alarm_capable(by_tag.get(n)))]
    noise_tags = rng.sample(pool, min(noise, len(pool))) if pool else []
    alarms = board + noise_tags
    rng.shuffle(alarms)
    return {"alarms": alarms, "cascade": cascade, "noise": noise_tags,
            "exposed": len(cascade)}


def candidate_brief(graph: nx.DiGraph, by_tag, active: list[str]) -> list[dict]:
    """Evidence per candidate root — deliberately WITHOUT declaring a winner.

    Cycle-aware: the plant model adds cross-drawing edges in BOTH directions
    (direction across a sheet boundary is not stated in the export), which
    creates cycles — and inside a cycle every alarm has an active
    predecessor, so the naive "no active upstream" root test finds nothing.
    Instead we condense the active-alarm subgraph into strongly connected
    components and take the SOURCE components as candidate groups; within a
    group the representative shown is the member that would explain most of
    the other active alarms. On a cycle-free graph (single-drawing mode)
    every SCC is a single node and this reduces exactly to the old test.
    """
    act = [a for a in active if a in graph]
    sub = graph.subgraph(act)
    cond = nx.condensation(sub)
    out = []
    for c in cond.nodes:
        if cond.in_degree(c) != 0:
            continue                       # not a source component
        members = cond.nodes[c]["members"]
        # explains = active alarms reachable in the FULL graph
        def _explains(t):
            return sorted(set(nx.descendants(graph, t)) & set(act) - {t})
        rep = max(members, key=lambda t: len(_explains(t)))
        exp = _explains(rep)
        entry = {
            "tag": rep,
            "explains": exp,
            "checks": cross_checks(graph, by_tag, rep),
            "barriers": relevant_barriers(graph, by_tag, rep),
        }
        if len(members) > 1:
            entry["group"] = sorted(m for m in members if m != rep)
        out.append(entry)
    return sorted(out, key=lambda b: b["tag"])


def audit_answer_tags(text: str, by_tag) -> dict:
    """Verify every tag-like token in an AI answer against the register —
    the same 'LLM proposes, register verifies' pattern as the vision layer,
    applied to chat. Returns {'verified': [...], 'suspect': [...]} where
    verified covers exact matches and (type, number)-normalised matches
    (HV 2264 ≡ 13-HV2264 ≡ 13-2264HV). Pure function, unit-testable."""
    import re as _re
    known = {t.upper() for t in by_tag}

    def _pair(t: str):
        u = _re.sub(r"\s+", "", t.upper())
        u = u.split("-", 1)[1] if _re.match(r"^\d{2}-", u) else u
        u = u.replace("-", "")
        m = _re.match(r"^([A-Z]{1,4})(\d{2,4})[A-Z]?$", u)
        if m:
            return m.group(1), m.group(2)
        m = _re.match(r"^(\d{2,4})([A-Z]{1,4})$", u)
        return (m.group(2), m.group(1)) if m else None

    known_pairs = {p for t in known if (p := _pair(t))}
    tokens = set(_re.findall(
        r"\b\d{2}-[A-Z]{1,4}-?\d{2,4}[A-Z]?\b|\b\d{2}-\d{3,4}[A-Z]{1,4}\b"
        r"|\b[A-Z]{2,4}[ -]\d{3,4}[A-Z]?\b", text))
    verified, suspect = [], []
    for tok in sorted(tokens):
        u = _re.sub(r"\s+", "", tok.upper())
        if u in known or (_pair(tok) and _pair(tok) in known_pairs):
            verified.append(tok)
        else:
            suspect.append(tok)
    return {"verified": verified, "suspect": suspect}


def shower_debrief(fault: str, chosen: str | None, noise: list[str],
                   n_active: int) -> list[str]:
    lines = [f"Faktisk feilkilde: {fault}."]
    if chosen == fault:
        lines.append("Riktig — du identifiserte kilden i alarmdusjen.")
    elif chosen in noise:
        lines.append(f"{chosen} var en STØYALARM uten kobling til hendelsen — "
                     f"i en ekte dusj er nettopp urelatert skravling den "
                     f"vanligste fellen.")
    elif chosen is not None:
        lines.append(f"{chosen} var et nedstrøms SYMPTOM av {fault} — "
                     f"strukturbeviset å se etter: kilden forklarer flest av "
                     f"de andre alarmene, symptomet forklarer få.")
    if noise:
        lines.append(f"Støyalarmer i bildet: {', '.join(noise)} — uavhengige "
                     f"av hendelsen.")
    lines.append(f"Totalt {n_active} samtidige alarmer. Treningsscenario på "
                 f"syntetiske data — assistentens brief var strukturell, "
                 f"vurderingen var din.")
    return lines


def debrief(fault: str, isolated: str | None, alarms_seen: int,
            total_cascade: int) -> list[str]:
    """Post-scenario feedback: did the operator isolate the true origin,
    and how early?"""
    lines = [f"Faktisk feilkilde i scenariet: {fault}."]
    if isolated is None:
        lines.append("Ingen isolasjon ble utført — kaskaden løp "
                     f"{alarms_seen} av {total_cascade} mulige alarmer.")
    elif isolated == fault:
        lines.append(f"Riktig komponent isolert ({isolated}) etter "
                     f"{alarms_seen} alarm(er) — kaskaden stoppet ved kilden.")
    else:
        lines.append(f"Isolerte {isolated}, men kilden var {fault} — "
                     f"nedstrøms isolasjon stopper symptomer, ikke årsaken.")
    lines.append("Treningsscenario på syntetiske data — assistentens forslag "
                 "var strukturelle, operatørens dømmekraft avgjorde.")
    return lines