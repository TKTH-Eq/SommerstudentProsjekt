"""
src/kontrollrom.py  —  control-room decision-support prototype (alarm shower)

Registered by src/app.py via st.navigation:
    st.Page("kontrollrom.py", title="Kontrollrom-assistent", icon="🎛️"),

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
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import streamlit.components.v1 as components

from config import PID_DIR, CATEGORY_COLORS
from analysis.build_dependency_graph import interactive_svg
from analysis.hazop_dexpi import load_dexpi_model
from analysis.analyze_scd import failure_map
from analysis.control_room import (alarm_shower, candidate_brief,
                                   scenario_order, shower_debrief)
from ai.operator_brief import operator_brief

RAW_DIR = Path(PID_DIR).parent


def find_dexpi() -> dict:
    out = {}
    for x in sorted(RAW_DIR.rglob("*.DGN.xml")):
        m = re.search(r"H[A-Z](\d{2})", x.stem)
        out[f"{m.group(1) if m else '??'} · {x.stem.replace('.DGN', '')}"] = x
    return out


@st.cache_resource(show_spinner="Leser DEXPI-modell…")
def load(xml: str, mtime: float) -> dict:
    m = load_dexpi_model(Path(xml))
    allo, g = m["objects"], m["tag_graph"]
    return {"g": g, "by_tag": {o.tag: o for o in allo},
            "fmap": failure_map(g, allo)}


def chips(tags, by_tag):
    if not tags:
        return "_none_"
    out = ""
    for t in tags:
        c = CATEGORY_COLORS.get(by_tag[t].category if t in by_tag else "other",
                                "#9aa0a6")
        out += (f"<span style='background:{c};color:#fff;border-radius:20px;"
                f"padding:2px 8px;margin:2px;display:inline-block;"
                f"font-size:12px'>{t}</span> ")
    return out


# ---- setup ------------------------------------------------------------------
files = find_dexpi()
st.sidebar.title("Kontrollrom-assistent")
if not files:
    st.error("Fant ingen DEXPI-XML under data/raw/.")
    st.stop()
choice = st.sidebar.selectbox("Tegning", list(files))
M = load(str(files[choice]), files[choice].stat().st_mtime)
g, by_tag, fmap = M["g"], M["by_tag"], M["fmap"]

candidates = sorted((n for n in g.nodes if len(scenario_order(g, n)) >= 4),
                    key=lambda n: -len(scenario_order(g, n)))
if not candidates:
    st.warning("Denne tegningen har for lite konnektivitet til et scenario — "
               "velg en annen (HO27-002 anbefales).")
    st.stop()

st.sidebar.divider()
fault_pick = st.sidebar.selectbox("Feilkilde (skjules under kjøring)",
                                  ["(tilfeldig)"] + candidates)
n_noise = st.sidebar.slider("Støyalarmer", 0, 4, 2,
                            help="Urelaterte alarmer blandet inn i dusjen — "
                                 "gjør øvelsen realistisk.")
if st.sidebar.button("▶ Nytt scenario"):
    fault = random.choice(candidates[:15]) if fault_pick == "(tilfeldig)" \
        else fault_pick
    shower = alarm_shower(g, fault, noise=n_noise,
                          seed=random.randrange(10**6))
    st.session_state["cr"] = {"drawing": choice, "fault": fault,
                              "shower": shower, "chosen": None}

st.title("🎛️ Kontrollrom-assistent — alarmdusj")
st.caption("Alle alarmene kommer SAMTIDIG: en skjult feils fulle kaskade, "
           "stokket sammen med urelaterte støyalarmer. Assistenten gir en "
           "strukturell brief per kandidat — uten å kåre en vinner. DU veier "
           "bevisene og bestemmer mest sannsynlig årsak. Syntetisk scenario, "
           "beslutningsstøtte — ikke en prosessmodell.")

S = st.session_state.get("cr")
if not S or S["drawing"] != choice:
    st.info("Start et scenario fra sidepanelet. Velg «(tilfeldig)» — da vet "
            "heller ikke du fasiten.")
    st.stop()

active = S["shower"]["alarms"]
done = S["chosen"] is not None

left, right = st.columns([1, 1.5])

# ---- alarm board -------------------------------------------------------------
with left:
    st.subheader(f"🔔 Alarmtavle — {len(active)} samtidige")
    for a in active:
        st.write(f"🔴 **{a}**  \u2003"
                 f"`{by_tag[a].category if a in by_tag else '?'}`")
    if not done:
        st.divider()
        pick = st.selectbox("Mest sannsynlig årsak", ["(velg)"] + sorted(active))
        if pick != "(velg)" and st.button(f"✅ Bekreft: {pick} er årsaken"):
            S["chosen"] = pick
            st.rerun()

# ---- assistant brief ----------------------------------------------------------
with right:
    st.subheader("🤝 Assistentens brief — kandidater og bevis")
    st.caption("Kandidater = alarmer ingen annen aktiv alarm kan forklare "
               "(uavhengige røtter i grafen). Bevisene under er strukturelle; "
               "å veie dem er din jobb.")
    briefs = candidate_brief(g, by_tag, active)
    for b in briefs:
        n_exp = len(b["explains"])
        with st.expander(f"**{b['tag']}** — ville forklart {n_exp} av de "
                         f"andre alarmene", expanded=(len(briefs) <= 3)):
            if b["tag"] in fmap:
                st.code(operator_brief(b["tag"], fmap[b["tag"]], by_tag),
                        language="text")
            if b["explains"]:
                st.caption("Forklarer disse aktive alarmene som konsekvenser:")
                st.markdown(chips(b["explains"], by_tag),
                            unsafe_allow_html=True)
            ch = b["checks"]
            if ch["loop_mates"]:
                st.caption("Kryssjekk redundante målinger:")
                st.markdown(chips(ch["loop_mates"], by_tag),
                            unsafe_allow_html=True)
            if ch["upstream_sensors"]:
                st.caption("Verifiser oppstrøms:")
                st.markdown(chips(ch["upstream_sensors"], by_tag),
                            unsafe_allow_html=True)
            if b["barriers"]:
                st.caption("Barrierer i kjeden:")
                st.markdown(chips(b["barriers"], by_tag),
                            unsafe_allow_html=True)
    st.caption("Grafen viser strukturell nåbarhet, ikke prosesskonsekvens — "
               "bekreft mot tegning og driftsmodus.")

# ---- debrief -------------------------------------------------------------------
if done:
    st.divider()
    st.subheader("📋 Debrief")
    for line in shower_debrief(S["fault"], S["chosen"], S["shower"]["noise"],
                               len(active)):
        st.write("• " + line)
    if st.button("↺ Nytt scenario"):
        del st.session_state["cr"]
        st.rerun()

# ---- connectivity graph ---------------------------------------------------------
st.divider()
st.subheader("🕸️ Konnektivitet — vurder kandidatene visuelt")
st.caption("Velg en kandidat og se dens kjeder mot alarmbildet: dekker den "
           "røde nedstrøms-kjeglen alarmene på tavlen, eller står mange "
           "utenfor? Kilden forklarer flest; et symptom og en støyalarm "
           "dekker lite. Samme bevis som i briefen — nå synlig.")
cand_tags = [b["tag"] for b in candidate_brief(g, by_tag, active)]
hl_pick = st.selectbox("Marker kandidat (eller annen alarm)",
                       cand_tags + [t for t in sorted(active)
                                    if t not in cand_tags])
he = fmap.get(hl_pick)
highlight = ({"sel": hl_pick, "down": he["downstream"], "up": he["upstream"]}
             if he else None)
st.markdown(
    f"Markerer **{hl_pick}** &nbsp; "
    f"<span style='color:#12233b'>■ valgt</span> &nbsp; "
    f"<span style='color:#b8442c'>■ nedstrøms (konsekvens)</span> &nbsp; "
    f"<span style='color:#2d7dd2'>■ oppstrøms (mulig årsak)</span>",
    unsafe_allow_html=True)
components.html(
    f"<div style='font-family:sans-serif'>{interactive_svg(g, highlight=highlight)}</div>",
    height=560, scrolling=False)

# ---- optional grounded Q&A -----------------------------------------------------
st.divider()
if os.getenv("GEMINI_API_KEY"):
    with st.expander("💬 Spør assistenten (Gemini, forankret i modellen)"):
        q = st.text_input("Spørsmål om situasjonen",
                          placeholder="F.eks.: Hvordan skiller jeg kandidatene "
                                      "fra hverandre?")
        if q:
            briefs = candidate_brief(g, by_tag, active)
            ctx = "\n".join(
                f"- {b['tag']}: explains {len(b['explains'])} active alarms "
                f"({', '.join(b['explains']) or 'none'}); barriers: "
                f"{', '.join(b['barriers']) or 'none'}" for b in briefs)
            prompt = ("You are a control-room decision-support assistant "
                      "during an alarm flood. Use ONLY the facts and tags "
                      "below — NEVER invent a tag or process detail, and do "
                      "NOT state which candidate is correct; help the "
                      "operator reason about the evidence. Be terse. End "
                      "with: 'Structural decision support — operator "
                      "judgement decides.'\n\n"
                      f"ACTIVE ALARMS: {', '.join(active)}\n"
                      f"CANDIDATES:\n{ctx}\n\nQUESTION: {q}")
            try:
                from ai.gemini_client import generate
                with st.spinner("Spør modellen…"):
                    r = generate(prompt)
                st.markdown(r.text)
            except Exception as e:  # noqa: BLE001
                st.error(f"Gemini-kallet feilet: {e}")
else:
    st.caption("Sett GEMINI_API_KEY for valgfri spørsmål/svar forankret i "
               "modellfakta — briefen over er deterministisk og komplett uten.")