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
        out.append(entry)
    # Ranking: the STRUCTURAL root signal leads — the candidate that explains
    # the most other active alarms — because that is what actually points at
    # the origin. Priority (severity) is the tiebreaker, so among equally
    # explanatory roots the more critical one surfaces first. This ordering
    # deliberately does NOT let a high-priority but independent noise alarm
    # (explains 0) leapfrog the true cascade root. The board (urgency) is
    # priority-sorted; the candidate list (likelihood of being the origin) is
    # explains-first — two different questions, two different orders.
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
                w: int = 1100) -> str:
    """Render the parsed verification plan as a numbered step chain:
    circles 1→n connected left-to-right, the step's register tag(s)
    beneath, colored by tag priority (P1 red … P4 grey), full step text
    on hover. Everything shown is parsed from the answer and verified
    against the register — the figure cannot contain a hallucinated tag."""
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
        P.append(f'<g><circle cx="{cx}" cy="{cy}" r="20" fill="{fill}">'
                 f'<title>{_html.escape(tip)}</title></circle>'
                 f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" '
                 f'font-size="14" font-weight="bold" fill="#fff">'
                 f'{s["n"]}</text></g>')
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

def alarm_timeline_svg(timeline: dict, shown: list[str], by_tag,
                       cascade: list[str], noise: list[str],
                       elapsed: float, window: float,
                       reveal_roles: bool = False,
                       first_up: str | None = None,
                       drawings_of: dict | None = None,
                       glow: set | None = None,
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
        label = ("valgt" if d == 0 else
                 f"{abs(d)} hopp {'nedstrøms' if d > 0 else 'oppstrøms'}")
        P.append(f'<text x="{60 + ci * colw + colw // 2}" y="30" '
                 f'text-anchor="middle" font-size="12" fill="#888">'
                 f'{label}</text>')
    for u, v, l in edges:
        (x1, y1), (x2, y2) = pos[u], pos[v]
        mid = (x1 + x2) / 2
        P.append(f'<path d="M{x1} {y1} Q{mid} {(y1 + y2) / 2 - 26} {x2} {y2}" '
                 f'fill="none" stroke="#9aa" stroke-width="1.6" opacity="0.7" '
                 f'marker-end="url(#ar)"><title>{u} → {v}: {l} hopp '
                 f'(mellomledd alarmerer ikke)</title></path>')
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
                 f'font-size="11" fill="#888">+{trunc} alarmer utenfor '
                 f'visningen (maks {per_col} per kolonne)</text>')
    P.append("</svg>")
    return "".join(P)