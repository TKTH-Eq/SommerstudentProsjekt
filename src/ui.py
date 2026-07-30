"""
src/ui.py — Huldra Insight design system for Streamlit.

Equinor-inspired (EDS-style): calm white/gray-blue surfaces, Moss Green
(#007079) as the interactive primary, Energy Red reserved for danger/critical,
mono type for anything that is a tag, underline tabs, thin borders.

Usage (unchanged API):
    app.py:          from ui import inject_css; inject_css()
    any page:        from ui import page_header, chips, pill, prio_badge
"""
from __future__ import annotations
import streamlit as st

# ---- palette (EDS-inspired) -------------------------------------------------
SLATE = "#243746"          # primary text
MUTED = "#5c6f7c"          # secondary text
FAINT = "#8395a1"          # captions / table headers
MOSS = "#007079"           # interactive primary (Moss Green)
MOSS_DARK = "#004f55"
RED = "#eb0037"            # danger / critical only
GREEN = "#00977b"
BORDER = "#e3e8ec"
PAGE_BG = "#f7f9fa"        # calm gray-blue canvas
CARD_BG = "#ffffff"

# category -> (bg, border, text) — tinted mono chips
CAT_CHIP = {
    "input":     ("#e6f1fb", "#b5d4f4", "#0c447c"),
    "logic":     ("#faeeda", "#fac775", "#633806"),
    "output":    ("#fbeaf0", "#f4c0d1", "#72243e"),
    "equipment": ("#e1f5ee", "#9fe1cb", "#085041"),
    "other":     ("#f0f2f4", "#d5dbe0", "#5c6f7c"),
}
PILL = {
    "ok":      ("#e1f5ee", "#9fe1cb", "#085041"),
    "warn":    ("#faeeda", "#fac775", "#633806"),
    "danger":  ("#fcebeb", "#f7c1c1", "#791f1f"),
    "neutral": ("#f0f2f4", "#d5dbe0", "#5c6f7c"),
}
# P1 red (critical only), P2 amber, P3 muted amber-gray, P4 gray
PRIO_COLOR = {1: "#a32d2d", 2: "#ba7517", 3: "#8a7a3a", 4: "#5f5e5a"}

_FONTS = ("<link rel='preconnect' href='https://fonts.googleapis.com'>"
          "<link href='https://fonts.googleapis.com/css2?family=Inter"
          ":wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600"
          "&display=swap' rel='stylesheet'>")

# Google Fonts is a PROGRESSIVE ENHANCEMENT, never a dependency. Offline, on a
# locked-down corporate machine, or behind a proxy that blocks
# fonts.googleapis.com, the link above simply fails — so the stacks below have
# to carry the design on their own. The mono stack matters most: every tag and
# every page_header context line is mono, and a bare `monospace` fallback
# lands on Courier, which is what actually made the offline app look broken.
_SANS = ("'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI Variable Text',"
         " 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif")
_MONO = ("'IBM Plex Mono', ui-monospace, 'Cascadia Mono', 'Segoe UI Mono',"
         " 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace")
# Same stack for inline style='…' attributes, which are single-quote
# delimited — so the family names must stay unquoted. Legal CSS: every name
# here is a sequence of valid identifiers.
_MONO_ATTR = ("IBM Plex Mono,ui-monospace,Cascadia Mono,Segoe UI Mono,"
              "SF Mono,Menlo,Consolas,Liberation Mono,monospace")

_BASE_CSS = f"""
<style>
html, body, [class*="css"], .stApp {{ font-family: {_SANS}; }}
/* calm light canvas — enforced so it never falls back to a dark base */
.stApp {{ background: {PAGE_BG} !important; color: {SLATE}; }}
[data-testid="stAppViewContainer"] {{ background: {PAGE_BG}; }}
[data-testid="stMain"] p, [data-testid="stMain"] li,
[data-testid="stMain"] label {{ color: {SLATE}; }}
code, pre {{ font-family: {_MONO}; }}
h1 {{ font-weight: 700 !important; letter-spacing: -0.3px; color: {SLATE} !important; }}
h2, h3 {{ font-weight: 600 !important; color: {SLATE} !important; }}
/* top header: white with a thin Energy Red brand line */
[data-testid="stHeader"] {{ background: #fff; border-bottom: 3px solid {RED}; }}
[data-testid="stHeader"] * {{ color: {SLATE}; }}
/* sidebar: white, readable slate text, moss highlight on the active page */
[data-testid="stSidebar"] {{ background: #ffffff !important;
  border-right: 1px solid {BORDER}; }}
[data-testid="stSidebar"] * {{ color: {SLATE} !important; }}
[data-testid="stSidebarNav"] a {{ border-radius: 6px; }}
[data-testid="stSidebarNav"] a:hover {{ background: #eef4f4; }}
[data-testid="stSidebarNav"] [aria-current="page"] {{
  background: #e1f0f1; box-shadow: inset 3px 0 0 {MOSS}; }}
[data-testid="stSidebarNav"] [aria-current="page"] span {{ color: {MOSS} !important;
  font-weight: 600; }}
/* bordered containers = flat white cards */
[data-testid="stVerticalBlockBorderWrapper"] {{
  background: {CARD_BG}; border: 1px solid {BORDER} !important;
  border-radius: 10px; box-shadow: none;
}}
/* buttons: quiet outline, moss on hover; primary buttons solid moss */
.stButton > button {{
  background: #fff; border: 1px solid {BORDER}; border-radius: 6px;
  font-weight: 600; color: {SLATE};
}}
.stButton > button:hover {{ border-color: {MOSS}; color: {MOSS}; }}
.stButton > button[kind="primary"] {{
  background: {MOSS}; border-color: {MOSS}; color: #fff;
}}
.stButton > button[kind="primary"]:hover {{ background: {MOSS_DARK};
  border-color: {MOSS_DARK}; color: #fff; }}
/* tabs -> EDS underline style */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  background: transparent; gap: 18px; border-bottom: 1px solid {BORDER};
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
  padding: 6px 2px; color: {MUTED}; font-weight: 500;
}}
[data-testid="stTabs"] [aria-selected="true"] {{
  color: {MOSS}; font-weight: 600; background: transparent; box-shadow: none;
}}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{
  background: {MOSS}; height: 2px; display: block;
}}
[data-testid="stTabs"] [data-baseweb="tab-border"] {{ display: none; }}
/* metrics */
[data-testid="stMetricValue"] {{ color: {SLATE}; font-weight: 700; }}
[data-testid="stMetricLabel"] {{ color: {FAINT}; }}
/* tables */
thead tr th {{ font-size: 11px !important; letter-spacing: 0.8px;
  text-transform: uppercase; color: {FAINT} !important;
  background: #fbfcfd !important; }}
/* expanders as cards */
[data-testid="stExpander"] details {{
  background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 10px;
}}
/* inputs focus in moss, links in moss */
a, a:visited {{ color: {MOSS}; }}
[data-testid="stCaptionContainer"] {{ color: {MUTED}; }}
[data-baseweb="select"] > div, .stTextInput input, .stNumberInput input {{
  border-color: {BORDER}; }}
</style>
"""


def inject_css() -> None:
    """Base theme — call once at the top of app.py (applies to every page)."""
    st.markdown(_FONTS + _BASE_CSS, unsafe_allow_html=True)


def inject_dark_css() -> None:
    """Deprecated: the app now uses ONE light theme everywhere. Kept as a
    no-op so any stale import keeps working."""
    return None


# ---- building blocks --------------------------------------------------------

def page_header(title: str, context: str,
                kpis: list[tuple[str, str]] | None = None,
                kpi_colors: dict[int, str] | None = None) -> None:
    """White header card: title + mono context line + right-aligned KPI strip
    with thin dividers. kpis: [("KOMPONENTER", "77"), ("FUNN", "9"), ...]
    kpi_colors: {index: "#a32d2d"} to colour specific KPI values."""
    kpi_colors = kpi_colors or {}
    kpi_html = "".join(
        (f"<div style='width:1px;background:{BORDER};margin:0 14px'></div>" if i else "")
        + f"<div style='text-align:right'>"
          f"<div style='font-size:24px;font-weight:700;line-height:1.1;"
          f"color:{kpi_colors.get(i, SLATE)}'>{v}</div>"
          f"<div style='font-size:11px;color:{FAINT};font-weight:600;"
          f"letter-spacing:0.5px'>{k}</div></div>"
        for i, (k, v) in enumerate(kpis or []))
    st.markdown(
        f"<div style='background:{CARD_BG};border:1px solid {BORDER};"
        f"border-radius:10px;padding:16px 22px;display:flex;align-items:center;"
        f"justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:10px'>"
        f"<div><div style='font-size:22px;font-weight:700;letter-spacing:-0.3px;"
        f"color:{SLATE}'>{title}</div>"
        f"<div style='font-size:12.5px;color:{MUTED};margin-top:2px;"
        f"font-family:{_MONO_ATTR}'>{context}</div></div>"
        f"<div style='display:flex;align-items:center'>{kpi_html}</div></div>",
        unsafe_allow_html=True)


def chip(tag: str, category: str = "other") -> str:
    bg, bd, fg = CAT_CHIP.get(category, CAT_CHIP["other"])
    return (f"<span style='background:{bg};border:1px solid {bd};color:{fg};"
            f"border-radius:4px;padding:2px 8px;margin:2px;display:inline-block;"
            f"font-family:{_MONO_ATTR};font-size:12px'>{tag}</span>")


def chips(tags, by_tag) -> str:
    """Drop-in replacement for the chips() helpers in the pages."""
    if not tags:
        return f"<i style='color:{FAINT};font-size:13px'>none</i>"
    return " ".join(chip(t, getattr(by_tag.get(t), "category", "other")
                         if hasattr(by_tag, "get") else "other") for t in tags)


def pill(text: str, kind: str = "neutral") -> str:
    """Status pill: ok (green), warn (amber), danger (red), neutral."""
    bg, bd, fg = PILL.get(kind, PILL["neutral"])
    return (f"<span style='background:{bg};border:1px solid {bd};color:{fg};"
            f"border-radius:100px;padding:2px 10px;font-size:11.5px;"
            f"font-weight:600'>{text}</span>")


def prio_badge(priority: int, direction: str | None = None) -> str:
    """P1..P4 badge; P1 red is reserved for critical/trip."""
    arrow = {"high": "▲", "low": "▼"}.get(direction or "", "")
    c = PRIO_COLOR.get(priority, "#5f5e5a")
    return (f"<span style='background:{c};color:#fff;border-radius:4px;"
            f"padding:1px 7px;font-size:11px;font-weight:600;"
            f"font-family:{_MONO_ATTR}'>P{priority}{arrow}</span>")

# --------------------------------------------------------------------------- #
#  Zoomable image viewer (shared)                                             #
# --------------------------------------------------------------------------- #
from pathlib import Path as _Path


@st.cache_data(show_spinner=False)
def _png_b64(path: str, mtime: float) -> str:
    import base64
    return base64.b64encode(_Path(path).read_bytes()).decode()


def zoomable_image(png_path: str, height: int = 640) -> None:
    """Inline pan/zoom image viewer — scroll = zoom toward the pointer, drag =
    pan, double-click = reset. Pure HTML/JS in a components iframe, no extra
    dependencies. Shared so any page can show a zoomable drawing."""
    import streamlit.components.v1 as components
    b64 = _png_b64(png_path, _Path(png_path).stat().st_mtime)
    components.html(f"""
<div id="vp" style="width:100%;height:{height - 20}px;overflow:hidden;
     border:1px solid #d0d5da;border-radius:8px;background:#fafbfc;
     cursor:grab;position:relative;user-select:none">
  <div id="wrap" style="transform-origin:0 0;position:absolute;left:0;top:0;
       width:100%">
    <img id="im" src="data:image/png;base64,{b64}" draggable="false"
         style="max-width:none;width:100%;display:block"/>
  </div>
  <div style="position:absolute;right:8px;bottom:8px;color:#555;
       font:11px sans-serif;background:#ffffffcc;padding:3px 8px;
       border-radius:6px;pointer-events:none">
    scroll = zoom &nbsp;·&nbsp; drag = pan &nbsp;·&nbsp; double-click = reset
  </div>
</div>
<script>
const vp=document.getElementById("vp"),im=document.getElementById("wrap");
let s=1,tx=0,ty=0,drag=false,sx=0,sy=0;
function apply(){{im.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{s}})`;}}
vp.addEventListener("wheel",e=>{{
  e.preventDefault();
  const r=vp.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=e.deltaY<0?1.25:0.8,ns=Math.min(Math.max(s*f,1),40);
  tx=mx-(mx-tx)*(ns/s); ty=my-(my-ty)*(ns/s); s=ns; apply();
}},{{passive:false}});
vp.addEventListener("mousedown",e=>{{drag=true;sx=e.clientX-tx;sy=e.clientY-ty;
  vp.style.cursor="grabbing";}});
window.addEventListener("mousemove",e=>{{if(!drag)return;
  tx=e.clientX-sx;ty=e.clientY-sy;apply();}});
window.addEventListener("mouseup",()=>{{drag=false;vp.style.cursor="grab";}});
vp.addEventListener("dblclick",()=>{{s=1;tx=0;ty=0;apply();}});
</script>""", height=height)
