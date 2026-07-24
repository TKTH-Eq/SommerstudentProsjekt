"""Shared INCIDENT CONTEXT — stitches the whole app around one situation.

The Control Room page PUBLISHES the current alarm scenario here (every
rerun, so the top candidate stays fresh); every other page can read it,
show a banner, and preselect its own drawing/system/tag accordingly.
One incident, the whole toolbox: topology, NeqSim consequence, HAZOP
prep, drawing analysis, tag register — all pointing at the same event.

Honesty rule: while the scenario is UNANSWERED the hidden fault is NOT
published (the operator could read the answer off another page). The
anchor tag is then the top structural candidate / first-up — which the
operator already sees. After the operator has answered, the true fault
is included.

Everything here is defensive: a missing or malformed context must never
break a page.
"""
from __future__ import annotations

import streamlit as st

_KEY = "active_incident"


def set_incident(ctx: dict) -> None:
    st.session_state[_KEY] = ctx


def get_incident() -> dict | None:
    ctx = st.session_state.get(_KEY)
    return ctx if isinstance(ctx, dict) and ctx.get("n_alarms") else None


def clear_incident() -> None:
    st.session_state.pop(_KEY, None)


def anchor_tag(ctx: dict | None) -> str | None:
    """The tag other pages should focus on: the true fault once answered,
    otherwise the top structural candidate / first-up (already visible)."""
    if not ctx:
        return None
    return (ctx.get("fault") or ctx.get("top") or ctx.get("first_up"))


def _pair(t: str):
    """(type, number) normalisation — same idea as the control-room audit:
    PT 2005 ≡ 20-PT2005 ≡ 20-2005PT."""
    import re as _re
    u = _re.sub(r"\s+", "", str(t).upper())
    u = u.split("-", 1)[1] if _re.match(r"^\d{2}-", u) else u
    u = u.replace("-", "")
    m = _re.match(r"^([A-Z]{1,4})(\d{2,4})[A-Z]?$", u)
    if m:
        return m.group(1), m.group(2)
    m = _re.match(r"^(\d{2,4})([A-Z]{1,4})$", u)
    return (m.group(2), m.group(1)) if m else None


def tag_in_incident(tag: str, ctx: dict | None) -> bool:
    """Is `tag` one of the incident's alarms? Robust to format variations
    (PT2005 vs 20-2005PT) via (type, number) normalisation."""
    if not ctx:
        return False
    alarms = ctx.get("alarms") or []
    if str(tag) in alarms:
        return True
    p = _pair(tag)
    return p is not None and any(_pair(a) == p for a in alarms)


def match_index(options, *candidates, default: int = 0) -> int:
    """Index of the first option matching any candidate (equality or
    substring either way) — for preselecting selectboxes without knowing
    each page's exact option format. Falls back to `default`."""
    try:
        opts = [str(o) for o in list(options)]
        for c in candidates:
            if c is None:
                continue
            cs = str(c)
            if not cs:
                continue
            for i, so in enumerate(opts):
                if cs == so or cs in so or so in cs:
                    return i
    except Exception:  # noqa: BLE001
        pass
    return default


def incident_banner(hint: str = "", key: str = "pg") -> dict | None:
    """Compact banner for consumer pages: what the active incident is and
    (via `hint`) what THIS page preselected because of it. Returns the
    context (or None) so the caller can use it for its own preselection.
    A Clear button drops the context app-wide."""
    ctx = get_incident()
    if not ctx:
        return None
    try:
        a = anchor_tag(ctx)
        drw = ctx.get("drawings") or []
        where = (", ".join(d[-14:] for d in drw[:3]) + (" …" if len(drw) > 3 else "")
                 if drw else str(ctx.get("source") or ""))
        state = "answered" if ctx.get("answered") else "in progress"
        c1, c2 = st.columns([7, 1])
        c1.info(f"🔗 **Active incident** ({state}, from the Control Room): "
                f"{ctx.get('title', 'alarm scenario')} · "
                f"**{ctx.get('n_alarms', '?')} alarms** · focus **{a or '?'}**"
                + (f" · {where}" if where else "")
                + (f" — {hint}" if hint else ""), icon="🔗")
        if c2.button("✕ Clear", key=f"inc_clear_{key}",
                     help="Drop the shared incident context (all pages)"):
            clear_incident()
            st.rerun()
    except Exception:  # noqa: BLE001
        return ctx
    return ctx