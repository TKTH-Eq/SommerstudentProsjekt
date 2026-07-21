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

from dotenv import load_dotenv
load_dotenv()  # eksplisitt: GEMINI_API_KEY-gaten under avhenger av .env,
               # og skal ikke lene seg på at en annen import lastet den
import streamlit.components.v1 as components

from config import PID_DIR, CATEGORY_COLORS
from analysis.build_dependency_graph import interactive_svg
from analysis.hazop_dexpi import load_dexpi_model
from analysis.analyze_scd import failure_map
from analysis.control_room import (alarm_shower, candidate_brief,
                                   scenario_order, shower_debrief)
from analysis.alarm_priority import (alarm_semantics, DIR_ARROW,
                                     priority_sort_key)
from ai.operator_brief import operator_brief, alarm_response_sheet

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


PRIO_COLOR = {1: "#c0392b", 2: "#e67e22", 3: "#c9a227", 4: "#7f8c8d"}


def prio_badge(tag, by_tag):
    """Small coloured P1..P4 badge with a high/low arrow for a tag."""
    o = by_tag.get(tag)
    if not o:
        return ""
    s = alarm_semantics(o.type_code)
    c = PRIO_COLOR.get(s["priority"], "#7f8c8d")
    arrow = DIR_ARROW.get(s["direction"], "")
    return (f"<span style='background:{c};color:#fff;border-radius:6px;"
            f"padding:1px 7px;font-size:11px;font-weight:600'>"
            f"P{s['priority']}{arrow}</span>")


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

PLANT = "🏭 Hele anlegget (alle tegninger)"


@st.cache_resource(show_spinner="Syr sammen anleggsmodellen…")
def load_plant() -> dict:
    from analysis.plant_model import build_plant_model
    Mp = build_plant_model(RAW_DIR)
    return {"g": Mp["graph"], "by_tag": {o.tag: o for o in Mp["objects"]},
            "fmap": failure_map(Mp["graph"], Mp["objects"]),
            "drawings_of": Mp["drawings_of"], "stats": Mp["stats"]}


choice = st.sidebar.selectbox("Kilde", [PLANT] + list(files))
plant_mode = choice == PLANT
if plant_mode:
    M = load_plant()
    st.sidebar.caption(f"{M['stats']['drawings']} tegninger · "
                       f"{M['stats']['tags']} tags · "
                       f"{M['stats']['line_stitches']} linje-sømmer · "
                       f"{M['stats']['cross_edges']} kryss-kanter")
else:
    M = load(str(files[choice]), files[choice].stat().st_mtime)
g, by_tag, fmap = M["g"], M["by_tag"], M["fmap"]
drawings_of = M.get("drawings_of", {})


def _drw(tag: str) -> str:
    ds = drawings_of.get(tag, [])
    return f" `[{ds[0][-14:]}]`" if ds else ""

from analysis.control_room import alarm_capable
candidates = sorted((n for n in g.nodes
                     if alarm_capable(by_tag.get(n))
                     and len(scenario_order(g, n)) >= 4),
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
demo_mode = st.sidebar.toggle(
    "🔒 Demo-modus (reproduserbart)",
    help="Fast seed: samme feilkilde gir nøyaktig samme scenario hver gang. "
         "Gjør at chat-svar kan pre-caches kvelden før — og at demoen "
         "fungerer offline.")
if st.sidebar.button("▶ Nytt scenario"):
    fault = random.choice(candidates[:15]) if fault_pick == "(tilfeldig)" \
        else fault_pick
    shower = alarm_shower(g, fault, noise=n_noise,
                          seed=42 if demo_mode else random.randrange(10**6),
                          by_tag=by_tag)
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
    st.markdown("### Slik spiller du")
    s1, s2, s3 = st.columns(3)
    s1.markdown("**1 · Start** \nVelg kilde og trykk «▶ Nytt scenario» i "
                "sidepanelet. Velg «(tilfeldig)» — da vet heller ikke du "
                "fasiten. «🏭 Hele anlegget» gir kaskader på tvers av "
                "tegninger.")
    s2.markdown("**2 · Vurder** \nAlle alarmene kommer samtidig. Les "
                "assistentens brief per kandidat og bruk konnektivitets-"
                "fanen til å se bevisene visuelt.")
    s3.markdown("**3 · Beslutt** \nPek på mest sannsynlig årsak og bekreft. "
                "Debriefen forteller om du traff kilden, et symptom eller "
                "støy — og kan beregne fysisk konsekvens (NeqSim).")
    st.stop()

active = S["shower"]["alarms"]
active_sorted = sorted(active, key=lambda t: priority_sort_key(t, by_tag))
done = S["chosen"] is not None

briefs = candidate_brief(g, by_tag, active)   # beregnes ÉN gang, brukes overalt

m1, m2, m3, m4 = st.columns(4)
m1.metric("Samtidige alarmer", len(active),
          help="Kun alarm-KAPABLE funksjoner ringer (instrumenter, brytere, "
               "regulatorer, sikkerhetsfunksjoner) — en håndventil har ingen "
               "alarm. Strukturelt eksponert totalt: se neste tall.")
m1.caption(f"eksponert: {S['shower'].get('exposed', '?')} komponenter")
m2.metric("Kandidat-røtter", len(briefs),
          help="Alarmer ingen annen aktiv alarm kan forklare — uavhengige "
               "røtter i grafen (sykel-grupper telles som én).")
if plant_mode:
    _drawn = sorted({d for t in active for d in drawings_of.get(t, [])})
    m3.metric("Tegninger berørt", len(_drawn),
              help="Kaskaden krysser tegningsgrenser via linje-sømmene — "
                   "umulig å se fra ett ark.")
else:
    m3.metric("Kilde", "1 tegning")
m4.metric("Status", "✅ Besvart" if done else "⏳ Pågår")

tab_sit, tab_graf, tab_chat = st.tabs(
    ["🔔 Situasjon og beslutning", "🕸️ Konnektivitet", "💬 Spør assistenten"])

with tab_sit:
    left, right = st.columns([1, 1.5])

    # ---- alarm board -------------------------------------------------------------
    with left:
        st.subheader(f"🔔 Alarmtavle — {len(active)} samtidige")
        st.caption("Sortert etter prioritet (P1 kritisk øverst). "
                   "Prioritet/retning er utledet fra tag-en — en proxy, ikke "
                   "konfigurert alarmprioritet.")
        for a in active_sorted:
            cat = by_tag[a].category if a in by_tag else "?"
            st.markdown(
                f"🔴 **{a}** &nbsp; {prio_badge(a, by_tag)} &nbsp; "
                f"<code>{cat}</code>"
                + (_drw(a) if plant_mode else ""),
                unsafe_allow_html=True)
        if not done:
            st.divider()
            pick = st.selectbox("Mest sannsynlig årsak", ["(velg)"] + active_sorted)
            if pick != "(velg)" and st.button(f"✅ Bekreft: {pick} er årsaken"):
                S["chosen"] = pick
                st.rerun()

    # ---- assistant brief ----------------------------------------------------------
    with right:
        st.subheader("🤝 Assistentens brief — kandidater og bevis")
        st.caption("Kandidater = alarmer ingen annen aktiv alarm kan forklare "
                   "(uavhengige røtter i grafen). Bevisene under er strukturelle; "
                   "å veie dem er din jobb.")
        for b in briefs:
            n_exp = len(b["explains"])
            plab = b.get("priority_label", "")
            with st.expander(f"**{b['tag']}** · {plab} — ville forklart "
                             f"{n_exp} av de andre alarmene",
                             expanded=(len(briefs) <= 3)):
                if b["tag"] in fmap:
                    st.code(alarm_response_sheet(b["tag"], fmap[b["tag"]],
                                                 by_tag),
                            language="text")
                if b.get("group"):
                    st.caption(f"⭕ Strukturelt uatskillelige (samme sykel via "
                               f"tegnings-sømmer): {', '.join(b['group'][:8])}"
                               + (" …" if len(b["group"]) > 8 else ""))
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
        fault_group = set()
        for b in briefs:
            grp = {b["tag"]} | set(b.get("group", []))
            if S["fault"] in grp:
                fault_group = grp
        if plant_mode and S["chosen"] in fault_group and S["chosen"] != S["fault"]:
            st.write(f"• Faktisk feilkilde: {S['fault']} — valget ditt "
                     f"({S['chosen']}) ligger i SAMME sykel over tegnings-sømmene "
                     f"og er strukturelt uatskillelig fra kilden. Regnes som "
                     f"riktig gruppe; fysisk verifisering må skille dem — nettopp "
                     f"fordi retning over en søm ikke er oppgitt i leveransen.")
            for line in shower_debrief(S["fault"], S["chosen"], S["shower"]["noise"],
                                       len(active))[-1:]:
                st.write("• " + line)
        else:
            for line in shower_debrief(S["fault"], S["chosen"], S["shower"]["noise"],
                                       len(active)):
                st.write("• " + line)
        if plant_mode:
            drawn = sorted({d for t in active for d in drawings_of.get(t, [])})
            st.write(f"• Kaskaden berørte **{len(drawn)} tegninger**: "
                     + ", ".join(d[-14:] for d in drawn)
                     + " — umulig å se fra ett ark, mulig fordi leveransen er "
                       "strukturert og sammensybar.")
        with st.expander("🧪 Fysisk konsekvens av valget ditt (NeqSim)"):
            st.caption("Kobler beslutningen til fysikk: hva isoleres strukturelt "
                       "hvis komponenten du pekte på faktisk feiler/stenges — og "
                       "hva er hydratrisikoen i det isolerte segmentet? "
                       "Forenklet illustrasjon (eksempeltrykk, antatt "
                       "fluidmapping) — se forbehold i simuleringsmodulen.")
            cons_drawing = (drawings_of.get(S["chosen"], [None])[0] if plant_mode
                            else str(files[choice].stem).replace(".DGN", ""))
            if cons_drawing is None:
                st.caption("Fant ikke tegningen for valgt komponent.")
            elif st.button("Beregn konsekvens", key="neqsim_cons"):
                from analysis.neqsim_seam import consequence_for
                with st.spinner("Kjører feilsimulering + NeqSim…"):
                    r = consequence_for(cons_drawing, S["chosen"])
                st.write(r["summary"])
                if r["affected"]:
                    st.markdown(chips(r["affected"][:20], by_tag),
                                unsafe_allow_html=True)
                if r["log"].strip():
                    st.code(r["log"].strip()[-1500:], language="text")

        if st.button("↺ Nytt scenario"):
            del st.session_state["cr"]
            st.rerun()


with tab_graf:
    # ---- connectivity graph ---------------------------------------------------------
    st.subheader("🕸️ Konnektivitet — vurder kandidatene visuelt")
    st.caption("Velg en kandidat og se dens kjeder mot alarmbildet: dekker den "
               "røde nedstrøms-kjeglen alarmene på tavlen, eller står mange "
               "utenfor? Kilden forklarer flest; et symptom og en støyalarm "
               "dekker lite. Samme bevis som i briefen — nå synlig.")
    cand_tags = [b["tag"] for b in briefs]
    hl_pick = st.selectbox("Marker kandidat (eller annen alarm)",
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
        st.caption(f"Anleggsmodus: viser subgrafen rundt alarmbildet "
                   f"({g_view.number_of_nodes()} av {g.number_of_nodes()} tags).")
    st.markdown(
        f"Markerer **{hl_pick}** &nbsp; "
        f"<span style='color:#12233b'>■ valgt</span> &nbsp; "
        f"<span style='color:#b8442c'>■ nedstrøms (konsekvens)</span> &nbsp; "
        f"<span style='color:#2d7dd2'>■ oppstrøms (mulig årsak)</span>",
        unsafe_allow_html=True)
    from analysis.control_room import layered_cause_svg
    st.caption("Årsakskart: kun ALARMERTE noder, i kolonner etter avstand "
               "fra valgt kandidat. En pil betyr «når frem, uten annen alarm "
               "imellom» — hold musen over for faktisk antall hopp gjennom "
               "komponenter som ikke alarmerer (håndventiler o.l.).")
    components.html(
        f"<div style='background:#141820;border-radius:10px;padding:8px'>"
        f"{layered_cause_svg(g, hl_pick, active, drawings_of or None)}</div>",
        height=760, scrolling=True)
    with st.expander("Vis rå subgraf (spring-layout, alle mellomledd)"):
        components.html(
            f"<div style='font-family:sans-serif'>{interactive_svg(g_view, highlight=highlight)}</div>",
            height=560, scrolling=False)


with tab_chat:
    # ---- optional grounded Q&A -----------------------------------------------------
    if os.getenv("GEMINI_API_KEY"):
        with st.expander("💬 Spør assistenten (Gemini, forankret i modellen)",
                         expanded=bool(st.session_state.get("qa_hist"))):
            from analysis.control_room import audit_answer_tags

            # samtaleminne per scenario — nullstilles når nytt scenario startes
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
                return "\n".join(lines)

            # vis historikken som chat
            for q_prev, a_prev, audit_prev in hist:
                with st.chat_message("user"):
                    st.write(q_prev)
                with st.chat_message("assistant"):
                    st.markdown(a_prev)
                    if audit_prev["suspect"]:
                        st.caption("Tag-sjekk: ✅ "
                                   + ", ".join(audit_prev["verified"]) + " · ❓ **"
                                   + ", ".join(audit_prev["suspect"])
                                   + "** — finnes ikke i modellen, verifiser!")
                    elif audit_prev["verified"]:
                        st.caption("Tag-sjekk: ✅ alle refererte tags finnes i "
                                   "modellen (" 
                                   + ", ".join(audit_prev["verified"]) + ")")


        # foreslåtte spørsmål (demo-sikring) + fritekst
            sugg = ["Gi meg en verifiseringsplan for alarmbildet",
                    "Hva taler for og mot hver kandidat?",
                    "Hva bør jeg ikke gjøre ennå, og hvorfor?"]
            cols = st.columns(len(sugg))
            clicked = None
            for c, txt in zip(cols, sugg):
                if c.button(txt, key=f"sugg_{txt[:12]}_{hist_key}"):
                    clicked = txt
            typed = st.text_input("Eller still ditt eget spørsmål",
                                  key=f"qa_in_{hist_key}")
            q = clicked or (typed if st.button("Send", key=f"qa_send_{hist_key}")
                            else None)

            if q:
                history_txt = "\n".join(
                    f"OPERATOR: {hq}\nASSISTANT: {ha}" for hq, ha, _ in hist[-3:])
                prompt = (
                    "You are a control-room decision-support assistant during an "
                    "alarm flood. Answer in NORWEGIAN. Use ONLY the facts and "
                    "tags below — NEVER invent a tag; general process knowledge "
                    "may be used if marked '(generelt)'.\n"
                    "Weight candidates and actions by the PRIORITY shown "
                    "(P1 = critical/trip highest … P4 lowest; ▲ high, ▼ low). "
                    "Priority is DERIVED FROM THE TAG, not the configured alarm "
                    "priority — treat it as a proxy and say so if it matters.\n"
                    "Your job is to turn the evidence into ACTION, not to "
                    "restate it. Structure the answer as:\n"
                    "1. BEVISVEIING — which candidate the structural evidence "
                    "favours and WHY (explains-counts, failure modes, position), "
                    "and what would speak against it. You SHOULD take a stand; "
                    "it is a structural assessment, not the verdict.\n"
                    "2. VERIFISERINGSPLAN — 3-5 numbered steps in priority "
                    "order. Each step: a concrete check tied to a REAL tag from "
                    "the facts, what reading/outcome to expect if the favoured "
                    "candidate is true, and what the opposite outcome would "
                    "imply.\n"
                    "3. IKKE GJØR ENNÅ — one line on actions to hold off on "
                    "and why.\n"
                    "Be concrete and terse. End with: 'Strukturell "
                    "beslutningsstøtte — operatørens vurdering avgjør.'\n\n"
                    f"FACTS:\n{_qa_context()}\n\n"
                    + (f"CONVERSATION SO FAR:\n{history_txt}\n\n" if hist else "")
                    + f"QUESTION: {q}")
                from ai.ai_cache import load_qa, save_qa
                cached_qa = load_qa(prompt)
                if cached_qa:
                    ans = cached_qa["answer"]
                    hist.append((f"{q}  \n*(🗂️ cachet svar, "
                                 f"{cached_qa['saved_at']})*", ans,
                                 audit_answer_tags(ans, by_tag)))
                    st.rerun()
                else:
                    try:
                        from ai.gemini_client import generate
                        with st.spinner("Spør modellen…"):
                            ans = generate(prompt).text
                        save_qa(prompt, q, ans)
                        hist.append((q, ans, audit_answer_tags(ans, by_tag)))
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Gemini-kallet feilet: {e}")

        st.divider()
        with st.expander("Vis prompt-malen og gjeldende fakta (skrivebeskyttet)"):
            st.caption("Samme standard som HAZOP-siden: malen er fast — "
                       "skjemaet (BEVISVEIING/VERIFISERINGSPLAN/IKKE GJØR "
                       "ENNÅ), tag-forbudet og norsk svar kan ikke "
                       "overstyres. FAKTA-blokken under bygges deterministisk "
                       "av modellen for hvert alarmbilde.")
            st.code(
                "You are a control-room decision-support assistant during an "
                "alarm flood. Answer in NORWEGIAN. Use ONLY the facts and "
                "tags below — NEVER invent a tag; general process knowledge "
                "may be used if marked '(generelt)'.\n"
                "Weight candidates and actions by the PRIORITY shown "
                "(P1 highest … P4 lowest; ▲ high, ▼ low) — a tag-derived "
                "proxy.\n"
                "1. BEVISVEIING — which candidate the structural evidence "
                "favours and WHY …\n"
                "2. VERIFISERINGSPLAN — 3-5 numbered steps tied to REAL "
                "tags …\n"
                "3. IKKE GJØR ENNÅ — …\n"
                "End with: 'Strukturell beslutningsstøtte — operatørens "
                "vurdering avgjør.'", language="text")
            st.code(_qa_context(), language="text")

    else:
        st.caption("Sett GEMINI_API_KEY for valgfri spørsmål/svar forankret i "
                   "modellfakta — briefen over er deterministisk og komplett uten.")