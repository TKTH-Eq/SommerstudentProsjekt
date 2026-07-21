"""
Alarm semantics from the tag alone — priority, direction and severity.

Point 1 of the control-room upgrade. The Huldra tags already encode the
alarm/trip information in their functional letters:

    LAHH  = Level  Alarm  High-High  -> trip level, direction HIGH
    PSH   = Pressure Switch High      -> alarm level, direction HIGH
    ZSL   = position Switch Low        -> alarm level, direction LOW
    XV/PSV/ESV/PSE                     -> shutdown / relief final elements

The trailing H/HH/L/LL is only an alarm/trip modifier when it follows an
A (alarm) or S (switch) function letter. That single rule is what keeps
ZL (position *lamp*), EL, VL, XL, PH out of the directional set while
still catching LAHH, TAHH, LSH, PSH, ZSH, ZSL, XSH, XSL.

HONEST SCOPE — this is a *proxy* derived from the tag, not the configured
operator priority. The real priority, setpoint and allowable response time
live in the alarm philosophy / alarm database, which is not in the open
Huldra data. What the tag DOES tell us reliably: trip-level (HH/LL) vs
alarm-level (single H/L) vs an unannotated measurement, plus the safety
role of final elements. We surface exactly that and label it as a proxy.

The four-level ladder follows YA-711 / EEMUA-191 practice: at most three
priorities in normal presentation plus one reserved for safety-critical.

Pure functions, no graph/IO — unit-testable headless.
"""
from __future__ import annotations

import re

# Final elements that initiate or execute a shutdown / pressure protection.
SHUTDOWN_TYPES = {"XV", "ESV", "PSV", "PSE"}

# Types that carry a genuine process measurement (can raise a process alarm
# even without an explicit H/L in the tag) vs. pure indicators/status/lamps.
_TRANSMITTERS = {"PT", "TT", "LT", "FT", "PDT", "PDIT", "AE", "SI"}
_CONTROLLERS = {"PIC", "LIC", "TIC", "FIC", "FRC", "TDIC", "HIC"}
_INDICATORS = {"PI", "TI", "LI", "FI", "PDI", "ZL", "XA", "XI", "XS", "US"}

# Priority ladder (proxy). 1 = highest. Labels are Norwegian for the UI.
PRIORITY_LABELS = {
    1: "P1 · Kritisk (sikkerhet/trip)",
    2: "P2 · Høy",
    3: "P3 · Lav",
    4: "P4 · Melding/info",
}

# Generic response-time guidance BY PRIORITY. Illustrative — the real
# allowable response time is defined in the alarm philosophy, not the tag.
RESPONSE_TIME_BANDS = {
    1: "Umiddelbar (sekunder) — automatisk sikkerhetsfunksjon kan alt ha reagert",
    2: "Rask — innen få minutter",
    3: "Undersøk — innen titalls minutter",
    4: "Overvåk — ingen umiddelbar handling",
}

_DIR_RE = re.compile(r"(A|S)(HH|LL|H|L)$")


def alarm_semantics(type_code: str) -> dict:
    """Derive {direction, level, priority, priority_label, response_time,
    is_shutdown, annotated} from an instrument/equipment type code.

    direction : 'high' | 'low' | None
    level     : 'trip' (HH/LL) | 'alarm' (single H/L) | None
    priority  : 1..4  (proxy, see module docstring)
    """
    tc = (type_code or "").upper()
    direction: str | None = None
    level: str | None = None

    m = _DIR_RE.search(tc)
    if m:
        mod = m.group(2)
        direction = "high" if mod[0] == "H" else "low"
        level = "trip" if len(mod) == 2 else "alarm"

    is_shutdown = tc in SHUTDOWN_TYPES or level == "trip"

    if is_shutdown:
        pr = 1
    elif level == "alarm":
        pr = 2
    elif tc in _TRANSMITTERS or tc in _CONTROLLERS:
        pr = 3
    elif tc in _INDICATORS:
        pr = 4
    else:
        pr = 3  # unknown but alarm-capable -> treat as low, never silently critical

    return {
        "direction": direction,
        "level": level,
        "priority": pr,
        "priority_label": PRIORITY_LABELS[pr],
        "response_time": RESPONSE_TIME_BANDS[pr],
        "is_shutdown": is_shutdown,
        "annotated": m is not None,
    }


# Convenience one-character direction arrow for compact UI chips.
DIR_ARROW = {"high": "▲", "low": "▼", None: ""}


def dir_label(direction: str | None) -> str:
    return {"high": "høy", "low": "lav"}.get(direction, "")


def priority_of(obj) -> int:
    """Priority for an EngineeringObject (or anything with .type_code)."""
    return alarm_semantics(getattr(obj, "type_code", "")).get("priority", 3)


def priority_sort_key(tag: str, by_tag) -> tuple:
    """Sort key so the most important alarms come first: priority asc
    (1 = critical first), then high before low, then tag for stability."""
    o = by_tag.get(tag) if by_tag else None
    s = alarm_semantics(getattr(o, "type_code", "")) if o else {"priority": 3,
                                                                 "direction": None}
    dir_rank = {"high": 0, "low": 1}.get(s["direction"], 2)
    return (s["priority"], dir_rank, tag)


if __name__ == "__main__":  # quick self-check against real Huldra type codes
    samples = ["LAHH", "TAHH", "LSH", "LSHH", "PSH", "ZSL", "ZSH", "XSH",
               "XSL", "PSV", "PSE", "XV", "ESV", "PT", "TT", "LT", "PIC",
               "PI", "TI", "ZL", "EL", "VL", "XL", "PH", "XA", "SI"]
    for tc in samples:
        s = alarm_semantics(tc)
        print(f"{tc:6} P{s['priority']} "
              f"dir={s['direction'] or '-':4} level={s['level'] or '-':5} "
              f"shutdown={s['is_shutdown']!s:5} annotated={s['annotated']}")