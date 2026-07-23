"""
src/kontrollrom.py  —  control-room decision-support prototype (alarm shower)

Registered by src/app.py via st.navigation:
    st.Page("kontrollrom.py", title="Control Room Assistant", icon="🎛️"),

The realistic incident shape: ALL alarms fire at once — the hidden fault's
full cascade shuffled together with a couple of unrelated noise alarms.
The assistant produces a structural brief per candidate root (what each
would explain, failure modes, cross-checks, barriers) WITHOUT declaring a
winner; the operator weighs the evidence and commits to an answer, then
gets a debrief distinguishing root, symptom and noise.

Honest scope (also stated on screen): synthetic scenario, structural
reachability, decision SUPPORT. The engine (analysis/control_room.py) is
data-source-agnostic: swap the scenario generator for a live alarm feed and
the same brief becomes operational support — that swap is the pilot step.
"""
from __future__ import annotations
import os
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from dotenv import load_dotenv
load_dotenv()  # explicit: the GEMINI_API_KEY gate below depends on .env,
               # and should not rely on another import loading it
import streamlit.components.v1 as components

from config import PID_DIR, CATEGORY_COLORS
from analysis.build_dependency_graph import interactive_svg
from analysis.hazop_dexpi import load_dexpi_model
from analysis.analyze_scd import failure_map
from analysis.control_room import (alarm_shower, alarm_timeline_svg,
                                   candidate_brief, explains_bar_svg,
                                   scenario_order, shower_debrief,
                                   situation_brief)
from analysis.alarm_priority import (alarm_semantics, DIR_ARROW,
                                     priority_sort_key)
from ai.operator_brief import operator_brief, alarm_response_sheet
from analysis.cause_effect import (load_ce, validate_ce, ce_lines_for,
                                   designed_response_check)

RAW_DIR = Path(PID_DIR).parent


def find_dexpi() -> dict:
    out = {}
    for x in sorted(RAW_DIR.rglob("*.DGN.xml")):
        m = re.search(r"H[A-Z](\d{2})", x.stem)
        out[f"{m.group(1) if m else '??'} · {x.stem.replace('.DGN', '')}"] = x
    return out


@st.cache_resource(show_spinner="Reading DEXPI model…")
def load(xml: str, mtime: float) -> dict:
    m = load_dexpi_model(Path(xml))
    allo, g = m["objects"], m["tag_graph"]
    return {"g": g, "by_tag": {o.tag: o for o in allo},
            "fmap": failure_map(g, allo)}


from ui import prio_badge as _ui_prio_badge, chips as _ui_chips, page_header


def prio_badge(tag, by_tag):
    """Design-system P1..P4 badge (delegates to ui.prio_badge). Keeps the
    (tag, by_tag) signature so existing call sites are untouched."""
    o = by_tag.get(tag)
    if not o:
        return ""
    return _ui_prio_badge(o.priority, o.alarm_direction)


def chips(tags, by_tag):
    """Design-system tag chips (delegates to ui.chips)."""
    return _ui_chips(tags, by_tag)


# ---- setup ------------------------------------------------------------------
files = find_dexpi()
st.sidebar.title("Control Room Assistant")
if not files:
    st.error("No DEXPI XML found under data/raw/.")
    st.stop()

PLANT = "🏭 Entire plant (all drawings)"


@st.cache_resource(show_spinner="Stitching plant model together…")
def load_plant() -> dict:
    from analysis.plant_model import build_plant_model
    Mp = build_plant_model(RAW_DIR)
    return {"g": Mp["graph"], "by_tag": {o.tag: o for o in Mp["objects"]},
            "fmap": failure_map(Mp["graph"], Mp["objects"]),
            "drawings_of": Mp["drawings_of"], "stats": Mp["stats"]}


choice = st.sidebar.selectbox("Source", [PLANT] + list(files))
plant_mode = choice == PLANT
if plant_mode:
    M = load_plant()
    st.sidebar.caption(f"{M['stats']['drawings']} drawings · "
                       f"{M['stats']['tags']} tags · "
                       f"{M['stats']['line_stitches']} line stitches · "
                       f"{M['stats']['cross_edges']} cross edges")
else:
    M = load(str(files[choice]), files[choice].stat().st_mtime)
g, by_tag, fmap = M["g"], M["by_tag"], M["fmap"]
drawings_of = M.get("drawings_of", {})

# ---- designed cause & effect from the SCD (manual CSV, validated) ----------
CE = validate_ce(load_ce(RAW_DIR.parent / "cause_effect"
                         if (RAW_DIR.parent / "cause_effect").exists()
                         else Path("data/cause_effect")), by_tag)
ce_index = CE["index"]
if CE["stats"]["rows"]:
    _s = CE["stats"]
    st.sidebar.caption(
        f"C&E from SCD: {_s['resolved']}/{_s['rows']} rows connected, "
        f"{_s['verified']} verified"
        + (f" · unknown tags: {', '.join(_s['unknown_tags'][:3])}"
           if _s["unknown_tags"] else ""))


def _drw(tag: str) -> str:
    ds = drawings_of.get(tag, [])
    return f" `[{ds[0][-14:]}]`" if ds else ""

from analysis.control_room import alarm_capable
candidates = sorted((n for n in g.nodes
                     if alarm_capable(by_tag.get(n))
                     and len(scenario_order(g, n)) >= 4),
                    key=lambda n: -len(scenario_order(g, n)))
if not candidates:
    st.warning("This drawing has too little connectivity for a scenario — "
               "please select another (HO27-002 is recommended).")
    st.stop()

st.sidebar.divider()
fault_pick = st.sidebar.selectbox("Fault source (hidden during run)",
                                  ["(random)"] + candidates)
n_noise = st.sidebar.slider("Noise alarms", 0, 4, 2,
                            help="Unrelated alarms mixed into the shower — "
                                 "makes the exercise realistic.")
alarm_step = st.sidebar.slider(
    "Seconds between alarms", 0.5, 10.0, 2.5, 0.5,
    help="How fast the cascade rolls in. Low = fast demo, high = more time "
         "to read each alarm. Applies to the next scenario you start.")
demo_mode = st.sidebar.toggle(
    "🔒 Demo mode (reproducible)",
    help="Fixed seed: the same fault source yields the exact same scenario every time. "
         "Allows chat responses to be pre-cached the night before — and ensures the "
         "demo works offline.")
if st.sidebar.button("▶ New scenario"):
    fault = random.choice(candidates[:15]) if fault_pick == "(random)" \
        else fault_pick
    shower = alarm_shower(g, fault, noise=n_noise,
                          seed=42 if demo_mode else random.randrange(10**6),
                          by_tag=by_tag, step=alarm_step)
    st.session_state["cr"] = {"drawing": choice, "fault": fault,
                              "shower": shower, "chosen": None,
                              "play_start": time.time(), "playing": True}

page_header("Control Room Assistant — Alarm Shower",
            f"source: {'entire plant (17 drawings)' if plant_mode else choice}"
            f" · synthetic scenario · decision support, not a process model")
st.caption("The alarms arrive AS A SEQUENCE over a few seconds: the cascade of a hidden "
           "fault in causal order, mixed with unrelated "
           "noise alarms. The assistant provides a structural brief per candidate — "
           "without declaring a winner. YOU weigh the evidence and determine the most "
           "likely cause.")

S = st.session_state.get("cr")
if not S or S["drawing"] != choice:
    st.markdown("### How to play")
    s1, s2, s3 = st.columns(3)
    s1.markdown("**1 · Start** \nSelect a source and press «▶ New scenario» in "
                "the sidebar. Select «(random)» — that way you won't know "
                "the answer either. «🏭 Entire plant» generates cascades across "
                "drawings.")
    s2.markdown("**2 · Evaluate** \nThe alarms arrive in sequence over a few "
                "seconds — note which one came FIRST. Read the assistant's "
                "brief per candidate and use the connectivity tab to see "
                "the evidence visually.")
    s3.markdown("**3 · Decide** \nPoint to the most likely cause and confirm. "
                "The debrief tells you whether you hit the source, a symptom, or "
                "noise — and can calculate the physical consequence (NeqSim).")
    st.stop()

all_alarms = S["shower"]["alarms"]
timeline = S["shower"].get("timeline", {})
window = float(S["shower"].get("window", 0.0))
done = S["chosen"] is not None

# progressive reveal: show only alarms whose timeline offset has elapsed.
if S.get("playing") and not done:
    elapsed = time.time() - S.get("play_start", time.time())
    if elapsed >= window:                 # sequence finished -> lock to full
        S["playing"] = False
        elapsed = window + 1.0
else:
    elapsed = window + 1.0
active = [a for a in all_alarms if timeline.get(a, 0.0) <= elapsed] or all_alarms[:1]
active_sorted = sorted(active, key=lambda t: priority_sort_key(t, by_tag))
playing = bool(S.get("playing")) and not done and elapsed < window

briefs = candidate_brief(g, by_tag, active)   # på det som er avslørt så langt

# tags the LATEST AI answer referenced (verified only) — drawn as gold
# rings on the timeline and cause map so the agent's claims are visibly
# anchored in the model. Empty set until the assistant has answered.
from analysis.control_room import canonicalize_tags as _canon
_qa_hist_key = f"qa_hist_{S['fault']}_{len(S['shower']['alarms'])}"
_qa_prev = st.session_state.get(_qa_hist_key) or []
qa_glow = (set(_canon(_qa_prev[-1][2]["verified"], by_tag).values())
           if _qa_prev else set())


m1, m2, m3, m4 = st.columns(4)
m1.metric("Concurrent alarms", len(active),
          help="Only alarm-CAPABLE functions trigger (instruments, switches, "
               "controllers, safety functions) — a manual valve has no "
               "alarm. Total structurally exposed: see next figure.")
m1.caption(f"exposed: {S['shower'].get('exposed', '?')} components")
m2.metric("Candidate roots", len(briefs),
          help="Alarms no other active alarm can explain — independent "
               "roots in the graph (cycle groups count as one).")
if plant_mode:
    _drawn = sorted({d for t in active for d in drawings_of.get(t, [])})
    m3.metric("Drawings affected", len(_drawn),
              help="The cascade crosses drawing boundaries via line stitches — "
                   "impossible to see from a single sheet.")
else:
    m3.metric("Source", "1 drawing")
m4.metric("Status", "✅ Answered" if done else "⏳ In progress")

tab_sit, tab_graf, tab_chat = st.tabs(
    ["🔔 Situation & Decision", "🕸️ Connectivity", "💬 Ask the Assistant"])

with tab_sit:
    if playing:
        pc1, pc2 = st.columns([4, 1])
        pc1.caption(f"⏱️ Alarms are rolling in … **{len(active)}/{len(all_alarms)}** "
                    f"shown. First alarm: **{S['shower'].get('first_up', '?')}**.")
        if pc2.button("⏭ Show all now"):
            S["playing"] = False
            st.rerun()
    # ---- neutral opening situation brief (fault-blind) -------------------------
    sb = situation_brief(active, briefs, drawings_of if plant_mode else None)
    st.subheader("🧭 Situation Brief")
    head = (f"**{sb['n_alarms']} concurrent alarms** &nbsp;·&nbsp; "
            f"**{sb['n_candidates']} independent candidate roots**")
    if plant_mode and sb["n_drawings"]:
        head += f" &nbsp;·&nbsp; **{sb['n_drawings']} drawings affected**"
    st.markdown(head)
    st.caption("Ranked by how many other active alarms each candidate "
               "would explain — the strongest structural clue. "
               "The assistant does NOT know which alarm is the cause and declares "
               "no winner; weighing the evidence is your job.")
    _fu = S["shower"].get("first_up")
    if _fu:
        st.caption(f"⏱️ First alarm in sequence: **{_fu}** — arrived first, often "
                   "(but not always) closest to the root. An observable clue, "
                   "not the absolute answer.")
    _cap = 8
    for i, r in enumerate(sb["ranking"][:_cap], 1):
        st.markdown(
            f"**{i}.** {prio_badge(r['tag'], by_tag)} &nbsp; **{r['tag']}** "
            f"— explains **{r['explains_count']}** other active alarms"
            + (_drw(r["tag"]) if plant_mode else ""),
            unsafe_allow_html=True)
    if len(sb["ranking"]) > _cap:
        st.caption(f"+ {len(sb['ranking']) - _cap} more candidates "
                   f"(explains fewer or none).")
    components.html(
        f"<div style='background:#141820;border-radius:10px;padding:8px'>"
        f"{explains_bar_svg(briefs, len(active), cap=_cap)}</div>",
        height=min(340, 60 + 30 * min(len(briefs), _cap)), scrolling=False)
    if sb["any_none"]:
        st.caption("Candidates explaining 0 can be independent/isolated "
                   "alarms — or noise. The graph displays structural reachability, "
                   "not process cause; confirm against the drawing and operating mode.")
    st.divider()

    # ---- arrival timeline -------------------------------------------------------
    with st.expander("⏱️ Arrival timeline — when each alarm rang", expanded=True):
        st.caption("One row per alarm in arrival order, dot at its +t offset. "
                   "While the sequence rolls, the orange sweep line marks «now». "
                   "Colors = tag category (fault-blind); after you answer, the "
                   "dots are recolored by ROLE — cascade vs. noise — so the "
                   "debrief shows the shape of the incident at a glance.")
        components.html(
            f"<div style='background:#141820;border-radius:10px;padding:8px'>"
            f"{alarm_timeline_svg(timeline, active, by_tag, S['shower']['cascade'], S['shower']['noise'], elapsed, window, reveal_roles=done, first_up=S['shower'].get('first_up'), drawings_of=drawings_of or None, glow=qa_glow)}"
            f"</div>",
            height=min(620, 110 + 30 * len(active)), scrolling=True)

    left, right = st.columns([1, 1.5])

    # ---- alarm board -------------------------------------------------------------
    with left:
        st.subheader(f"🔔 Alarm Board — {len(active)} concurrent")
        sort_time = st.toggle(
            "Sort by arrival (first-up at the top)", value=False,
            help="Off = priority (P1 at top). On = the order the alarms arrived "
                 "— the first-up clue.")
        st.caption("**+t** = seconds after the first alarm. Priority/direction "
                   "is derived from the tag — a proxy, not the configured "
                   "alarm priority.")
        board = (sorted(active, key=lambda t: (timeline.get(t, 0.0), t))
                 if sort_time else active_sorted)
        for a in board:
            cat = by_tag[a].category if a in by_tag else "?"
            ts = timeline.get(a)
            t_chip = (f"<span style='font-family:IBM Plex Mono,monospace;"
                      f"font-size:11px;color:#5c6f7c;background:#f0f2f4;"
                      f"border-radius:4px;padding:1px 6px'>+{ts:.1f}s</span>"
                      if ts is not None else "")
            st.markdown(
                f"🔴 **{a}** &nbsp; {prio_badge(a, by_tag)} &nbsp; {t_chip} "
                f"&nbsp; <code>{cat}</code>"
                + (_drw(a) if plant_mode else ""),
                unsafe_allow_html=True)
        if not done:
            st.divider()
            pick = st.selectbox("Most likely cause", ["(select)"] + active_sorted)
            if pick != "(select)" and st.button(f"✅ Confirm: {pick} is the cause"):
                S["chosen"] = pick
                st.rerun()

    # ---- assistant brief ----------------------------------------------------------
    with right:
        st.subheader("🤝 Assistant's Brief — candidates and evidence")
        st.caption("Candidates = alarms no other active alarm can explain "
                   "(independent roots in the graph). The evidence below is structural; "
                   "weighing it is your job.")
        for b in briefs:
            n_exp = len(b["explains"])
            plab = b.get("priority_label", "")
            with st.expander(f"**{b['tag']}** · {plab} — would explain "
                             f"{n_exp} of the other alarms",
                             expanded=(len(briefs) <= 3)):
                if b["tag"] in fmap:
                    st.code(alarm_response_sheet(b["tag"], fmap[b["tag"]],
                                                 by_tag),
                            language="text")
                _ce = ce_lines_for(b["tag"], ce_index)
                if _ce:
                    st.caption("**Designed logic (SCD C&E)** — what the sheet "
                               "says should happen, not just what is connected:")
                    for line in _ce:
                        st.markdown(f"&nbsp;&nbsp;⚙️ `{line}`",
                                    unsafe_allow_html=True)
                if b.get("group"):
                    st.caption(f"⭕ Structurally indistinguishable (same cycle via "
                               f"drawing stitches): {', '.join(b['group'][:8])}"
                               + (" …" if len(b["group"]) > 8 else ""))
                if b["explains"]:
                    st.caption("Explains these active alarms as consequences:")
                    st.markdown(chips(b["explains"], by_tag),
                                unsafe_allow_html=True)
                ch = b["checks"]
                if ch["loop_mates"]:
                    st.caption("Cross-check redundant measurements:")
                    st.markdown(chips(ch["loop_mates"], by_tag),
                                unsafe_allow_html=True)
                if ch["upstream_sensors"]:
                    st.caption("Verify upstream:")
                    st.markdown(chips(ch["upstream_sensors"], by_tag),
                                unsafe_allow_html=True)
                if b["barriers"]:
                    st.caption("Barriers in the chain:")
                    st.markdown(chips(b["barriers"], by_tag),
                                unsafe_allow_html=True)
        st.caption("The graph displays structural reachability, not process consequence — "
                   "confirm against drawing and operating mode.")

    # ---- debrief -------------------------------------------------------------------
    if done:
        st.divider()
        st.subheader("📋 Debrief")
        fault_group = set()
        for b in briefs:
            grp = {b["tag"]} | set(b.get("group", []))
            if S["fault"] in grp:
                fault_group = grp
        if plant_mode and S["chosen"] in fault_group and S["chosen"] != S["fault"]:
            st.write(f"• Actual fault source: {S['fault']} — your choice "
                     f"({S['chosen']}) lies in the SAME cycle across the drawing stitches "
                     f"and is structurally indistinguishable from the source. Considered "
                     f"the correct group; physical verification must separate them — precisely "
                     f"because direction across a stitch is not provided in the delivery.")
            for line in shower_debrief(S["fault"], S["chosen"], S["shower"]["noise"],
                                       len(active))[-1:]:
                st.write("• " + line)
        else:
            for line in shower_debrief(S["fault"], S["chosen"], S["shower"]["noise"],
                                       len(active)):
                st.write("• " + line)
        if plant_mode:
            drawn = sorted({d for t in active for d in drawings_of.get(t, [])})
            st.write(f"• The cascade affected **{len(drawn)} drawings**: "
                     + ", ".join(d[-14:] for d in drawn)
                     + " — impossible to see from a single sheet, possible because the "
                       "delivery is structured and stitchable.")
        _dr = designed_response_check(S["fault"], ce_index, active)
        if _dr:
            st.write("• **Designed response (SCD C&E) for the fault source:**")
            for d in _dr:
                mk = "✅ triggered" if d["observed"] else "⬜ did not trigger in scenario"
                uv = "" if d["verified"] else " *(unverified row)*"
                st.write(f"&nbsp;&nbsp;&nbsp;⚙️ {S['fault']} → {d['effect']}: "
                         f"{d['function']} — {mk}{uv}")
            st.caption("Compares the sheet's designed actions with the alarms "
                       "that actually arrived — alignment strengthens the diagnosis, "
                       "deviation is a finding in itself.")
        with st.expander("🧪 Physical consequence of your choice (NeqSim)"):
            st.caption("Links the decision to physics: what is structurally isolated "
                       "if the component you pointed to actually fails/closes — and "
                       "what is the hydrate risk in the isolated segment? "
                       "Simplified illustration (example pressure, assumed "
                       "fluid mapping) — see reservations in the simulation module.")
            cons_drawing = (drawings_of.get(S["chosen"], [None])[0] if plant_mode
                            else str(files[choice].stem).replace(".DGN", ""))
            if cons_drawing is None:
                st.caption("Could not find the drawing for the selected component.")
            elif st.button("Calculate consequence", key="neqsim_cons"):
                from analysis.neqsim_seam import consequence_for
                with st.spinner("Running fault simulation + NeqSim…"):
                    r = consequence_for(cons_drawing, S["chosen"])
                st.write(r["summary"])
                if r["affected"]:
                    st.markdown(chips(r["affected"][:20], by_tag),
                                unsafe_allow_html=True)
                if r["log"].strip():
                    st.code(r["log"].strip()[-1500:], language="text")

        if st.button("↺ New scenario"):
            del st.session_state["cr"]
            st.rerun()


with tab_graf:
    # ---- connectivity graph ---------------------------------------------------------
    st.subheader("🕸️ Connectivity — visually evaluate candidates")
    st.caption("Select a candidate and view its chains against the alarm picture: does the "
               "red downstream cone cover the alarms on the board, or are many "
               "left out? The source explains the most; a symptom and a noise alarm "
               "cover little. The same evidence as in the brief — now visible.")
    cand_tags = [b["tag"] for b in briefs]
    hl_pick = st.selectbox("Highlight candidate (or other alarm)",
                           cand_tags + [t for t in sorted(active)
                                        if t not in cand_tags])
    he = fmap.get(hl_pick)
    highlight = ({"sel": hl_pick, "down": he["downstream"], "up": he["upstream"]}
                 if he else None)
    g_view = g
    if plant_mode:
        keep = set(active) | {hl_pick}
        if he:
            keep |= set(he["downstream"]) | set(he["upstream"])
        g_view = g.subgraph(keep).copy()
        st.caption(f"Plant mode: shows the subgraph around the alarm scenario "
                   f"({g_view.number_of_nodes()} of {g.number_of_nodes()} tags).")
    st.markdown(
        f"Highlighting **{hl_pick}** &nbsp; "
        f"<span style='color:#12233b'>■ selected</span> &nbsp; "
        f"<span style='color:#b8442c'>■ downstream (consequence)</span> &nbsp; "
        f"<span style='color:#2d7dd2'>■ upstream (possible cause)</span>",
        unsafe_allow_html=True)
    from analysis.control_room import layered_cause_svg
    st.caption("Cause map: only ALARMED nodes, in columns by distance "
               "from the selected candidate. An arrow means «reaches, without another alarm "
               "in between» — hover to see actual hop count through "
               "non-alarming components (manual valves, etc.).")
    components.html(
        f"<div style='background:#141820;border-radius:10px;padding:8px'>"
        f"{layered_cause_svg(g, hl_pick, active, drawings_of or None, glow=qa_glow)}</div>",
        height=760, scrolling=True)
    with st.expander("Show raw subgraph (spring layout, all intermediates)"):
        components.html(
            f"<div style='font-family:sans-serif'>{interactive_svg(g_view, highlight=highlight)}</div>",
            height=560, scrolling=False)


with tab_chat:
    # ---- optional grounded Q&A -----------------------------------------------------
    if os.getenv("GEMINI_API_KEY"):
        with st.expander("💬 Ask the Assistant (Gemini, grounded in the model)",
                         expanded=bool(st.session_state.get("qa_hist"))):
            from analysis.control_room import audit_answer_tags

            def _answer_visuals(ans_text: str, audit: dict,
                                cached: bool = False) -> None:
                """Deterministic figures parsed FROM the answer — the model
                never draws; we render only tags verified in the register."""
                from analysis.control_room import (agent_trace_svg,
                                                   answer_coverage_svg,
                                                   parse_verification_plan,
                                                   qa_plan_svg)
                n_ce = sum(len(ce_lines_for(b["tag"], ce_index, 3))
                           for b in briefs)
                top = briefs[0] if briefs else None
                components.html(
                    f"<div style='background:#141820;border-radius:10px;"
                    f"padding:8px'>"
                    f"{agent_trace_svg(len(active), len(briefs), top and top['tag'], len(top['explains']) if top else 0, n_ce, len(_qa_context()), len(audit['verified']), len(audit['suspect']), cached=cached)}"
                    f"</div>", height=165, scrolling=False)
                steps = parse_verification_plan(ans_text, by_tag)
                if steps:
                    st.caption("📐 Verification plan as a figure (parsed from "
                               "the answer, tags verified):")
                    components.html(
                        f"<div style='background:#141820;border-radius:10px;"
                        f"padding:8px'>"
                        f"{qa_plan_svg(steps, by_tag, active)}</div>",
                        height=185, scrolling=False)
                if audit["verified"] or audit["suspect"]:
                    with st.expander("🗺️ Answer coverage of the alarm board"):
                        components.html(
                            f"<div style='background:#141820;border-radius:"
                            f"10px;padding:8px'>"
                            f"{answer_coverage_svg(active_sorted, audit['verified'], audit['suspect'], by_tag)}"
                            f"</div>",
                            height=80 + 34 * (1 + (len(active) - 1) // 9)
                            + (34 if audit["suspect"] else 0),
                            scrolling=False)

            # conversation memory per scenario — resets when a new scenario starts
            hist_key = f"qa_hist_{S['fault']}_{len(S['shower']['alarms'])}"
            hist = st.session_state.setdefault(hist_key, [])
            st.session_state["qa_hist"] = hist

            def _pa(t: str) -> str:
                s = alarm_semantics(by_tag[t].type_code) if t in by_tag else {}
                arr = ("▲" if s.get("direction") == "high"
                       else "▼" if s.get("direction") == "low" else "")
                return f"{t}[P{s.get('priority', '?')}{arr}]"

            def _qa_context() -> str:
                head = ", ".join(_pa(t) for t in active_sorted[:40])
                lines = [f"ACTIVE ALARMS ({len(active)}), priority-sorted "
                         f"(P1 highest, ▲ high / ▼ low): {head}"
                         + (" …" if len(active) > 40 else "")]
                for b in briefs:
                    fm = "; ".join(fmap.get(b["tag"], {}).get("modes", [])[:3])
                    sem = (alarm_semantics(by_tag[b["tag"]].type_code)
                           if b["tag"] in by_tag else {})
                    drw = (f" on drawing {drawings_of.get(b['tag'], ['?'])[0]}"
                           if plant_mode else "")
                    grp = (f"; cycle-group: {', '.join(b['group'][:5])}"
                           if b.get("group") else "")
                    lines.append(
                        f"- CANDIDATE {b['tag']}{drw}: "
                        f"{b.get('priority_label', 'P?')}, direction "
                        f"{sem.get('direction') or 'n/a'}, expected response "
                        f"{sem.get('response_time', 'n/a')}; explains "
                        f"{len(b['explains'])} active alarms; failure modes: "
                        f"{fm or 'n/a'}; barriers: "
                        f"{', '.join(b['barriers']) or 'none'}; cross-checks: "
                        f"{b['checks']}{grp}")
                    for ce_line in ce_lines_for(b["tag"], ce_index, 3):
                        lines.append(f"  DESIGNED C&E (from SCD sheet): {ce_line}")
                return "\n".join(lines)

            # display history as chat
            for q_prev, a_prev, audit_prev in hist:
                with st.chat_message("user"):
                    st.write(q_prev)
                with st.chat_message("assistant"):
                    st.markdown(a_prev)
                    _answer_visuals(a_prev, audit_prev,
                                    cached="🗂" in q_prev)
                    if audit_prev["suspect"]:
                        st.caption("Tag check: ✅ "
                                   + ", ".join(audit_prev["verified"]) + " · ❓ **"
                                   + ", ".join(audit_prev["suspect"])
                                   + "** — not found in the model, verify!")
                    elif audit_prev["verified"]:
                        st.caption("Tag check: ✅ all referenced tags exist in the "
                                   "model (" 
                                   + ", ".join(audit_prev["verified"]) + ")")


            # suggested questions (demo safeguard) + free text
            sugg = ["Give me a verification plan for the alarms",
                    "What speaks for and against each candidate?",
                    "What should I hold off on doing, and why?"]
            cols = st.columns(len(sugg))
            clicked = None
            for c, txt in zip(cols, sugg):
                if c.button(txt, key=f"sugg_{txt[:12]}_{hist_key}"):
                    clicked = txt
            typed = st.text_input("Or ask your own question",
                                  key=f"qa_in_{hist_key}")
            q = clicked or (typed if st.button("Send", key=f"qa_send_{hist_key}")
                            else None)

            if q:
                history_txt = "\n".join(
                    f"OPERATOR: {hq}\nASSISTANT: {ha}" for hq, ha, _ in hist[-3:])
                prompt = (
                    "You are a control-room decision-support assistant during an "
                    "alarm flood. Answer in ENGLISH. Use ONLY the facts and "
                    "tags below — NEVER invent a tag; general process knowledge "
                    "may be used if marked '(general)'.\n"
                    "Weight candidates and actions by the PRIORITY shown "
                    "(P1 = critical/trip highest … P4 lowest; ▲ high, ▼ low). "
                    "Priority is DERIVED FROM THE TAG, not the configured alarm "
                    "priority — treat it as a proxy and say so if it matters.\n"
                    "Your job is to turn the evidence into ACTION, not to "
                    "restate it. Structure the answer as:\n"
                    "1. WEIGHING EVIDENCE — which candidate the structural evidence "
                    "favours and WHY (explains-counts, failure modes, position), "
                    "and what would speak against it. You SHOULD take a stand; "
                    "it is a structural assessment, not the verdict.\n"
                    "2. VERIFICATION PLAN — 3-5 numbered steps in priority "
                    "order. Each step: a concrete check tied to a REAL tag from "
                    "the facts, what reading/outcome to expect if the favoured "
                    "candidate is true, and what the opposite outcome would "
                    "imply.\n"
                    "3. DO NOT ACT YET — one line on actions to hold off on "
                    "and why.\n"
                    "Be concrete and terse. End with: 'Structural "
                    "decision support — operator's judgment prevails.'\n\n"
                    f"FACTS:\n{_qa_context()}\n\n"
                    + (f"CONVERSATION SO FAR:\n{history_txt}\n\n" if hist else "")
                    + f"QUESTION: {q}")
                from ai.ai_cache import load_qa, save_qa
                cached_qa = load_qa(prompt)
                if cached_qa:
                    ans = cached_qa["answer"]
                    hist.append((f"{q}  \n*(🗂️ cached response, "
                                 f"{cached_qa['saved_at']})*", ans,
                                 audit_answer_tags(ans, by_tag)))
                    st.rerun()
                else:
                    try:
                        from ai.gemini_client import generate
                        with st.spinner("Asking the model…"):
                            ans = generate(prompt).text
                        save_qa(prompt, q, ans)
                        hist.append((q, ans, audit_answer_tags(ans, by_tag)))
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Gemini call failed: {e}")

        st.divider()
        with st.expander("Show prompt template and current facts (read-only)"):
            st.caption("Same standard as the HAZOP page: the template is fixed — "
                       "the structure (WEIGHING EVIDENCE / VERIFICATION PLAN / DO NOT ACT "
                       "YET), the tag ban, and the English response cannot be "
                       "overridden. The FACTS block below is built deterministically "
                       "from the model for each alarm scenario.")
            st.code(
                "You are a control-room decision-support assistant during an "
                "alarm flood. Answer in ENGLISH. Use ONLY the facts and "
                "tags below — NEVER invent a tag; general process knowledge "
                "may be used if marked '(general)'.\n"
                "Weight candidates and actions by the PRIORITY shown "
                "(P1 highest … P4 lowest; ▲ high, ▼ low) — a tag-derived "
                "proxy.\n"
                "1. WEIGHING EVIDENCE — which candidate the structural evidence "
                "favours and WHY …\n"
                "2. VERIFICATION PLAN — 3-5 numbered steps tied to REAL "
                "tags …\n"
                "3. DO NOT ACT YET — …\n"
                "End with: 'Structural decision support — operator's "
                "judgment prevails.'", language="text")
            st.code(_qa_context(), language="text")

    else:
        st.caption("Set GEMINI_API_KEY for optional Q&A grounded in "
                   "model facts — the brief above is deterministic and complete without it.")

# ---- playback: mens sekvensen ruller, be om en rerun ~1 s senere ------------
# Modellen er @st.cache_resource, så en rerun er billig. Løkka stopper av seg
# selv når vinduet er passert (S["playing"] settes False over), eller når
# operatøren trykker «Vis alle nå» / bekrefter et valg.
if playing:
    # refresh a bit faster than the alarm spacing so no alarm arrives "late";
    # clamp to 0.3–1.0 s so slow steps don't burn reruns and fast steps keep up.
    time.sleep(min(1.0, max(0.3, float(S["shower"].get("step", 2.5)) / 2)))
    st.rerun()