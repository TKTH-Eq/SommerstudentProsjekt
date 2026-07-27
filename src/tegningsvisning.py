"""
src/tegningsvisning.py
=====================================================================
View layer for the Drawing analysis page: show the ORIGINAL drawing (with
text), draw the model's findings on top of it, and let the user zoom and pan.

Why: classify_drawing.py erases the text layer before detection, so the
proof image is drawn on a text-free working copy. For engineering review
the human needs the text — tag numbers, line numbers, notes — to judge
whether a finding is correct.

How it lines up:
  {stem}_detections.json carries "bbox_orig" = pixels in the drawing as
  rendered at the analysis DPI. Re-render the PDF at that same DPI *without*
  the text mask and the boxes land exactly right. The DPI of the run is
  therefore stored in {stem}_run.json (see save_run_meta) so the view never
  has to guess.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html as _html
from PIL import Image, ImageDraw, ImageFont

# Same colors classify_drawing uses for the proof image, but in RGB
# (the OpenCV tuples there are BGR). Kept in sync by hand — change them
# there and they must change here.
CLASS_RGB = {
    "gate_open":       (0, 170, 0),
    "gate_closed":     (220, 0, 0),
    "ball_valve":      (255, 140, 0),
    "ball_open":       (255, 140, 0),
    "ball_closed":     (180, 95, 0),
    "globe_valve":     (200, 0, 200),
    "check_valve":     (0, 180, 180),
    "butterfly_valve": (255, 0, 150),
    "reducer":         (139, 69, 19),
    "other_valve":     (0, 120, 200),
}
_MAX_PANZOOM_PX = 2600      # downscale for the overview shown in the browser


# ------------------------------------------------------------------- run meta
def _run_meta_path(results_dir: Path, drawing: Path) -> Path:
    return Path(results_dir) / f"{drawing.stem}_run.json"


def save_run_meta(results_dir: Path, drawing: Path, dpi: int) -> None:
    """Remember which DPI the findings were computed at. Without this the
    view has to guess, and boxes land in the wrong place if the user changes
    the DPI field after a run."""
    p = _run_meta_path(results_dir, drawing)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"dpi": int(dpi), "pdf": drawing.name}),
                 encoding="utf-8")


def load_run_dpi(results_dir: Path, drawing: Path) -> int | None:
    p = _run_meta_path(results_dir, drawing)
    if not p.exists():
        return None
    try:
        return int(json.loads(p.read_text(encoding="utf-8"))["dpi"])
    except Exception:                                   # noqa: BLE001
        return None


# ------------------------------------------------------------------ rendering
@st.cache_data(show_spinner=False, max_entries=4)
def _render_original(path_str: str, mtime: float, dpi: int) -> bytes:
    """Render page 1 of the PDF at the given DPI, WITH text. Returns PNG
    bytes (bytes cache safely; PIL objects do not)."""
    import pypdfium2 as pdfium
    page = pdfium.PdfDocument(path_str)[0]
    im = page.render(scale=dpi / 72.0).to_pil().convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def original_image(pdf: Path, dpi: int) -> Image.Image:
    data = _render_original(str(pdf), pdf.stat().st_mtime, int(dpi))
    return Image.open(io.BytesIO(data)).convert("RGB")


def load_detections(det_path: Path) -> list[dict]:
    if not Path(det_path).exists():
        return []
    try:
        return json.loads(Path(det_path).read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001
        return []


# -------------------------------------------------------------------- overlay
def draw_overlay(img: Image.Image, dets: list[dict], *,
                 show_classes: set[str] | None = None,
                 min_conf: float = 0.0,
                 show_confidence: bool = False,
                 width: int = 3) -> Image.Image:
    """Draw the findings on a copy of the image. bbox_orig must be in the
    same pixel space as img (i.e. the DPI the analysis used)."""
    out = img.copy()
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default(size=max(11, width * 5))
    except TypeError:                                   # older Pillow
        font = ImageFont.load_default()

    for det in dets:
        cls = det.get("cls")
        if show_classes is not None and cls not in show_classes:
            continue
        if float(det.get("conf", 0.0)) < min_conf:
            continue
        box = det.get("bbox_orig")
        if not box:
            continue
        x0, y0, x1, y1 = (int(v) for v in box)
        color = CLASS_RGB.get(cls, (0, 0, 0))
        # confident = thick frame, possible = thin, as in the proof image
        w = width if det.get("tier", "confident") in ("confident", "sikker") \
            else max(width - 1, 1)
        pad = width                      # breathing room so the symbol stays readable
        d.rectangle([x0 - pad, y0 - pad, x1 + pad, y1 + pad], outline=color, width=w)
        if show_confidence:
            d.text((x0 - pad, max(y0 - pad - 14, 0)),
                   f"{float(det.get('conf', 0)):.2f}", fill=color, font=font)
    return out


def crop_around(img: Image.Image, bbox, margin: float = 5.0,
                min_side: int = 640) -> Image.Image:
    """Cut out the area around a box, with margin measured in box widths,
    and enlarge small crops so they are readable on screen."""
    x0, y0, x1, y1 = (int(v) for v in bbox)
    s = max(x1 - x0, y1 - y0, 1)
    m = int(s * margin)
    box = (max(x0 - m, 0), max(y0 - m, 0),
           min(x1 + m, img.width), min(y1 + m, img.height))
    out = img.crop(box)
    if out.width < min_side:
        k = min_side / max(out.width, 1)
        out = out.resize((int(out.width * k), int(out.height * k)), Image.LANCZOS)
    return out


# ------------------------------------------------------------ zoom in browser
def _b64_png(img: Image.Image, max_side: int = _MAX_PANZOOM_PX) -> tuple[str, int, int]:
    im = img
    if max(im.width, im.height) > max_side:
        k = max_side / max(im.width, im.height)
        im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
    # line drawings compress very well as palette images
    small = im.convert("P", palette=Image.ADAPTIVE, colors=128)
    buf = io.BytesIO()
    small.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), im.width, im.height


def panzoom(img: Image.Image, height: int = 620, key: str = "pz") -> None:
    """Overview with wheel zoom and drag to pan. The image is downscaled for
    the browser; use the detail view for full resolution."""
    b64, w, h = _b64_png(img)
    html = f"""
<style>
  .pz-frame {{ border:1px solid #c9ccd1; border-radius:6px; overflow:hidden;
               background:#fff; position:relative; height:{height}px; }}
  .pz-frame img {{ position:absolute; top:0; left:0; transform-origin:0 0;
                   user-select:none; -webkit-user-drag:none; }}
  .pz-bar {{ display:flex; gap:8px; align-items:center; margin-top:6px;
             font:13px/1.4 system-ui,-apple-system,Segoe UI,sans-serif; color:#444; }}
  .pz-bar button {{ font:inherit; padding:3px 10px; border:1px solid #c9ccd1;
                    border-radius:5px; background:#f6f7f8; cursor:pointer; }}
  .pz-bar button:focus-visible {{ outline:2px solid #0b6; outline-offset:2px; }}
</style>
<div class="pz-frame" id="{key}-frame">
  <img id="{key}-img" src="data:image/png;base64,{b64}" width="{w}" height="{h}"
       alt="Drawing with the model's findings">
</div>
<div class="pz-bar">
  <button id="{key}-reset" type="button">Fit to window</button>
  <button id="{key}-in" type="button">+</button>
  <button id="{key}-out" type="button">&minus;</button>
  <span id="{key}-lvl">100 %</span>
  <span style="color:#888">· scroll to zoom, drag to move, double-click to zoom in</span>
</div>
<script>
(function() {{
  const frame = document.getElementById("{key}-frame");
  const im    = document.getElementById("{key}-img");
  const lvl   = document.getElementById("{key}-lvl");
  const IW = {w}, IH = {h};
  let fit = 1, s = 1, tx = 0, ty = 0, drag = null;

  function apply() {{
    im.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + s + ")";
    lvl.textContent = Math.round(s / fit * 100) + " %";
  }}
  function reset() {{
    fit = Math.min(frame.clientWidth / IW, frame.clientHeight / IH);
    s = fit;
    tx = (frame.clientWidth - IW * s) / 2;
    ty = (frame.clientHeight - IH * s) / 2;
    apply();
  }}
  function zoomAt(cx, cy, k) {{
    const ns = Math.min(Math.max(s * k, fit * 0.8), fit * 30);
    tx = cx - (cx - tx) * (ns / s);
    ty = cy - (cy - ty) * (ns / s);
    s = ns; apply();
  }}
  frame.addEventListener("wheel", e => {{
    e.preventDefault();
    const r = frame.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015));
  }}, {{ passive: false }});
  frame.addEventListener("dblclick", e => {{
    const r = frame.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, 1.8);
  }});
  frame.addEventListener("pointerdown", e => {{
    drag = {{ x: e.clientX - tx, y: e.clientY - ty }};
    frame.setPointerCapture(e.pointerId); frame.style.cursor = "grabbing";
  }});
  frame.addEventListener("pointermove", e => {{
    if (!drag) return;
    tx = e.clientX - drag.x; ty = e.clientY - drag.y; apply();
  }});
  frame.addEventListener("pointerup", () => {{ drag = null; frame.style.cursor = "grab"; }});
  document.getElementById("{key}-reset").onclick = reset;
  document.getElementById("{key}-in").onclick  = () =>
    zoomAt(frame.clientWidth / 2, frame.clientHeight / 2, 1.4);
  document.getElementById("{key}-out").onclick = () =>
    zoomAt(frame.clientWidth / 2, frame.clientHeight / 2, 1 / 1.4);
  frame.style.cursor = "grab";
  if (im.complete) reset(); else im.onload = reset;
  window.addEventListener("resize", reset);
}})();
</script>
"""
    _html(html, height=height + 52, scrolling=False)


# ----------------------------------------------------------------- main panel
def view_panel(pdf: Path, proof_path: Path, det_path: Path,
               results_dir: Path, *, fallback_dpi: int,
               class_info: dict, color_legend: str) -> None:
    """The whole «Where on the drawing?» block: pick a view, filter the
    findings, zoom the overview, and step through findings at full
    resolution."""
    dets = load_detections(det_path)
    run_dpi = load_run_dpi(results_dir, pdf)
    dpi = run_dpi or fallback_dpi

    view = st.radio(
        "View", ["Original + findings", "Original", "What the model saw"],
        horizontal=True, key="tv_view",
        help="The model reads a text-free copy. The original shows the tag "
             "numbers and notes you need to judge the findings.")

    if view == "What the model saw":
        if Path(proof_path).exists():
            image = Image.open(proof_path).convert("RGB")
        else:
            st.warning("Proof image not found.")
            return
    else:
        try:
            image = original_image(pdf, dpi)
        except Exception as e:                          # noqa: BLE001
            st.error(f"Could not render the original: {e}")
            return
        if view == "Original + findings" and dets:
            classes = sorted({d["cls"] for d in dets if d.get("cls")})
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                chosen = st.multiselect(
                    "Classes", classes, default=classes,
                    format_func=lambda c: class_info.get(c, (c,))[0],
                    key="tv_classes")
            with c2:
                min_conf = st.slider("Minimum confidence", 0.0, 1.0, 0.0, 0.05,
                                     key="tv_conf")
            with c3:
                show_conf = st.checkbox("Show confidence", value=False,
                                        key="tv_showconf")
            image = draw_overlay(image, dets, show_classes=set(chosen),
                                 min_conf=min_conf, show_confidence=show_conf,
                                 width=max(2, round(dpi / 70)))

    if run_dpi is None:
        st.caption(f"No stored DPI for this run — assuming {dpi} DPI. "
                   "If the boxes are offset, rerun the analysis.")

    panzoom(image, height=620, key="tv")
    st.caption("Color legend: " + color_legend +
               " · The overview is downscaled; use the detail view below for "
               "full resolution.")

    if not dets:
        return

    # ---- detail view: one finding at a time, at full resolution
    with st.expander("Inspect one finding at a time"):
        def _label(i: int) -> str:
            d = dets[i]
            name = class_info.get(d["cls"], (d["cls"],))[0]
            x, y = d["bbox_orig"][0], d["bbox_orig"][1]
            return (f"{i + 1}. {name} · {float(d.get('conf', 0)):.2f} "
                    f"· {d.get('tier', 'confident')} · ({x}, {y})")

        order = sorted(range(len(dets)),
                       key=lambda i: -float(dets[i].get("conf", 0)))
        i = st.selectbox("Finding", order, format_func=_label, key="tv_finding")
        margin = st.slider("Context around the finding", 2.0, 15.0, 5.0, 0.5,
                           key="tv_margin",
                           help="How many symbol widths of drawing to keep "
                                "around the box.")
        d = dets[i]

        try:
            orig = original_image(pdf, dpi)
        except Exception as e:                          # noqa: BLE001
            st.error(f"Could not render the original: {e}")
            return
        marked = draw_overlay(orig, [d], width=max(2, round(dpi / 70)))

        k1, k2 = st.columns(2)
        with k1:
            st.markdown("**The original** — with text")
            st.image(crop_around(marked, d["bbox_orig"], margin),
                     use_container_width=True)
        with k2:
            st.markdown("**What the model saw** — text erased")
            if Path(proof_path).exists():
                proof = Image.open(proof_path).convert("RGB")
                f = proof.width / orig.width          # working res / original
                pbox = [v * f for v in d["bbox_orig"]]
                st.image(crop_around(proof, pbox, margin), use_container_width=True)
            else:
                st.caption("Proof image missing.")
        st.caption("Where the two differ, you can see why: text that was "
                   "erased may leave a hole the model read as a symbol.")