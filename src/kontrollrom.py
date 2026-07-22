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
import time
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


@st.cache_resource(show_spinner="Leser DEXPI-modell…")
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

# ---- designed cause & effect from the SCD (manual CSV, validated) ----------
CE = validate_ce(load_ce(RAW_DIR.parent / "cause_effect"
                         if (RAW_DIR.parent / "cause_effect").exists()
                         else Path("data/cause_effect")), by_tag)
ce_index = CE["index"]
if CE["stats"]["rows"]:
    _s = CE["stats"]
    st.sidebar.caption(
        f"C&E fra SCD: {_s['resolved']}/{_s['rows']} rader koblet, "
        f"{_s['verified']} verifisert"
        + (f" · ukjente tags: {', '.join(_s['unknown_tags'][:3])}"
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
    st.warning("Denne tegningen har for lite konnektivitet til et scenario — "
               "velg en annen (HO27-002 anbefales).")
    st.stop()

st.sidebar.divider()
fault_pick = st.sidebar.selectbox("Feilkilde (skjules under kjøring)",
                                  ["(tilfeldig)"] + candidates)
n_noise = st.sidebar.slider("Støyalarmer", 0, 4, 2,
                            help="Urelaterte alarmer blandet inn i dusjen — "
                                 "gjør øvelsen realistisk.")
alarm_step = st.sidebar.slider(
    "Sekunder mellom alarmer", 0.5, 10.0, 2.5, 0.5,
    help="Hvor raskt kaskaden ruller inn. Lavt = rask demo, høyt = mer tid "
         "til å lese hver alarm. Gjelder neste scenario du starter.")
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
                          by_tag=by_tag, step=alarm_step)
    st.session_state["cr"] = {"drawing": choice, "fault": fault,
                              "shower": shower, "chosen": None,
                              "play_start": time.time(), "playing": True}

page_header("Kontrollrom-assistent — alarmdusj",
            f"kilde: {'hele anlegget (17 tegninger)' if plant_mode else choice}"
            f" · syntetisk scenario · beslutningsstøtte, ikke prosessmodell")
st.caption("Alarmene kommer inn SOM EN SEKVENS over noen sekunder: en skjult "
           "feils kaskade i årsaksrekkefølge, blandet med urelaterte "
           "støyalarmer. Assistenten gir en strukturell brief per kandidat — "
           "uten å kåre en vinner. DU veier bevisene og bestemmer mest "
           "sannsynlig årsak.")

S = st.session_state.get("cr")
if not S or S["drawing"] != choice:
    st.markdown("### Slik spiller du")
    s1, s2, s3 = st.columns(3)
    s1.markdown("**1 · Start** \nVelg kilde og trykk «▶ Nytt scenario» i "
                "sidepanelet. Velg «(tilfeldig)» — da vet heller ikke du "
                "fasiten. «🏭 Hele anlegget» gir kaskader på tvers av "
                "tegninger.")
    s2.markdown("**2 · Vurder** \nAlarmene kommer inn i sekvens over noen "
                "sekunder — merk deg hvilken som kom FØRST. Les assistentens "
                "brief per kandidat og bruk konnektivitets-fanen til å se "
                "bevisene visuelt.")
    s3.markdown("**3 · Beslutt** \nPek på mest sannsynlig årsak og bekreft. "
                "Debriefen forteller om du traff kilden, et symptom eller "
                "støy — og kan beregne fysisk konsekvens (NeqSim).")
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
    if playing:
        pc1, pc2 = st.columns([4, 1])
        pc1.caption(f"⏱️ Alarmene kommer inn … **{len(active)}/{len(all_alarms)}** "
                    f"vist. Første alarm: **{S['shower'].get('first_up', '?')}**.")
        if pc2.button("⏭ Vis alle nå"):
            S["playing"] = False
            st.rerun()
    # ---- neutral opening situation brief (fault-blind) -------------------------
    sb = situation_brief(active, briefs, drawings_of if plant_mode else None)
    st.subheader("🧭 Situasjonsbrief")
    head = (f"**{sb['n_alarms']} samtidige alarmer** &nbsp;·&nbsp; "
            f"**{sb['n_candidates']} uavhengige kandidatrøtter**")
    if plant_mode and sb["n_drawings"]:
        head += f" &nbsp;·&nbsp; **{sb['n_drawings']} tegninger berørt**"
    st.markdown(head)
    st.caption("Rangert etter hvor mange andre aktive alarmer hver kandidat "
               "ville forklart — det sterkeste strukturelle sporet. "
               "Assistenten vet IKKE hvilken alarm som er årsaken og kårer "
               "ingen vinner; å veie bevisene er din jobb.")
    _fu = S["shower"].get("first_up")
    if _fu:
        st.caption(f"⏱️ Første alarm i sekvensen: **{_fu}** — kom først, ofte "
                   "(men ikke alltid) nærmest roten. Et observerbart spor, "
                   "ikke fasit.")
    _cap = 8
    for i, r in enumerate(sb["ranking"][:_cap], 1):
        st.markdown(
            f"**{i}.** {prio_badge(r['tag'], by_tag)} &nbsp; **{r['tag']}** "
            f"— forklarer **{r['explains_count']}** andre aktive alarmer"
            + (_drw(r["tag"]) if plant_mode else ""),
            unsafe_allow_html=True)
    if len(sb["ranking"]) > _cap:
        st.caption(f"+ {len(sb['ranking']) - _cap} flere kandidater "
                   f"(forklarer færre eller ingen).")
    if sb["any_none"]:
        st.caption("Kandidater som forklarer 0 kan være uavhengige/isolerte "
                   "alarmer — eller støy. Grafen viser strukturell nåbarhet, "
                   "ikke prosessårsak; bekreft mot tegning og driftsmodus.")
    st.divider()

    left, right = st.columns([1, 1.5])

    # ---- alarm board -------------------------------------------------------------
    with left:
        st.subheader(f"🔔 Alarmtavle — {len(active)} samtidige")
        sort_time = st.toggle(
            "Sortér etter ankomst (first-up øverst)", value=False,
            help="Av = prioritet (P1 øverst). På = rekkefølgen alarmene kom "
                 "inn — first-up-sporet.")
        st.caption("**+t** = sekunder etter første alarm. Prioritet/retning "
                   "er utledet fra tag-en — en proxy, ikke konfigurert "
                   "alarmprioritet.")
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
                _ce = ce_lines_for(b["tag"], ce_index)
                if _ce:
                    st.caption("**Designert logikk (SCD C&E)** — hva arket "
                               "sier skal skje, ikke bare hva som er koblet:")
                    for line in _ce:
                        st.markdown(f"&nbsp;&nbsp;⚙️ `{line}`",
                                    unsafe_allow_html=True)
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
        _dr = designed_response_check(S["fault"], ce_index, active)
        if _dr:
            st.write("• **Designert respons (SCD C&E) for feilkilden:**")
            for d in _dr:
                mk = "✅ ringte" if d["observed"] else "⬜ ringte ikke i scenariet"
                uv = "" if d["verified"] else " *(uverifisert rad)*"
                st.write(f"&nbsp;&nbsp;&nbsp;⚙️ {S['fault']} → {d['effect']}: "
                         f"{d['function']} — {mk}{uv}")
            st.caption("Sammenlikner arkets designede aksjoner med alarmene "
                       "som faktisk kom — samsvar styrker diagnosen, avvik er "
                       "et funn i seg selv.")
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
                    for ce_line in ce_lines_for(b["tag"], ce_index, 3):
                        lines.append(f"  DESIGNED C&E (from SCD sheet): {ce_line}")
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

# ---- playback: mens sekvensen ruller, be om en rerun ~1 s senere ------------
# Modellen er @st.cache_resource, så en rerun er billig. Løkka stopper av seg
# selv når vinduet er passert (S["playing"] settes False over), eller når
# operatøren trykker «Vis alle nå» / bekrefter et valg.
if playing:
    # refresh a bit faster than the alarm spacing so no alarm arrives "late";
    # clamp to 0.3–1.0 s so slow steps don't burn reruns and fast steps keep up.
    time.sleep(min(1.0, max(0.3, float(S["shower"].get("step", 2.5)) / 2)))
    st.rerun()