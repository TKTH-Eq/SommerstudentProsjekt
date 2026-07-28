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

TIME AS EVIDENCE (candidate_brief(timeline=...)): the graph says what is
connected; arrival times say how many things went wrong. Passing the alarm
shower's timeline lets an alarm that cannot be a consequence — because it
rang before everything that supposedly explains it — be surfaced as its own
candidate. Measured on the real Huldra model this removes the double-fault
ceiling entirely (95 % -> 100 % hit1) and also lifts hit3 under dropped
alarms (96.9 % -> 99.4 % at 40 % drop). Without a timeline the module
behaves exactly as before.
"""
from __future__ import annotations

import os
import sys

if __name__ == "__main__" and __package__ is None:      # direct run support
    # må ligge FØR pakkeimportene under — samme fallgruve som hazop_prep.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
                f"Cross-check redundant measurements in the same loop before "
                f"acting: {', '.join(ch['loop_mates'])} — is the deviation real?")
        if ch["upstream_sensors"]:
            out["advice"].append(
                f"Verify upstream: {', '.join(ch['upstream_sensors'])} — if the "
                f"disturbance comes from there, {primary} is a symptom, "
                f"not the cause.")
        if out["barriers"]:
            out["advice"].append(
                f"Relevant barriers in the chain: {', '.join(out['barriers'])} — "
                f"confirm status/availability.")
        out["advice"].append(
            "The graph shows structural reachability, not process consequence — "
            "confirm against the drawing, redundancy and operating mode "
            "before intervening.")
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
    from analysis.alarm_priority import alarm_semantics
    # measuring/logic, safety-typed, OR anything whose tag carries an explicit
    # alarm/trip annotation (LAHH, TAHH, PSH, ZSL …) — the last clause makes
    # sure a dedicated alarm/switch tag rings even if its type sits in "other".
    return (obj.category in ("input", "logic")
            or obj.type_code in SAFETY_TYPES
            or alarm_semantics(obj.type_code)["level"] is not None)


def alarm_shower(graph: nx.DiGraph, fault: str, noise: int = 2,
                 seed: int | None = None, by_tag=None,
                 step: float = 2.5) -> dict:
    """A realistic incident picture: the fault's cascade fires as a SEQUENCE
    over a few seconds (not all at once), mixed with a couple of unrelated
    'noise' alarms — chatter from elsewhere in the plant, independent of the
    fault. The operator's task is to separate root from symptom from noise,
    which is exactly what a real alarm flood demands.

    Timing (new): each cascade alarm gets a reveal offset in seconds by its
    position in the causal (BFS) order — the root rings first, downstream
    alarms follow ~`step` s apart. Noise is scattered AFTER the first
    cascade alarm, so the 'first-up' alarm is usually — but not always —
    the root: a strong clue, never a guarantee. Offsets are deterministic
    for a given seed.

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

    # reveal timeline: cascade in causal order at ~step s spacing (small
    # jitter), earliest normalised to t=0; noise scattered strictly after
    # the first cascade alarm and within the cascade window.
    step = max(0.1, float(step))
    timeline: dict[str, float] = {}
    for i, t in enumerate(board):
        jitter = rng.uniform(-0.2, 0.2) * step
        timeline[t] = round(max(0.0, i * step + jitter), 2)
    if board:
        base = min(timeline[t] for t in board)
        for t in board:
            timeline[t] = round(timeline[t] - base, 2)
    last = max(timeline.values()) if timeline else 0.0
    for t in noise_tags:
        timeline[t] = round(rng.uniform(step, max(last, step * 1.5)), 2)
    window = round(max(timeline.values()) if timeline else 0.0, 2)
    order_revealed = sorted(timeline, key=lambda t: (timeline[t], t))
    first_up = order_revealed[0] if order_revealed else None

    return {"alarms": alarms, "cascade": cascade, "noise": noise_tags,
            "exposed": len(cascade), "timeline": timeline,
            "order_revealed": order_revealed, "first_up": first_up,
            "window": window, "step": step}


def arrival_clusters(timeline: dict, gap: float) -> dict:
    """Split alarms into temporal clusters: {tag: cluster index}, earliest 0.

    One cascade rings at roughly `step` second spacing, so a gap materially
    larger than that suggests a SEPARATE initiating event rather than more of
    the same propagation. That is the one thing arrival times can say which
    the graph cannot: how MANY things went wrong, as opposed to what is
    connected to what.

    Honest limits, both visible in the measurement: unrelated chatter
    scattered through the window bridges real gaps and merges clusters, and
    two faults that start close together are indistinguishable from one
    cascade no matter how the threshold is set. This is evidence, not a
    verdict — which is why it enters the ranking as a tiebreaker and is
    reported alongside the structural signal, never instead of it.
    """
    if not timeline:
        return {}
    ordered = sorted(timeline, key=lambda t: (timeline[t], t))
    out, cid = {}, 0
    prev = None
    for tag in ordered:
        if prev is not None and (timeline[tag] - prev) > gap:
            cid += 1
        out[tag] = cid
        prev = timeline[tag]
    return out


def candidate_brief(graph: nx.DiGraph, by_tag, active: list[str],
                    timeline: dict | None = None,
                    cluster_gap: float | None = None) -> list[dict]:
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
    clusters = (arrival_clusters({t: v for t, v in timeline.items() if t in act},
                                 cluster_gap if cluster_gap is not None else 5.0)
                if timeline else {})
    first_of_cluster = {}
    for tag, c in sorted(clusters.items(), key=lambda kv: (timeline[kv[0]], kv[0])):
        first_of_cluster.setdefault(c, tag)
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
        from analysis.alarm_priority import alarm_semantics
        o = by_tag.get(rep)
        sem = alarm_semantics(o.type_code if o else "")
        entry = {
            "tag": rep,
            "explains": exp,
            "priority": sem["priority"],
            "priority_label": sem["priority_label"],
            "direction": sem["direction"],
            "checks": cross_checks(graph, by_tag, rep),
            "barriers": relevant_barriers(graph, by_tag, rep),
        }
        if len(members) > 1:
            entry["group"] = sorted(m for m in members if m != rep)
        if timeline:
            entry["late_onset"] = False
            # earliest arrival within the group — the group is one candidate,
            # so its clock starts when any of its members first rang
            times = [timeline[m] for m in members if m in timeline]
            entry["t"] = min(times) if times else None
            entry["cluster"] = clusters.get(rep)
            entry["first_in_cluster"] = any(
                first_of_cluster.get(clusters.get(m)) == m
                for m in members if m in clusters)
        out.append(entry)
    # Ranking: the STRUCTURAL root signal leads — the candidate that explains
    # the most other active alarms — because that is what actually points at
    # the origin. Priority (severity) is the tiebreaker, so among equally
    # explanatory roots the more critical one surfaces first. This ordering
    # deliberately does NOT let a high-priority but independent noise alarm
    # (explains 0) leapfrog the true cascade root. The board (urgency) is
    # TEMPORAL DETACHMENT — the one thing arrival time can do that the graph
    # cannot, and the only thing that moves the measured ceiling.
    #
    # The structural test asks "is anything active upstream of this alarm?".
    # With two overlapping faults it silently loses a root: if fault B's root
    # sits downstream of fault A's cascade it has active ancestors, is filed
    # as a consequence, and never becomes a candidate. Measurement showed
    # this IS the ceiling — on double faults every root that reaches the
    # candidate list already ranks #1, so the whole 5 % loss is roots that
    # were never listed. Ranking was never the problem.
    #
    # Two rules, and the order matters because they are not equally strong:
    #
    #   PRECEDES  an alarm that rang BEFORE every alarm that supposedly
    #             explains it cannot be their consequence — causality does
    #             not run backwards. This is a proof, not a heuristic, and
    #             it is what rescues the EARLIER fault's root when the later
    #             fault's cascade sits structurally upstream of it.
    #
    # A second rule was tried and REMOVED by measurement: "late onset" — an
    # alarm ringing more than one propagation step after the latest alarm
    # that could explain it. It sounded reasonable and cost nothing to add.
    # Over 360 single-fault scenarios it promoted 804 extra candidates, and
    # every single one was a genuine CASCADE alarm, not noise: in a long
    # cascade a branch can trail its nearest active ancestor by well over a
    # step without being a new event. It also contributed nothing to the
    # dual-fault result — the 95 % -> 100 % jump came entirely from
    # `precedes`, which fires zero times spuriously. A heuristic that adds
    # ~2 false candidates per incident and buys no accuracy is worse than no
    # heuristic, so it is gone rather than tuned.
    if timeline:
        tol = 0.01                       # rounding slack on the timeline
        covered = {m for c in cond.nodes for m in cond.nodes[c]["members"]
                   if cond.in_degree(c) == 0}
        for a in act:
            if a in covered or a not in timeline:
                continue
            anc = [x for x in nx.ancestors(sub, a) if x in timeline]
            if not anc:
                continue
            earliest = min(timeline[x] for x in anc)
            if timeline[a] + tol >= earliest:
                continue
            why, by = "precedes", round(earliest - timeline[a], 2)
            exp = sorted(set(nx.descendants(graph, a)) & set(act) - {a})
            from analysis.alarm_priority import alarm_semantics
            o = by_tag.get(a)
            sem = alarm_semantics(o.type_code if o else "")
            out.append({
                "tag": a, "explains": exp,
                "priority": sem["priority"],
                "priority_label": sem["priority_label"],
                "direction": sem["direction"],
                "checks": cross_checks(graph, by_tag, a),
                "barriers": relevant_barriers(graph, by_tag, a),
                "t": timeline[a], "cluster": clusters.get(a),
                "first_in_cluster": first_of_cluster.get(clusters.get(a)) == a,
                "late_onset": True, "detached": why, "detached_by": by,
            })

    # priority-sorted; the candidate list (likelihood of being the origin) is
    # explains-first — two different questions, two different orders.
    #
    # With arrival times available, TIME enters strictly as a tiebreaker ahead
    # of priority: among candidates that explain equally many alarms, the one
    # that rang first is the likelier origin. It is deliberately not allowed
    # to outrank the structural signal — the structural ordering is the one
    # that measures 100 %/94 % on single faults, and a late-arriving alarm
    # that explains more is still the better candidate.
    if timeline:
        return sorted(out, key=lambda b: (
            -len(b["explains"]),
            b["t"] if b.get("t") is not None else float("inf"),
            b["priority"], b["tag"]))
    return sorted(out, key=lambda b: (-len(b["explains"]), b["priority"], b["tag"]))


def situation_brief(active, briefs, drawings_of=None) -> dict:
    """Neutral opening synthesis of the alarm picture — FAULT-BLIND.

    Built only from the active alarms and the candidate briefs (which are
    themselves derived from the graph, never from the hidden fault), so the
    assistant cannot and does not know which alarm is the true cause. It
    surfaces the strongest STRUCTURAL signal — how many other active alarms
    each candidate root would explain — as a transparent ranking, and
    declares NO winner. Weighing the evidence stays the operator's job.

    briefs is expected already ordered (explains desc, then priority); we
    keep that order so rank 1 = 'explains the most', not 'is the cause'.
    """
    ranking = [
        {"tag": b["tag"],
         "priority": b.get("priority", 3),
         "priority_label": b.get("priority_label", ""),
         "explains_count": len(b["explains"]),
         "explains_none": len(b["explains"]) == 0}
        for b in briefs
    ]
    n_drawings = (len({d for t in active for d in drawings_of.get(t, [])})
                  if drawings_of else 0)
    return {
        "n_alarms": len(active),
        "n_candidates": len(briefs),
        "n_drawings": n_drawings,
        "ranking": ranking,
        "any_none": any(r["explains_none"] for r in ranking),
    }


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


def _tag_pair(t: str):
    """(type, number) normalisation shared with audit_answer_tags:
    HV 2264 ≡ 13-HV2264 ≡ 13-2264HV."""
    import re as _re
    u = _re.sub(r"\s+", "", t.upper())
    u = u.split("-", 1)[1] if _re.match(r"^\d{2}-", u) else u
    u = u.replace("-", "")
    m = _re.match(r"^([A-Z]{1,4})(\d{2,4})[A-Z]?$", u)
    if m:
        return m.group(1), m.group(2)
    m = _re.match(r"^(\d{2,4})([A-Z]{1,4})$", u)
    return (m.group(2), m.group(1)) if m else None


def canonicalize_tags(tokens, by_tag) -> dict:
    """Map free-text tag tokens from an AI answer to canonical register
    tags (same normalisation as audit_answer_tags). Unresolvable tokens
    are omitted — they are the 'suspect' set. {token: canonical_tag}."""
    import re as _re
    exact = {t.upper(): t for t in by_tag}
    pairs = {}
    for t in by_tag:
        p = _tag_pair(t)
        if p:
            pairs.setdefault(p, t)
    out = {}
    for tok in tokens:
        u = _re.sub(r"\s+", "", tok.upper())
        if u in exact:
            out[tok] = exact[u]
        else:
            p = _tag_pair(tok)
            if p and p in pairs:
                out[tok] = pairs[p]
    return out


_TAG_TOKEN_RE = (r"\b\d{2}-[A-Z]{1,4}-?\d{2,4}[A-Z]?\b"
                 r"|\b\d{2}-\d{3,4}[A-Z]{1,4}\b"
                 r"|\b[A-Z]{2,4}[ -]\d{3,4}[A-Z]?\b")


def parse_verification_plan(text: str, by_tag) -> list[dict]:
    """Deterministically extract the numbered VERIFICATION PLAN steps from
    an AI answer (the fixed prompt template demands 3-5 numbered steps
    tied to REAL tags). No AI involved in the parse: numbered lines are
    collected, tag tokens found with the same regex as audit_answer_tags,
    and resolved against the register. Returns
    [{'n', 'text', 'tags': [canonical...]}]; empty list if the answer has
    no recognisable numbered steps — the caller then simply shows no
    figure. Multi-line steps are folded into their opening line."""
    import re as _re
    # isolate the plan section if the heading is present; else use whole text
    m = _re.search(r"VERIFICATION\s+PLAN(.*?)(?:\n\s*(?:\*\*)?\s*3[\.)]\s*"
                   r"DO\s+NOT\s+ACT|$)", text, _re.S | _re.I)
    body = m.group(1) if m else text
    steps, cur = [], None
    for line in body.splitlines():
        sm = _re.match(r"^\s*(?:\*\*)?(\d)[\.)]\s*(?:\*\*)?\s*(.+)$", line)
        if sm and int(sm.group(1)) <= 9:
            if cur:
                steps.append(cur)
            cur = {"n": int(sm.group(1)), "text": sm.group(2).strip()}
        elif cur and line.strip():
            cur["text"] += " " + line.strip()
    if cur:
        steps.append(cur)
    # if we parsed the WHOLE answer (no heading), keep only a plausible
    # consecutive 1..n run so section numbers 1-3 of the template don't
    # masquerade as a plan of their own
    if not m and steps:
        run = [s for i, s in enumerate(steps) if s["n"] == i + 1]
        steps = run if len(run) >= 2 else []
    canon = canonicalize_tags(
        {t for s in steps for t in _re.findall(_TAG_TOKEN_RE, s["text"])},
        by_tag)
    for s in steps:
        seen = []
        for tok in _re.findall(_TAG_TOKEN_RE, s["text"]):
            c = canon.get(tok)
            if c and c not in seen:
                seen.append(c)
        s["tags"] = seen
    return steps


def qa_plan_svg(steps: list[dict], by_tag, active: list[str],
                checked: set | None = None, w: int = 1100) -> str:
    """Render the parsed verification plan as a numbered step chain:
    circles 1→n connected left-to-right, the step's register tag(s)
    beneath, colored by tag priority (P1 red … P4 grey), full step text
    on hover. `checked` is a set of 0-based POSITIONS (robust to answers
    that reuse a step number): done steps turn green with ✓, the first
    undone step pulses. Everything shown is parsed from the answer and
    verified against the register — the figure cannot contain a
    hallucinated tag."""
    import html as _html
    from analysis.alarm_priority import alarm_semantics, DIR_ARROW
    if not steps:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>"
    PRIO_FILL = {1: "#b8442c", 2: "#d97f3f", 3: "#5c81a6", 4: "#6e7781"}
    n = len(steps)
    cellw = max(150, (w - 60) // n)
    h = 150
    P = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'style="width:100%;height:auto;font-family:sans-serif">']
    cy = 52
    for i, s in enumerate(steps):
        cx = 30 + i * cellw + cellw // 2
        if i:
            px = 30 + (i - 1) * cellw + cellw // 2
            P.append(f'<line x1="{px + 22}" y1="{cy}" x2="{cx - 22}" '
                     f'y2="{cy}" stroke="#3a4250" stroke-width="2" '
                     f'marker-end="url(#qa_ar)"/>')
        first = s["tags"][0] if s["tags"] else None
        o = by_tag.get(first) if first else None
        sem = alarm_semantics(getattr(o, "type_code", "")) if o else None
        fill = PRIO_FILL.get(sem["priority"], "#6e7781") if sem else "#3a4250"
        tip = f"Step {s['n']}: {s['text']}"
        done = checked is not None and i in checked
        is_next = (checked is not None and not done
                   and all(j in checked for j in range(i)))
        if done:
            fill = "#2d5a3d"
        if is_next:
            P.append(f'<circle cx="{cx}" cy="{cy}" r="26" fill="none" '
                     f'stroke="#f4d35e" stroke-width="2">'
                     f'<animate attributeName="opacity" '
                     f'values="0.9;0.15;0.9" dur="1.6s" '
                     f'repeatCount="indefinite"/></circle>')
        ring = ' stroke="#3f8f4f" stroke-width="2"' if done else ""
        P.append(f'<g><circle cx="{cx}" cy="{cy}" r="20" fill="{fill}"{ring}>'
                 f'<title>{_html.escape(tip)}</title></circle>'
                 f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" '
                 f'font-size="14" font-weight="bold" fill="#fff">'
                 f'{"✓" if done else s["n"]}</text></g>')
        y = cy + 40
        for t in s["tags"][:3]:
            oo = by_tag.get(t)
            ss = alarm_semantics(getattr(oo, "type_code", "")) if oo else {}
            lab = (f"{t} P{ss.get('priority', '?')}"
                   f"{DIR_ARROW.get(ss.get('direction'), '')}")
            act = t in active
            P.append(f'<text x="{cx}" y="{y}" text-anchor="middle" '
                     f'font-size="11" fill="{"#f0d0c8" if act else "#9aa4ae"}">'
                     f'{_html.escape(lab)}'
                     f'{" 🔔" if act else ""}</text>')
            y += 15
        if not s["tags"]:
            P.append(f'<text x="{cx}" y="{y}" text-anchor="middle" '
                     f'font-size="11" fill="#556070">(no register tag)</text>')
    P.append('<defs><marker id="qa_ar" viewBox="0 0 10 10" refX="9" refY="5" '
             'markerWidth="6" markerHeight="6" orient="auto">'
             '<path d="M0 0L10 5L0 10z" fill="#3a4250"/></marker></defs>')
    P.append(f'<text x="{w - 10}" y="{h - 8}" text-anchor="end" '
             f'font-size="10" fill="#556070">parsed from the answer · every '
             f'tag verified against the register · 🔔 = currently alarming</text>')
    P.append("</svg>")
    return "".join(P)


def answer_coverage_svg(active: list[str], verified_tokens: list[str],
                        suspect_tokens: list[str], by_tag,
                        w: int = 1100, per_row: int = 9) -> str:
    """Visual form of the tag audit: one chip per ACTIVE alarm — lit if
    the answer referenced it, dimmed if the answer ignored it — plus a
    red block for tokens the answer used that do NOT exist in the model
    (hallucination flags). Turns 'tag check: ✅/❓' into a coverage map."""
    import html as _html
    ref = set(canonicalize_tags(verified_tokens, by_tag).values())
    rows = [active[i:i + per_row] for i in range(0, len(active), per_row)]
    chw = (w - 40) // per_row
    rowh = 34
    h = 26 + rowh * len(rows) + (30 if suspect_tokens else 0) + 10
    P = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'style="width:100%;height:auto;font-family:sans-serif">']
    P.append(f'<text x="20" y="16" font-size="11" fill="#9aa4ae">'
             f'Answer coverage of the {len(active)} active alarms — '
             f'lit = referenced, dim = not mentioned</text>')
    y0 = 26
    for ri, row in enumerate(rows):
        for ci, t in enumerate(row):
            x = 20 + ci * chw
            y = y0 + ri * rowh
            on = t in ref
            P.append(
                f'<g><rect x="{x}" y="{y}" width="{chw - 8}" height="24" '
                f'rx="6" fill="{"#2d5a3d" if on else "#232a35"}" '
                f'stroke="{"#3f8f4f" if on else "#2e3644"}">'
                f'<title>{_html.escape(t)}: '
                f'{"referenced in the answer" if on else "not mentioned"}'
                f'</title></rect>'
                f'<text x="{x + (chw - 8) / 2}" y="{y + 16}" '
                f'text-anchor="middle" font-size="10" '
                f'fill="{"#c9e7d2" if on else "#5c6673"}">'
                f'{_html.escape(t)}</text></g>')
    if suspect_tokens:
        y = y0 + rowh * len(rows) + 6
        P.append(f'<text x="20" y="{y + 14}" font-size="11" fill="#e07b6a">'
                 f'❓ tokens NOT in the model (verify!): '
                 f'{_html.escape(", ".join(suspect_tokens[:8]))}'
                 + (" …" if len(suspect_tokens) > 8 else "") + '</text>')
    P.append("</svg>")
    return "".join(P)


def agent_trace_svg(n_active: int, n_candidates: int, top_tag: str | None,
                    top_explains: int, n_ce: int, prompt_chars: int,
                    n_verified: int, n_suspect: int, cached: bool = False,
                    w: int = 1100) -> str:
    """The agent's pipeline for ONE answer, as a figure: which stages are
    deterministic (blue, verifiable) and which single stage is generative
    (amber). Every number shown is real for the current scenario/answer.
    This is the 'how do I know it's not making this up?' picture."""
    import html as _html
    DET, AI = "#1d3a5f", "#7a4a12"
    DETS, AIS = "#2d7dd2", "#f4a259"
    ok = n_suspect == 0
    stages = [
        ("Alarm picture", f"{n_active} active alarms", "priority-sorted, tag-annotated", DET, DETS),
        ("Structural analysis", f"{n_candidates} candidate roots",
         f"top {top_tag or '—'} explains {top_explains}", DET, DETS),
        ("SCD C&E + modes", f"{n_ce} designed-response lines",
         "read from the SCD sheets", DET, DETS),
        ("Grounded prompt", f"fixed template · {prompt_chars:,} facts chars",
         "facts block, tag ban, forced structure", DET, DETS),
        ("LLM answer", "🗂️ cached response" if cached else "Gemini",
         "the ONLY generative stage", AI, AIS),
        ("Tag audit", f"✅ {n_verified} verified"
         + (f" · ❓ {n_suspect} suspect" if n_suspect else " · 0 invented"),
         "every token checked vs register", DET,
         "#3f8f4f" if ok else "#b8442c"),
    ]
    n = len(stages)
    gap = 26
    bw = (w - 40 - gap * (n - 1)) // n
    bh, y0 = 74, 26
    h = y0 + bh + 34
    P = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'style="width:100%;height:auto;font-family:sans-serif">']
    for i, (title, big, small, fill, stroke) in enumerate(stages):
        x = 20 + i * (bw + gap)
        if i:
            P.append(f'<line x1="{x - gap + 2}" y1="{y0 + bh / 2}" '
                     f'x2="{x - 3}" y2="{y0 + bh / 2}" stroke="#3a4250" '
                     f'stroke-width="2" marker-end="url(#tr_ar)"/>')
        P.append(f'<rect x="{x}" y="{y0}" width="{bw}" height="{bh}" rx="8" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        cx = x + bw / 2
        P.append(f'<text x="{cx}" y="{y0 + 20}" text-anchor="middle" '
                 f'font-size="11" font-weight="bold" fill="#e8edf2">'
                 f'{_html.escape(title)}</text>')
        P.append(f'<text x="{cx}" y="{y0 + 40}" text-anchor="middle" '
                 f'font-size="11" fill="#cfd6dd">{_html.escape(big)}</text>')
        P.append(f'<text x="{cx}" y="{y0 + 58}" text-anchor="middle" '
                 f'font-size="9" fill="#8a95a3">{_html.escape(small)}</text>')
    P.append('<defs><marker id="tr_ar" viewBox="0 0 10 10" refX="9" refY="5" '
             'markerWidth="6" markerHeight="6" orient="auto">'
             '<path d="M0 0L10 5L0 10z" fill="#3a4250"/></marker></defs>')
    P.append(f'<rect x="20" y="{h - 22}" width="10" height="10" rx="2" '
             f'fill="{DET}" stroke="{DETS}"/>'
             f'<text x="36" y="{h - 13}" font-size="10" fill="#9aa4ae">'
             f'deterministic — computed from the model, verifiable</text>'
             f'<rect x="330" y="{h - 22}" width="10" height="10" rx="2" '
             f'fill="{AI}" stroke="{AIS}"/>'
             f'<text x="346" y="{h - 13}" font-size="10" fill="#9aa4ae">'
             f'generative — 1 of {n} stages; its output is audited by the '
             f'next</text>')
    P.append("</svg>")
    return "".join(P)


def parse_hold_off(text: str, by_tag) -> dict | None:
    """Extract the DO NOT ACT YET section (section 3 of the fixed
    template): the hold-off instruction and the register-verified tags it
    names. Deterministic parse; None if the answer lacks the section."""
    import re as _re
    m = _re.search(r"DO\s+NOT\s+ACT\s+YET[^\n]*?[\u2014\-:\u2013]*\s*(.+?)"
                   r"(?:Structural\s+decision\s+support|$)", text,
                   _re.S | _re.I)
    if not m:
        return None
    body = _re.sub(r"[*_#]+", "", m.group(1)).strip()
    body = _re.sub(r"\s+", " ", body).lstrip("—–-: ").strip()
    if not body:
        return None
    toks = _re.findall(_TAG_TOKEN_RE, body)
    tags = list(dict.fromkeys(canonicalize_tags(toks, by_tag).values()))
    return {"text": body, "tags": tags}


def agent_pick(text: str, by_tag, cand_tags: list[str]) -> str | None:
    """Which CANDIDATE the answer's WEIGHING EVIDENCE section favours,
    inferred deterministically: the candidate tag mentioned most often in
    section 1 (ties -> first mention). None if the section is missing or
    names no candidate. Used to compare the agent's stance against the
    structural top candidate — agreement confirms, disagreement is the
    moment the operator should read closely."""
    import re as _re
    m = _re.search(r"WEIGHING\s+EVIDENCE(.*?)(?:VERIFICATION\s+PLAN|$)",
                   text, _re.S | _re.I)
    if not m:
        return None
    sec = m.group(1)
    canon = canonicalize_tags(set(_re.findall(_TAG_TOKEN_RE, sec)), by_tag)
    cset = set(cand_tags)
    counts, first = {}, {}
    for tok, c in canon.items():
        if c not in cset:
            continue
        n = len(_re.findall(_re.escape(tok), sec))
        counts[c] = counts.get(c, 0) + n
        pos = sec.find(tok)
        if pos >= 0:
            first[c] = min(first.get(c, 10**9), pos)
    if not counts:
        return None
    return max(counts, key=lambda c: (counts[c], -first.get(c, 10**9)))


def synthetic_trends(timeline: dict, window: float, by_tag,
                     seed: str = "", pre: float = 15.0, post: float = 5.0,
                     step: float = 1.0, noise_level: float = 0.0) -> dict:
    """SYNTHETIC process trends for demo purposes — generated ONLY from
    the alarm arrival order (which the operator sees anyway), never from
    the hidden fault, so the game leaks nothing. Illustrates what the
    pilot does once real historian data is connected: each alarmed tag
    drifts from baseline starting a few seconds BEFORE its alarm, crosses
    its threshold exactly at the alarm time, then plateaus. Direction
    (high/low) follows the tag's alarm semantics. Deterministic per
    scenario via `seed`.

    `noise_level` (default 0.0 = clean, identical to before) adds
    realistic imperfection FOR ROBUSTNESS TESTING, drawn from a separate
    random stream so the base curves are unchanged: gaussian measurement
    noise, slow PV oscillation, and occasional baseline excursions toward
    the limit that retreat ("limit sniffers") — the classic source of
    false early warnings. ~1.0 is realistic, ~2.0 harsh.

    Returns {'t': [...], 'series': {tag: [...]}, 'hi': 80, 'lo': 20,
             'lead': {tag: seconds of pre-alarm drift}}."""
    import random
    from analysis.alarm_priority import alarm_semantics
    HI, LO, BASE = 80.0, 20.0, 50.0
    ts = []
    t = -pre
    while t <= window + post:
        ts.append(round(t, 2))
        t += step
    series, lead = {}, {}
    prev_onset = None
    for tag in sorted(timeline, key=timeline.get):   # arrival order
        t_a = timeline[tag]
        rng = random.Random(f"{seed}|{tag}")
        ld = rng.uniform(6.0, 13.0)
        # temporal coherence: drift ONSET order must follow arrival order
        # (earlier alarm ⇒ earlier or equal onset) — still derived from
        # arrival only, so nothing about the hidden fault leaks.
        onset = t_a - ld
        if prev_onset is not None and onset < prev_onset + 0.5:
            onset = prev_onset + 0.5
            ld = max(1.5, t_a - onset)
        prev_onset = onset
        lead[tag] = ld
        o = by_tag.get(tag)
        sem = alarm_semantics(getattr(o, "type_code", "")) if o else {}
        low = sem.get("direction") == "low"
        thr = LO if low else HI
        # imperfection layer (separate stream: base curves stay identical)
        nz = None
        if noise_level > 0:
            import math as _m
            r2 = random.Random(f"{seed}|noise|{tag}")
            amp_o = 2.2 * noise_level
            per = r2.uniform(18.0, 45.0)
            ph = r2.uniform(0.0, per)
            bumps = []
            for _ in range(r2.randint(0, 2)):        # limit sniffers
                c = r2.uniform(ts[0], max(ts[0] + 1.0, onset - 2.0))
                bumps.append((c, r2.uniform(4.0, 9.0)
                              * min(noise_level, 1.5),
                              r2.uniform(3.0, 6.0)))
            sgn = -1.0 if low else 1.0

            def nz(tt):
                v = amp_o * _m.sin(2 * _m.pi * (tt + ph) / per)
                v += r2.gauss(0.0, 0.9 * noise_level)
                for c, a, wdt in bumps:
                    v += sgn * a * _m.exp(-((tt - c) / wdt) ** 2)
                return v
        vals = []
        for tt in ts:
            j = rng.uniform(-1.2, 1.2)
            if tt < t_a - ld:
                v = BASE + j
            elif tt < t_a:
                p = (tt - (t_a - ld)) / ld            # 0→1 up to alarm
                v = BASE + (thr - BASE) * (p * p * (3 - 2 * p)) + j  # smoothstep
            else:
                over = min(12.0, (tt - t_a) * 1.5)
                v = thr + (-over if low else over) * 0.8 + j
            if nz is not None:
                v += nz(tt)
            vals.append(round(max(0.0, min(100.0, v)), 2))
        series[tag] = vals
    return {"t": ts, "series": series, "hi": HI, "lo": LO, "lead": lead}


def trend_svg(trends: dict, timeline: dict, elapsed: float, window: float,
              active: list[str], by_tag, glow: set | None = None,
              max_series: int = 8, w: int = 1100) -> str:
    """Live HMI-style trend chart of the SYNTHETIC series: lines clipped
    at «now» during playback (they grow with the sweep), dashed HI/LO
    alarm limits, a dot where each series crosses its limit (= its alarm
    time), category colors, gold ⌾ label for tags referenced by the AI
    answer, and an unmissable SYNTHETIC watermark."""
    import html as _html
    from config import CATEGORY_COLORS
    show = [t for t in active if t in trends["series"]][:max_series]
    if not show:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>"
    ts = trends["t"]
    t0, t1 = ts[0], ts[-1]
    h, left, right, top, bot = 300, 60, 120, 24, 34
    def X(t): return left + (t - t0) / (t1 - t0) * (w - left - right)
    def Y(v): return top + (100 - v) / 100 * (h - top - bot)
    cut = min(elapsed, t1) if elapsed < window else t1
    P = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'style="width:100%;height:auto;font-family:sans-serif">']
    # axes + thresholds
    P.append(f'<line x1="{left}" y1="{Y(0)}" x2="{w - right}" y2="{Y(0)}" '
             f'stroke="#2e3644"/>')
    for thr, lab in ((trends["hi"], "HI alarm"), (trends["lo"], "LO alarm")):
        P.append(f'<line x1="{left}" y1="{Y(thr)}" x2="{w - right}" '
                 f'y2="{Y(thr)}" stroke="#b8442c" stroke-width="1" '
                 f'stroke-dasharray="6 4" opacity="0.7"/>'
                 f'<text x="{left - 6}" y="{Y(thr) + 4}" text-anchor="end" '
                 f'font-size="10" fill="#b8442c">{lab}</text>')
    P.append(f'<text x="{left - 6}" y="{Y(50) + 4}" text-anchor="end" '
             f'font-size="10" fill="#556070">base</text>')
    # t=0 marker (first alarm)
    P.append(f'<line x1="{X(0)}" y1="{top}" x2="{X(0)}" y2="{Y(0)}" '
             f'stroke="#3a4250" stroke-dasharray="2 3"/>'
             f'<text x="{X(0)}" y="{h - 12}" text-anchor="middle" '
             f'font-size="10" fill="#556070">t=0 (first alarm)</text>')
    for tag in show:
        o = by_tag.get(tag)
        col = CATEGORY_COLORS.get(getattr(o, "category", "other"), "#9aa0a6")
        pts, last = [], None
        for tt, v in zip(ts, trends["series"][tag]):
            if tt <= cut:
                pts.append(f"{X(tt):.1f},{Y(v):.1f}")
                last = (tt, v)
        if not pts:
            continue
        P.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                 f'stroke="{col}" stroke-width="1.8" opacity="0.9"/>')
        t_a = timeline.get(tag, 0.0)
        if t_a <= cut:                       # alarm-crossing marker
            _ia = min(range(len(ts)), key=lambda k: abs(ts[k] - t_a))
            thr = (trends["hi"]
                   if trends["series"][tag][_ia] >= 50 else trends["lo"])
            P.append(f'<circle cx="{X(t_a):.1f}" cy="{Y(thr):.1f}" r="4.5" '
                     f'fill="#e07b6a" stroke="#141820" stroke-width="1.5">'
                     f'<title>{_html.escape(tag)} alarm at +{t_a:.0f}s</title>'
                     f'</circle>')
        if last:
            gl = glow and tag in glow
            _ev, _eu = eng_of(tag, last[1], by_tag)
            P.append(f'<text x="{X(last[0]) + 6:.1f}" y="{Y(last[1]) + 4:.1f}" '
                     f'font-size="10" font-weight="{"bold" if gl else "normal"}" '
                     f'fill="{"#f4d35e" if gl else col}">'
                     f'{"⌾ " if gl else ""}{_html.escape(tag)} · '
                     f'{_ev:.0f} {_eu}</text>')
    if elapsed < window:                      # sweep «now»
        P.append(f'<line x1="{X(cut):.1f}" y1="{top}" x2="{X(cut):.1f}" '
                 f'y2="{Y(0)}" stroke="#f4a259" stroke-width="1.5" '
                 f'opacity="0.85"/>')
    P.append(f'<text x="{w - right}" y="{top - 6}" text-anchor="end" '
             f'font-size="12" font-weight="bold" fill="#e0a800" '
             f'opacity="0.9">⚠ SYNTHETIC DEMO DATA</text>')
    P.append("</svg>")
    return "".join(P)


def load_incident(path) -> dict:
    """Load a historical demo incident (made by tools/make_demo_incident.py)
    and shape it for the Control Room page: a shower-compatible dict plus
    a trends dict matching synthetic_trends' format, so the whole pipeline
    — watch log, auto-brief, trend panel, debrief — replays the recorded
    incident unchanged. Raises FileNotFoundError/ValueError on bad data."""
    import csv as _csv
    import json as _json
    from pathlib import Path as _P
    p = _P(path)
    meta = _json.loads((p / "incident.json").read_text(encoding="utf-8"))
    timeline: dict[str, float] = {}
    _alm: dict[str, list[float]] = {}
    _rtn: dict[str, list[float]] = {}
    with (p / "alarms.csv").open(encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            t = float(row["offset_s"])
            if row.get("state", "ALM").upper() == "RTN":
                _rtn.setdefault(row["tag"], []).append(t)
                continue
            _alm.setdefault(row["tag"], []).append(t)
            if row["tag"] not in timeline or t < timeline[row["tag"]]:
                timeline[row["tag"]] = t
    chatter = {t: {"alm": sorted(a), "rtn": sorted(_rtn.get(t, []))}
               for t, a in _alm.items() if len(a) >= 3}
    if not timeline:
        raise ValueError("alarms.csv contains no rows")
    alarms = sorted(timeline, key=timeline.get)
    window = max(timeline.values())
    series: dict[str, dict[float, float]] = {}
    with (p / "trends.csv").open(encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            series.setdefault(row["tag"], {})[float(row["offset_s"])] = \
                float(row["value_pct"])
    ts = sorted(next(iter(series.values())).keys()) if series else []
    lead = {}
    for tag, t_a in timeline.items():
        sv = series.get(tag, {})
        base_ts = [t for t in sv if t < t_a and abs(sv[t] - 50) <= 3.0]
        lead[tag] = max(4.0, min(15.0, t_a - max(base_ts))) if base_ts else 8.0
    sol = meta.get("solution", {})
    shower = {"alarms": alarms, "timeline": timeline, "window": window,
              "first_up": meta.get("first_up", alarms[0]),
              "cascade": sol.get("cascade", alarms),
              "noise": sol.get("noise", []),
              "exposed": len(alarms),
              "chatter": chatter,
              "step": max(1.0, window / max(1, len(alarms) - 1))}
    trends = {"t": ts,
              "series": {t: [series[t].get(tt, 50.0) for tt in ts]
                         for t in series},
              "hi": 80.0, "lo": 20.0, "lead": lead}
    return {"meta": meta, "fault": sol.get("fault", alarms[0]),
            "shower": shower, "trends": trends}


ENG_RANGES = {"P": (0.0, 120.0, "barg"), "T": (0.0, 200.0, "°C"),
              "F": (0.0, 500.0, "m³/h"), "L": (0.0, 100.0, "%")}


def eng_of(tag: str, pct: float, by_tag=None) -> tuple[float, str]:
    """Map a normalized 0–100 % value to plausible ENGINEERING UNITS by
    tag type (P→barg, T→°C, F→m³/h, L→%). Display cosmetics only — the
    underlying synthetic values stay normalized; this just removes the
    most obvious 'this is simulated' signal from labels and exports."""
    import re as _re
    tc = getattr(by_tag.get(tag), "type_code", "") if by_tag else ""
    letter = (tc or "").strip()[:1].upper()
    if not letter:
        m = _re.search(r"([A-Z])[A-Z]*\d", tag.replace("-", ""))
        letter = m.group(1) if m else "L"
    lo, hi, unit = ENG_RANGES.get(letter, (0.0, 100.0, "%"))
    return lo + (hi - lo) * pct / 100.0, unit


def synthetic_chatter(noise_tags: list[str], timeline: dict, window: float,
                      seed: str = "") -> dict:
    """SYNTHETIC alarm chatter — the most common nuisance in real alarm
    management, absent from clean demos: pick ~half of the NOISE tags and
    give them repeated ALM→RTN→ALM activations after their first alarm.
    Deterministic per seed; cascade tags never chatter (their alarms are
    'real'). Returns {tag: {'alm': [t...], 'rtn': [t...]}} — 'alm'[0] is
    the original activation from the timeline."""
    import random
    rng = random.Random(f"{seed}|chatter")
    picks = [t for t in sorted(noise_tags) if t in timeline]
    picks = picks[:max(1, len(picks) // 2)] if picks else []
    out = {}
    for tag in picks:
        t0 = timeline[tag]
        alm, rtn = [t0], []
        cur = t0
        for _ in range(rng.randint(2, 4)):          # re-activations
            r = cur + rng.uniform(1.5, 4.0)
            a = r + rng.uniform(1.0, 3.0)
            if a > window + 8.0:
                break
            rtn.append(round(r, 1))
            alm.append(round(a, 1))
            cur = a
        if len(alm) >= 3:                           # only real chatterers
            out[tag] = {"alm": alm, "rtn": rtn}
    return out


def chatter_events(state: dict | None, chatter: dict,
                   elapsed: float) -> tuple[dict, list[dict]]:
    """Watch layer for chatter: when a tag reaches its 3rd activation
    within the window, flag it once — with the ISA-18.2 remedy (shelving)
    and the operational advice (treat as unreliable until it holds)."""
    st_ = {"flagged": set(state.get("flagged") or set()) if state else set()}
    ev: list[dict] = []
    for tag, d in (chatter or {}).items():
        if tag in st_["flagged"]:
            continue
        n = sum(1 for a in d["alm"] if a <= elapsed)
        if n >= 3:
            span = elapsed - d["alm"][0]
            ev.append({"t": elapsed, "icon": "⚡", "text":
                       f"**{tag}** has alarmed {n}× in {span:.0f} s — "
                       f"CHATTERING. Shelving candidate per ISA-18.2; "
                       f"treat as unreliable noise until it holds."})
            st_["flagged"].add(tag)
    return st_, ev


def trend_watch_events(state: dict | None, trends: dict, timeline: dict,
                       elapsed: float) -> tuple[dict, list[dict]]:
    """EARLY WARNING from the (synthetic) trends: while the shower rolls,
    detect tags that are drifting from baseline but have NOT alarmed yet,
    and estimate time-to-limit from the current slope. Uses ONLY samples
    up to «now» — the agent never peeks ahead. Deterministic; one warning
    per tag. This is the pilot capability real historian data unlocks:
    the agent runs AHEAD of the alarm list instead of reacting to it."""
    st_ = {"warned": set(state.get("warned") or set()) if state else set()}
    ev: list[dict] = []
    ts = trends["t"]
    for tag, t_a in timeline.items():
        if t_a <= elapsed or tag in st_["warned"]:
            continue                      # already alarmed / already warned
        vis = [(tt, v) for tt, v in zip(ts, trends["series"][tag])
               if tt <= elapsed]
        if len(vis) < 4:
            continue
        v = vis[-1][1]
        dev = v - 50.0
        if abs(dev) < 6.0:
            continue                      # still within baseline noise
        (ta_, va_), (tb_, vb_) = vis[-4], vis[-1]
        slope = (vb_ - va_) / max(0.5, tb_ - ta_)     # %/s
        thr = trends["hi"] if dev > 0 else trends["lo"]
        eta = ((thr - v) / slope
               if slope and (thr - v) * slope > 0 else None)
        if eta is not None and 0 < eta <= 30:
            txt = (f"**{tag}** is drifting from baseline ({v:.0f} %) — "
                   f"at this rate it reaches its alarm limit in "
                   f"~{eta:.0f} s. *(synthetic trend)*")
        else:
            txt = (f"**{tag}** is drifting from baseline ({v:.0f} %) — "
                   f"no alarm yet; watch it. *(synthetic trend)*")
        ev.append({"t": elapsed, "icon": "📈" if dev > 0 else "📉",
                   "text": txt})
        st_["warned"].add(tag)
    return st_, ev


def structure_time_verdict(briefs, trends: dict, timeline: dict) -> list[dict]:
    """At sequence completion: combine STRUCTURAL evidence (explains-count)
    with TEMPORAL evidence (who moved first, from drift onsets) into a
    joint verdict — agreement is confirming, disagreement is exactly when
    the operator should slow down. Also flags alarmed tags whose drift
    window is uncorrelated with the main development (noise support).
    Deterministic; trends are synthetic and said to be."""
    if not timeline:
        return []
    onset = {t: timeline[t] - trends.get("lead", {}).get(t, 8.0)
             for t in timeline}
    first_mover = min(onset, key=onset.get)
    w_end = max(timeline.values())
    ev: list[dict] = []
    leader = briefs[0]["tag"] if briefs else None
    if leader:
        if first_mover == leader:
            ev.append({"t": w_end, "icon": "🤝", "text":
                       f"Structure and time point the same way: "
                       f"**{leader}** explains most of the board AND moved "
                       f"first (drift onset {onset[leader]:+.0f} s). "
                       f"*(synthetic trend)*"})
        else:
            ev.append({"t": w_end, "icon": "⚖️", "text":
                       f"Structural evidence favours **{leader}**, but "
                       f"**{first_mover}** moved FIRST (onset "
                       f"{onset[first_mover]:+.0f} s vs "
                       f"{onset.get(leader, 0):+.0f} s). With real data this "
                       f"split is exactly when to slow down and verify. "
                       f"*(synthetic trend)*"})
        # co-movement: isolated candidates far from the main cluster
        main = sorted(onset[t] for t in
                      [leader, *briefs[0]["explains"]] if t in onset)
        if main:
            med = main[len(main) // 2]
            for b in briefs[1:]:
                t = b["tag"]
                if not b["explains"] and t in onset \
                        and abs(onset[t] - med) > 8.0:
                    ev.append({"t": w_end, "icon": "🔬", "text":
                               f"**{t}**'s drift window is uncorrelated "
                               f"with the main development (onset "
                               f"{onset[t]:+.0f} s vs cluster ~{med:+.0f} s)"
                               f" — supports the noise hypothesis. "
                               f"*(synthetic trend)*"})
    return ev


def incident_report_md(title: str, fault: str, chosen: str | None,
                       shower: dict, watch_log: list[dict],
                       qa_hist: list, briefs, by_tag,
                       debrief_lines: list[str],
                       drawings_of: dict | None = None,
                       replay_meta: dict | None = None,
                       trends: dict | None = None) -> str:
    """Assemble the complete INCIDENT REPORT as Markdown — the document a
    shift would otherwise write by hand after an event: what happened
    (timeline), what the agent said while it happened (watch log, with
    timestamps), what it assessed and how that was audited, what the
    operator decided, and the verdict. Pure function over data the app
    already holds; nothing is generated here, only assembled — so the
    report is exactly as trustworthy as its sources, and says so."""
    import re as _re
    from datetime import datetime, timezone
    from analysis.alarm_priority import alarm_semantics, DIR_ARROW

    def _plain(s: str) -> str:
        return _re.sub(r"\*\*?", "", str(s))

    timeline = shower.get("timeline", {})
    noise = set(shower.get("noise", []))
    chatter = shower.get("chatter") or {}
    order = sorted(timeline, key=timeline.get)
    L: list[str] = []
    L.append(f"# Incident report — {title}")
    L.append("")
    L.append(f"*Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} · "
             f"training/demonstration on SYNTHETIC data — structural model is "
             f"real, timestamps and process values are generated.*")
    if replay_meta:
        L.append(f"*Replayed historical demo incident recorded "
                 f"{str(replay_meta.get('start_iso', ''))[:16]}.*")
    L.append("")
    L.append("## Summary")
    L.append("")
    verdict = debrief_lines[0] if debrief_lines else ""
    L.append(f"- **Alarms:** {len(order)} in {shower.get('window', 0):.0f} s "
             f"(first-up **{shower.get('first_up', '?')}**)")
    L.append(f"- **Operator's call:** {chosen or '(none)'}")
    L.append(f"- **{_plain(verdict)}**")
    top = briefs[0] if briefs else None
    if top:
        L.append(f"- **Top structural candidate at completion:** "
                 f"{top['tag']} — explained {len(top['explains'])} of the "
                 f"other active alarms")
    if drawings_of:
        drw = sorted({d for t in order for d in drawings_of.get(t, [])})
        if drw:
            L.append(f"- **Drawings involved:** {', '.join(drw)}")
    L.append("")
    L.append("## Alarm timeline")
    L.append("")
    L.append("| +t (s) | tag | prio | role | activations |")
    L.append("|---:|---|---|---|---:|")
    for t in order:
        o = by_tag.get(t)
        sem = alarm_semantics(getattr(o, "type_code", "")) if o else {}
        pr = (f"P{sem.get('priority', '?')}"
              f"{DIR_ARROW.get(sem.get('direction'), '')}")
        role = ("noise" if t in noise else
                "root" if t == fault else "cascade")
        n_act = len(chatter.get(t, {}).get("alm", [])) or 1
        L.append(f"| {timeline[t]:.1f} | {t} | {pr} | {role} | "
                 f"{n_act}{' (chatter)' if n_act >= 3 else ''} |")
    L.append("")
    if watch_log:
        L.append("## Agent watch log (as it happened)")
        L.append("")
        for e in watch_log:
            L.append(f"- `+{e.get('t', 0):>5.1f}s` {e.get('icon', '')} "
                     f"{_plain(e.get('text', ''))}")
        L.append("")
    if qa_hist:
        L.append("## Agent assessment & Q&A (audited)")
        L.append("")
        for q, a, aud in qa_hist:
            L.append(f"**Q:** {_plain(q)}")
            L.append("")
            L.append(a.strip())
            L.append("")
            ver, sus = aud.get("verified", []), aud.get("suspect", [])
            L.append(f"*Tag audit: {len(ver)} verified"
                     + (f" · {len(sus)} NOT in the model: "
                        f"{', '.join(sus)}" if sus else " · 0 invented")
                     + "*")
            L.append("")
    L.append("## Operator decision & debrief")
    L.append("")
    for line in debrief_lines:
        L.append(f"- {_plain(line)}")
    L.append("")
    L.append("## Basis & limitations")
    L.append("")
    L.append("- Candidate ranking and the watch log are **deterministic** "
             "structural analysis of the extracted topology (DEXPI/SCD); "
             "the graph shows reachability, not process consequence.")
    L.append("- The AI assessment is a single generative step over a fixed, "
             "fact-grounded template; every tag token was audited against "
             "the register (results above).")
    L.append("- Process trends and timestamps are **synthetic**, generated "
             "from the alarm arrival order for demonstration; trend-based "
             "statements are marked as such in the log.")
    L.append("- Decision support only — the operator's judgment prevails.")
    L.append("")
    return "\n".join(L)


def agent_watch_events(state: dict | None, active: list[str], briefs,
                       by_tag, timeline: dict, window: float,
                       first_up: str | None,
                       flood_n: int = 10) -> tuple[dict, list[dict]]:
    """The proactive agent: compare the CURRENT alarm picture against the
    last observed state and emit commentary events when something material
    changed — unprompted, while the shower rolls. Fully deterministic
    (same structural analysis as the Situation Brief, narrated live);
    call it every rerun and append the returned events to a session log.

    Events (each {'t','icon','text'}, t = arrival offset that triggered):
      watch start · leading-hypothesis change · consolidation (>=70 % of
      the board explained) · alarm flood (ISA-18.2: >=10 alarms in a
      short burst) · newly arrived alarms the current picture cannot
      explain · sequence complete summary."""
    n = len(active)
    t_now = max((timeline.get(a, 0.0) for a in active), default=0.0)
    leader = briefs[0]["tag"] if briefs else None
    m = len(briefs[0]["explains"]) if briefs else 0
    isolated = {b["tag"] for b in briefs if not b["explains"]} - {leader}
    st_ = dict(state or {})
    ev: list[dict] = []

    def _e(icon, text):
        ev.append({"t": t_now, "icon": icon, "text": text})

    if not state:
        _e("👁", f"Watch started — first-up **{first_up or active[0]}**. "
                 f"Following the picture as it develops.")
        st_ = {"leader": leader, "consol": False, "flood": False,
               "isolated": set(), "complete": False}
    else:
        st_["isolated"] = set(st_.get("isolated") or set())
        if leader and st_.get("leader") and leader != st_["leader"] and n >= 3:
            _e("🔁", f"Hypothesis update: **{leader}** now explains "
                     f"**{m}** of {n - 1} other active alarms — takes the "
                     f"lead from {st_['leader']}.")
        elif leader and not st_.get("leader"):
            _e("🔍", f"First structural candidate: **{leader}**.")
        st_["leader"] = leader

        if (not st_["consol"] and leader and n >= 5
                and m >= 0.7 * (n - 1)):
            _e("📈", f"The picture is consolidating: **{leader}** explains "
                     f"**{m}/{n - 1}** of the board. Verify before acting — "
                     f"see the candidate brief.")
            st_["consol"] = True

        if not st_["flood"] and n >= flood_n:
            _e("🌊", f"**{n} alarms** in one burst — alarm flood by the "
                     f"ISA-18.2 yardstick (≥{flood_n}/10 min). Work "
                     f"P1/P2 first; the candidate ranking is your map.")
            st_["flood"] = True

        new_iso = isolated - st_["isolated"]
        if new_iso and n >= 3:
            lst = ", ".join(f"**{t}**" for t in sorted(new_iso)[:4])
            _e("❓", f"{lst} cannot be explained by any other active "
                     f"alarm — independent fault or noise. Keep separate "
                     f"from the main hypothesis.")
        st_["isolated"] |= isolated

    if not st_.get("complete") and t_now >= window and n >= 2:
        iso_n = len(st_.get("isolated") or isolated)
        _e("🏁", f"Sequence complete: **{n} alarms** in. Leading "
                 f"hypothesis **{leader}** explains **{m}/{n - 1}**"
                 + (f"; {iso_n} alarm(s) unexplained by it."
                    if iso_n else " — the whole board.")
                 + " Ready for your verification and decision.")
        st_["complete"] = True
    return st_, ev


def shower_debrief(fault: str, chosen: str | None, noise: list[str],
                   n_active: int, board: list[str] | None = None,
                   first_up: str | None = None) -> list[str]:
    lines = [f"Actual fault origin: {fault}."]
    silent_root = board is not None and fault not in board
    if silent_root:
        lines[0] = (f"Actual fault origin: {fault} — NOT alarm-capable "
                    f"(e.g. a manual valve/equipment without "
                    f"instrumentation). The source itself NEVER rings and "
                    f"was therefore not on the board — a realistic and "
                    f"difficult case: the root is silent, only the "
                    f"symptoms speak.")
        if chosen == fault:
            pass  # unreachable via the board, but keep the standard branch
        elif chosen is not None and chosen == first_up:
            lines.append(f"You pointed at {chosen} — the source's FIRST "
                         f"alarming symptom, as close to the root as an "
                         f"operator can get from the board alone. Counts "
                         f"as a hit: the next step in the field would be "
                         f"to inspect upstream of {chosen}, where {fault} "
                         f"sits.")
            chosen = None  # verdict delivered; skip the generic branches
    if chosen == fault:
        lines.append("Correct — you identified the source in the alarm shower.")
    elif chosen in noise:
        lines.append(f"{chosen} was a NOISE ALARM with no connection to the "
                     f"incident — in a real shower, unrelated chatter is "
                     f"precisely the most common trap.")
    elif chosen is not None:
        lines.append(f"{chosen} was a downstream SYMPTOM of {fault} — the "
                     f"structural evidence to look for: the source explains "
                     f"most of the other alarms, the symptom explains few.")
    if noise:
        lines.append(f"Noise alarms in the picture: {', '.join(noise)} — "
                     f"independent of the incident.")
    lines.append(f"A total of {n_active} concurrent alarms. Training "
                 f"scenario on synthetic data — the assistant's brief was "
                 f"structural, the judgment was yours.")
    return lines


def debrief(fault: str, isolated: str | None, alarms_seen: int,
            total_cascade: int) -> list[str]:
    """Post-scenario feedback: did the operator isolate the true origin,
    and how early?"""
    lines = [f"Actual fault origin in the scenario: {fault}."]
    if isolated is None:
        lines.append("No isolation was performed — the cascade ran "
                     f"{alarms_seen} of {total_cascade} possible alarms.")
    elif isolated == fault:
        lines.append(f"Correct component isolated ({isolated}) after "
                     f"{alarms_seen} alarm(s) — the cascade stopped at "
                     f"the source.")
    else:
        lines.append(f"Isolated {isolated}, but the source was {fault} — "
                     f"downstream isolation stops symptoms, not the cause.")
    lines.append("Training scenario on synthetic data — the assistant's "
                 "suggestions were structural, the operator's judgment "
                 "decided.")
    return lines

def alarm_timeline_svg(timeline: dict, shown: list[str], by_tag,
                       cascade: list[str], noise: list[str],
                       elapsed: float, window: float,
                       reveal_roles: bool = False,
                       first_up: str | None = None,
                       drawings_of: dict | None = None,
                       glow: set | None = None,
                       chatter: dict | None = None,
                       w: int = 1100) -> str:
    """Arrival timeline of the alarm shower: one row per alarm (in arrival
    order), a dot at its +t offset, colored by tag category. While the
    sequence is still rolling a sweep line marks 'now'. After the operator
    has answered (reveal_roles=True) the dots are recolored by ROLE —
    cascade vs. noise, with the true fault ringed — so the debrief shows
    the shape of the incident at a glance. Fault-blind until then."""
    import html as _html
    from config import CATEGORY_COLORS

    rows = sorted((t for t in shown if t in timeline),
                  key=lambda t: (timeline[t], t))
    if not rows:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>"
    span = max(window, max(timeline[t] for t in rows), 1.0)
    left, right, top, rowh = 190, 30, 34, 30
    h = top + rowh * len(rows) + 34
    px = lambda s: left + (w - left - right) * (s / span)

    cascade_set, noise_set = set(cascade), set(noise)

    def dot_color(t: str) -> str:
        if reveal_roles:
            return "#b8442c" if t in cascade_set else "#9aa0a6"
        o = by_tag.get(t)
        return CATEGORY_COLORS.get(getattr(o, "category", "other"), "#9aa0a6")

    P = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'style="width:100%;height:auto;font-family:sans-serif">']
    # time axis + gridlines each second (capped so long windows stay clean)
    P.append(f'<line x1="{left}" y1="{top - 10}" x2="{left}" y2="{h - 26}" '
             f'stroke="#3a4250" stroke-width="1"/>')
    tick = max(1, int(span // 10) or 1)
    s = 0
    while s <= span + 1e-6:
        x = px(s)
        P.append(f'<line x1="{x:.1f}" y1="{top - 10}" x2="{x:.1f}" '
                 f'y2="{h - 26}" stroke="#2a3140" stroke-width="1"/>'
                 f'<text x="{x:.1f}" y="{h - 10}" text-anchor="middle" '
                 f'font-size="10" fill="#7a8694">+{s}s</text>')
        s += tick
    # sweep line while the sequence is playing
    if not reveal_roles and elapsed < window:
        x = px(min(elapsed, span))
        P.append(f'<line x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" '
                 f'y2="{h - 24}" stroke="#f4a259" stroke-width="2" '
                 f'stroke-dasharray="4 3"/>'
                 f'<text x="{x:.1f}" y="{top - 16}" text-anchor="middle" '
                 f'font-size="10" fill="#f4a259">now</text>')
    for i, t in enumerate(rows):
        y = top + i * rowh + rowh // 2
        x = px(timeline[t])
        o = by_tag.get(t)
        drw = ""
        if drawings_of:
            ds = drawings_of.get(t, [])
            drw = f" [{ds[0][-14:]}]" if ds else ""
        role = ("cascade" if t in cascade_set else
                "noise" if t in noise_set else "?")
        tip = (f"{t}{drw} · +{timeline[t]:.1f}s"
               + (f" · {role}" if reveal_roles else "")
               + (f" · {getattr(o, 'category', '')}" if o else ""))
        # connector from label to dot
        P.append(f'<line x1="{left}" y1="{y}" x2="{x:.1f}" y2="{y}" '
                 f'stroke="#2a3140" stroke-width="1"/>')
        if glow and t in glow:
            P.append(f'<circle cx="{x:.1f}" cy="{y}" r="12" fill="none" '
                     f'stroke="#f4d35e" stroke-width="2" opacity="0.85" '
                     f'stroke-dasharray="3 2"/>')
        if chatter and t in chatter:      # re-activations: hollow dots
            for _a in chatter[t]["alm"][1:]:
                if _a <= elapsed or reveal_roles:
                    P.append(f'<circle cx="{px(_a):.1f}" cy="{y}" r="4" '
                             f'fill="none" stroke="{dot_color(t)}" '
                             f'stroke-width="1.5" opacity="0.8">'
                             f'<title>{t} re-alarmed at +{_a:.0f}s '
                             f'(chatter)</title></circle>')
        ring = (' stroke="#f4d35e" stroke-width="2.5"'
                if reveal_roles and t == first_up and t in cascade_set else
                ' stroke="#f4a259" stroke-width="1.5"'
                if t == first_up and not reveal_roles else "")
        P.append(f'<circle cx="{x:.1f}" cy="{y}" r="7" '
                 f'fill="{dot_color(t)}"{ring}>'
                 f'<title>{_html.escape(tip)}</title></circle>')
        P.append(f'<text x="{left - 8}" y="{y + 4}" text-anchor="end" '
                 f'font-size="11" fill="#cfd6dd">{_html.escape(t)}</text>')
    # legend
    if reveal_roles:
        leg = [("#b8442c", "cascade of the fault"), ("#9aa0a6", "noise"),
               ("#f4d35e", "first-up (ringed)")]
    else:
        leg = [(CATEGORY_COLORS["input"], "input"),
               (CATEGORY_COLORS["logic"], "logic"),
               (CATEGORY_COLORS["output"], "output"),
               ("#f4a259", "first-up (ringed)")]
    if glow:
        leg.append(("#f4d35e", "⌾ referenced by the AI answer"))
    lx = left
    for c, lab in leg:
        P.append(f'<circle cx="{lx}" cy="16" r="6" fill="{c}"/>'
                 f'<text x="{lx + 11}" y="20" font-size="11" '
                 f'fill="#9aa4ae">{lab}</text>')
        lx += 12 + 8 * len(lab) + 30
    P.append("</svg>")
    return "".join(P)


def explains_bar_svg(briefs: list[dict], n_active: int, cap: int = 8,
                     w: int = 1100) -> str:
    """Horizontal bar chart of the situation-brief ranking: how many of the
    other active alarms each candidate root would explain. Same numbers as
    the text list — now comparable at a glance. Fault-blind by design."""
    import html as _html
    rows = briefs[:cap]
    if not rows:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>"
    denom = max(1, n_active - 1)
    left, right, rowh, top = 190, 60, 30, 12
    h = top + rowh * len(rows) + 10
    bw = w - left - right
    P = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'style="width:100%;height:auto;font-family:sans-serif">']
    for i, b in enumerate(rows):
        y = top + i * rowh
        n = len(b["explains"])
        bl = max(3, bw * n / denom)
        fill = "#b8442c" if i == 0 and n > 0 else "#5c81a6" if n > 0 else "#3a4250"
        tip = (f"{b['tag']} ({b.get('priority_label', '')}) explains {n} of "
               f"{denom} other active alarms")
        P.append(f'<text x="{left - 8}" y="{y + rowh / 2 + 4}" '
                 f'text-anchor="end" font-size="11" fill="#cfd6dd">'
                 f'{_html.escape(b["tag"])}</text>')
        P.append(f'<rect x="{left}" y="{y + 5}" width="{bl:.1f}" '
                 f'height="{rowh - 10}" rx="4" fill="{fill}">'
                 f'<title>{_html.escape(tip)}</title></rect>')
        P.append(f'<text x="{left + bl + 8:.1f}" y="{y + rowh / 2 + 4}" '
                 f'font-size="11" fill="#9aa4ae">{n}</text>')
    P.append("</svg>")
    return "".join(P)


def layered_cause_svg(graph: nx.DiGraph, center: str, active: list[str],
                      drawings_of: dict | None = None, max_depth: int = 4,
                      per_col: int = 12, glow: set | None = None,
                      w: int = 1100) -> str:
    """Readable cause map: ALARMED nodes only, laid out in columns by hop
    distance from the selected candidate (upstream left, downstream
    right), with arcs showing chains. Edges are the TRANSITIVE REDUCTION
    of reachability between shown nodes — an arc means "reaches, with no
    other shown alarm in between", and its tooltip tells the real hop
    count through unalarmed components (hand valves etc. that never ring).
    Far clearer than a spring hairball, and honest about what it hides.
    """
    import html as _html

    act = [a for a in active if a in graph]
    down = dict(nx.single_source_shortest_path_length(graph, center)) \
        if center in graph else {center: 0}
    up = dict(nx.single_source_shortest_path_length(graph.reverse(copy=False),
                                                    center)) \
        if center in graph else {}
    depth: dict[str, int] = {center: 0}
    for n in act:
        if n == center:
            continue
        d, u = down.get(n), up.get(n)
        if d is not None and d <= max_depth and (u is None or d <= u):
            depth[n] = d
        elif u is not None and u <= max_depth:
            depth[n] = -u
    cols: dict[int, list[str]] = {}
    trunc = 0
    for n, d in sorted(depth.items()):
        cols.setdefault(d, [])
        if len(cols[d]) < per_col:
            cols[d].append(n)
        else:
            trunc += 1
    shown = {n for ns in cols.values() for n in ns}

    # transitive reduction over reachability among shown nodes
    spl = {u: {v: l for v, l in
               nx.single_source_shortest_path_length(graph, u).items()
               if v in shown and v != u} for u in shown}
    edges = []
    for u in shown:
        for v, l in spl[u].items():
            if any(w in spl[u] and v in spl.get(w, {})
                   and spl[u][w] + spl[w][v] == l for w in shown
                   if w not in (u, v)):
                continue
            edges.append((u, v, l))

    xs = sorted(cols)
    colw = max(120, (w - 80) // max(len(xs), 1))
    h = 90 + per_col * 52
    pos = {}
    for ci, d in enumerate(xs):
        for ri, n in enumerate(cols[d]):
            pos[n] = (60 + ci * colw + colw // 2, 70 + ri * 52)

    def color(n):
        if n == center:
            return "#12233b"
        return "#b8442c" if depth[n] > 0 else "#2d7dd2"

    P = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'style="width:100%;height:auto;font-family:sans-serif">']
    for ci, d in enumerate(xs):
        label = ("selected" if d == 0 else
                 f"{abs(d)} hop{'s' if abs(d) > 1 else ''} "
                 f"{'downstream' if d > 0 else 'upstream'}")
        P.append(f'<text x="{60 + ci * colw + colw // 2}" y="30" '
                 f'text-anchor="middle" font-size="12" fill="#888">'
                 f'{label}</text>')
    for u, v, l in edges:
        (x1, y1), (x2, y2) = pos[u], pos[v]
        mid = (x1 + x2) / 2
        P.append(f'<path d="M{x1} {y1} Q{mid} {(y1 + y2) / 2 - 26} {x2} {y2}" '
                 f'fill="none" stroke="#9aa" stroke-width="1.6" opacity="0.7" '
                 f'marker-end="url(#ar)"><title>{u} → {v}: {l} hops '
                 f'(intermediates do not alarm)</title></path>')
    P.append('<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" '
             'markerWidth="6" markerHeight="6" orient="auto">'
             '<path d="M0 0L10 5L0 10z" fill="#9aa"/></marker></defs>')
    for n, (x, y) in pos.items():
        drw = ""
        if drawings_of:
            ds = drawings_of.get(n, [])
            drw = f" [{ds[0][-14:]}]" if ds else ""
        if glow and n in glow:
            P.append(f'<circle cx="{x}" cy="{y}" r="19" fill="none" '
                     f'stroke="#f4d35e" stroke-width="2" opacity="0.85" '
                     f'stroke-dasharray="3 2"/>')
        P.append(f'<g><circle cx="{x}" cy="{y}" r="14" fill="{color(n)}">'
                 f'<title>{_html.escape(n + drw)}</title></circle>'
                 f'<text x="{x}" y="{y - 20}" text-anchor="middle" '
                 f'font-size="10" fill="#ddd">{_html.escape(n)}</text></g>')
    if trunc:
        P.append(f'<text x="{w - 10}" y="{h - 8}" text-anchor="end" '
                 f'font-size="11" fill="#888">+{trunc} alarms outside '
                 f'the view (max {per_col} per column)</text>')
    P.append("</svg>")
    return "".join(P)

# ---------------------------------------------------------------------------
# Selvtest for tidsbeviset — deterministisk, ingen data, ingen nettverk
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """Regresjonsvakt for de to reglene i candidate_brief(timeline=...).

    Bygger en liten kjede A->B->C->D der D OGSÅ er strukturelt nedstrøms for
    en annen kjede, og sjekker at tid gjenoppretter det strukturen mister —
    uten å fragmentere en vanlig kaskade.
    """
    from models.engineering_object import EngineeringObject as E

    g = nx.DiGraph()
    chain = ["27-PT4801", "27-PIC4801", "27-PV4801", "27-XV4801"]
    for a, b in zip(chain, chain[1:]):
        g.add_edge(a, b)
    # feil B sin rot ligger strukturelt NEDSTRØMS feil A sin kjede
    g.add_edge("27-XV4801", "13-PT2201")
    g.add_edge("13-PT2201", "13-PIC2201")
    by_tag = {t: E.from_tag(t, "SCD") for t in list(g.nodes)}
    active = list(g.nodes)

    # 1) én kaskade, jevn spacing -> nøyaktig én kandidat, ingen fragmentering
    single = {t: round(i * 2.5, 2) for i, t in enumerate(
        ["27-PT4801", "27-PIC4801", "27-PV4801", "27-XV4801",
         "13-PT2201", "13-PIC2201"])}
    b1 = candidate_brief(g, by_tag, active, timeline=single, cluster_gap=5.0)
    # 2) feil B starter LANGT etter -> skal IKKE bli kandidat: sen ankomst
    #    alene er ikke bevis, og 'late'-regelen ble fjernet etter måling
    late = dict(single)
    late["13-PT2201"], late["13-PIC2201"] = 200.0, 202.5
    b2 = candidate_brief(g, by_tag, active, timeline=late, cluster_gap=5.0)
    # 3) feil B ringte FØR sine påståtte årsaker -> kan ikke være konsekvens
    early = {"27-PT4801": 100.0, "27-PIC4801": 102.5, "27-PV4801": 105.0,
             "27-XV4801": 107.5, "13-PT2201": 0.0, "13-PIC2201": 2.5}
    b3 = candidate_brief(g, by_tag, active, timeline=early, cluster_gap=5.0)
    # 4) uten timeline -> uendret oppførsel
    b0 = candidate_brief(g, by_tag, active)

    def tags(bs):
        return [b["tag"] for b in bs]

    checks = [
        ("uten tid: én strukturell kandidat", tags(b0) == ["27-PT4801"]),
        ("jevn kaskade fragmenteres ikke", tags(b1) == ["27-PT4801"]),
        # sen ankomst alene promoterer IKKE — 'late' ble fjernet fordi den
        # over 360 enkeltfeil-scenarioer flagget 804 ekte kaskadealarmer og
        # ikke bidro til dobbeltfeil-gevinsten
        ("sen ankomst alene gir ingen ny kandidat",
         "13-PT2201" not in tags(b2)),
        ("ingen kandidat merkes 'late'",
         not any(b.get("detached") == "late" for b in b1 + b2 + b3)),
        ("alarm før sin årsak blir kandidat", "13-PT2201" in tags(b3)),
        ("den merkes 'precedes' (bevis, ikke terskel)",
         any(b.get("detached") == "precedes"
             for b in b3 if b["tag"] == "13-PT2201")),
        ("strukturell rot beholdes i alle tilfeller",
         all("27-PT4801" in tags(b) for b in (b1, b2, b3))),
        ("strukturell rangering leder fortsatt",
         tags(b2)[0] == "27-PT4801"),
    ]
    ok = True
    for name, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok &= passed
    return 0 if ok else 1


if __name__ == "__main__":                       # sti satt øverst
    sys.exit(_selftest())
