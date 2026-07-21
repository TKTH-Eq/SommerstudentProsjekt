#!/usr/bin/env python3
"""
make_synthetic.py — Lager VEILEDET treningsdata syntetisk fra legendesymbolene:
maskinen trener på tusenvis av utsnitt der fasiten er kjent (vi la symbolet
der selv). Augmentering etterligner ekte tegninger: rørlinjer gjennom
symbolet, rotasjon, skala, strektykkelse, uskarphet og lav-DPI-rastering.

Klasser:
  gate_open    VAL001
  gate_closed  VAL006
  other_valve  andre ventiler fra legenden (ball, globe, needle, check ...)
  background   linjekryss, tekstlignende strøk, piler — ingen ventil

Bruk:
  python make_synthetic.py --templates ../pid-symbol-ai/templates --n 800
"""
import argparse, glob, os, random
import numpy as np
import cv2

SIZE = 64
# templatelister per klasse — VERIFISERT mot legendeteksten (PT-111):
BALL   = ["VAL022", "VAL027"]            # BALL VALVE, OPEN / CLOSED
GLOBE  = ["VAL017", "VAL023"]            # GLOBE VALVE, OPEN / CLOSED
CHECK  = ["VAL033"]                      # CHECK VALVE
BFLY   = ["VAL028"]                      # BUTTERFLY VALVE
RED    = ["FIT005"]                      # REDUCER/EXPANDER (fittinglegenden)
# other_valve SMALNET til sloyfe-familien (nål/plugg/vinkel) — de eksotiske
# formene flyttes til bakgrunn så klassen slutter å være standardsvar for alt rart
OTHER  = ["VAL011", "VAL016",            # needle open/closed
          "VAL007", "VAL012",            # plug open/closed
          "VAL029", "VAL024"]            # angle open/closed
EXOTIC = ["VAL009", "VAL019", "VAL002", "VAL032", "VAL003",
          "VAL004", "VAL005", "VAL008", "VAL010"]  # choke/barstock/membran/Y/3-veis -> bakgrunn

def load_tpl(path):
    """Les mal og ISOLER symbolkjernen (round-1-malene inneholder ramme-rester):
    dropp kant-berørende og ramme-store komponenter, behold klyngen nær midten."""
    t = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if t is None:
        return None
    H, W = t.shape
    n, lab, stats, cent = cv2.connectedComponentsWithStats((t > 0).astype(np.uint8))
    cands = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < 25 or x == 0 or y == 0 or x + w >= W or y + h >= H:
            continue
        if w > 0.6 * W or h > 0.6 * H:
            continue
        d = ((cent[i][0] - W / 2) ** 2 + (cent[i][1] - H / 2) ** 2) ** 0.5
        cands.append((d, i))
    if not cands:
        return None
    # sammensatte symboler (sløyfe + sirkel, vinge + skive) har flere deler:
    # forankre i STØRSTE komponent og ta med alt i nabolaget dens
    main = max(cands, key=lambda di: stats[di[1]][4])[1]
    mx, my, mw, mh, _ = stats[main]
    pad = 0.6 * max(mw, mh)
    keep = np.zeros_like(t)
    for d, i in cands:
        cx, cy = cent[i]
        if mx - pad < cx < mx + mw + pad and my - pad < cy < my + mh + pad:
            keep[lab == i] = 255
    ys, xs = np.where(keep > 0)
    core = keep[ys.min():ys.max()+1, xs.min():xs.max()+1]
    return core if core.shape[0] >= 8 and core.shape[1] >= 8 else None

def place(tpl, rng):
    """Legg symbolet i et 64x64-vindu med realistisk kontekst."""
    canvas = np.zeros((SIZE, SIZE), np.uint8)
    # skala: symbolbredde 45-95 % av vinduet
    w = rng.randint(int(SIZE*0.45), int(SIZE*0.95))
    s = w / tpl.shape[1]
    t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    if rng.random() < 0.5:                      # 90° (ventil på vertikal linje)
        t = np.ascontiguousarray(np.rot90(t))
    th, tw = t.shape
    if th >= SIZE or tw >= SIZE:
        f = (SIZE-4) / max(th, tw)
        t = cv2.resize(t, None, fx=f, fy=f); th, tw = t.shape
    ox = rng.randint(0, SIZE-tw); oy = rng.randint(0, SIZE-th)
    canvas[oy:oy+th, ox:ox+tw] = np.maximum(canvas[oy:oy+th, ox:ox+tw], t)
    # rørlinje gjennom symbolet (som i ekte P&ID)
    if rng.random() < 0.85:
        y = oy + th//2 if tw >= th else None
        lw = rng.randint(1, 3)
        if y is not None:
            cv2.line(canvas, (0, y), (SIZE, y), 255, lw)
        else:
            x = ox + tw//2
            cv2.line(canvas, (x, 0), (x, SIZE), 255, lw)
    return canvas, (ox, oy, tw, th)

def zigzag(canvas, rng):
    """Varmetrasé-stil: sikksakk- eller bølgelinje tvers over vinduet."""
    horiz = rng.random() < 0.5
    amp = rng.randint(2, 5); per = rng.randint(4, 9)
    y0 = rng.randint(6, SIZE - 6); x0 = rng.randint(6, SIZE - 6)
    pts = []
    for t in range(0, SIZE, max(per // 2, 2)):
        off = amp if (t // max(per // 2, 2)) % 2 == 0 else -amp
        pts.append((t, min(max(y0 + off, 0), SIZE - 1)) if horiz
                   else (min(max(x0 + off, 0), SIZE - 1), t))
    for a, b in zip(pts, pts[1:]):
        cv2.line(canvas, a, b, 255, rng.randint(1, 2))
    return canvas

def slash_decoys(canvas, rng):
    """Snarveis-vaksine: enslige skråstreker, spec-merker (dobbel skråstrek)
    og firkant-med-diagonal (⧄) — alt som er 'en halv åpen sløyfe'."""
    kind = rng.random()
    cx, cy = rng.randint(14, SIZE - 14), rng.randint(14, SIZE - 14)
    if kind < 0.45:      # enslig skråstrek, evt. gjennom en rørlinje
        L = rng.randint(5, 12); s = rng.choice([-1, 1])
        cv2.line(canvas, (cx - L, cy + s * L), (cx + L, cy - s * L), 255, rng.randint(1, 2))
        if rng.random() < 0.7:
            cv2.line(canvas, (0, cy), (SIZE, cy), 255, rng.randint(1, 2))
    elif kind < 0.7:     # spec-/størrelsesmerke: to parallelle skråstreker
        L = rng.randint(4, 8); s = rng.choice([-1, 1]); gap = rng.randint(4, 7)
        for off in (0, gap):
            cv2.line(canvas, (cx - L + off, cy + s * L), (cx + L + off, cy - s * L), 255, 2)
        cv2.line(canvas, (0, cy), (SIZE, cy), 255, rng.randint(1, 2))
    else:                # firkant med én diagonal (⧄)
        w = rng.randint(10, 20); h = rng.randint(10, 20)
        cv2.rectangle(canvas, (cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2), 255, rng.randint(1, 2))
        if rng.random() < 0.5:
            cv2.line(canvas, (cx - w // 2, cy + h // 2), (cx + w // 2, cy - h // 2), 255, rng.randint(1, 2))
        else:
            cv2.line(canvas, (cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2), 255, rng.randint(1, 2))
    return canvas

def nozzle_decoys(canvas, rng):
    """Reducer-vaksine: HULE trekanter — spraydyser (terminale, med rørstubb
    inn i flatsiden) og hule pilhoder på linjer. Etter kanonisering ligner
    disse reducerens trapes; her lærer modellen forskjellen."""
    n = rng.randint(1, 3)
    for _ in range(n):
        cx, cy = rng.randint(12, SIZE - 12), rng.randint(12, SIZE - 12)
        L = rng.randint(5, 10)
        d = rng.choice(["opp", "ned", "venstre", "hoyre"])
        if d in ("opp", "ned"):
            s = -1 if d == "opp" else 1
            pts = [(cx - L, cy - s * L), (cx + L, cy - s * L), (cx, cy + s * L)]
            stub = ((cx, cy - s * L), (cx, cy - s * (L + rng.randint(6, 14))))
        else:
            s = -1 if d == "venstre" else 1
            pts = [(cx - s * L, cy - L), (cx - s * L, cy + L), (cx + s * L, cy)]
            stub = ((cx - s * L, cy), (cx - s * (L + rng.randint(6, 14)), cy))
        p = np.array(pts, np.int32)
        cv2.polylines(canvas, [p], True, 255, rng.randint(1, 2))
        if rng.random() < 0.8:
            cv2.line(canvas, stub[0], stub[1], 255, rng.randint(1, 2))
        if rng.random() < 0.3:      # dyserad: nabo-dyse på samme linje
            off = rng.randint(16, 26)
            p2 = p + (np.array([off, 0]) if d in ("opp", "ned") else np.array([0, off]))
            cv2.polylines(canvas, [p2], True, 255, 1)
    return canvas

def clutter(canvas, rng, avoid=None, heavy=False):
    """Tilfeldige nabolinjer/tekststrøk rundt symbolet."""
    n = rng.randint(2, 7) if heavy else rng.randint(0, 3)
    for _ in range(n):
        x0, y0 = rng.randint(0, SIZE), rng.randint(0, SIZE)
        if rng.random() < 0.6:   # rette linjer (rør)
            x1, y1 = (rng.randint(0, SIZE), y0) if rng.random() < 0.5 else (x0, rng.randint(0, SIZE))
        else:                    # korte skrå strøk (tekst/piler)
            x1, y1 = x0 + rng.randint(-14, 14), y0 + rng.randint(-14, 14)
        if avoid:
            ax, ay, aw, ah = avoid
            cx, cy = (x0+x1)/2, (y0+y1)/2
            if ax+3 < cx < ax+aw-3 and ay+3 < cy < ay+ah-3:
                continue
        cv2.line(canvas, (x0, y0), (x1, y1), 255, rng.randint(1, 2))
    return canvas

def arrows_and_shapes(canvas, rng):
    """Bakgrunnsfeller: pilhoder, sirkler, fylte bokser — ting som IKKE er ventiler."""
    k = rng.randint(1, 3)
    for _ in range(k):
        cx, cy = rng.randint(8, SIZE-8), rng.randint(8, SIZE-8)
        r = rng.random()
        if r < 0.35:   # pilhode (fylt trekant)
            d = rng.randint(4, 9); dr = rng.choice([-1, 1])
            pts = np.array([[cx, cy-d//2], [cx, cy+d//2], [cx+dr*d, cy]])
            cv2.fillPoly(canvas, [pts], 255)
        elif r < 0.6:  # instrumentsirkel
            cv2.circle(canvas, (cx, cy), rng.randint(5, 11), 255, rng.randint(1, 2))
        elif r < 0.7:  # instrumentboble: sirkel med korde og indre merker
            rr = rng.randint(7, 13)
            cv2.circle(canvas, (cx, cy), rr, 255, rng.randint(1, 2))
            cv2.line(canvas, (cx - rr, cy), (cx + rr, cy), 255, 1)
            for _ in range(rng.randint(2, 4)):
                x = cx + rng.randint(-rr + 2, rr - 5)
                y = cy + rng.choice([-1, 1]) * rng.randint(2, max(rr - 4, 3))
                cv2.line(canvas, (x, y), (x + rng.randint(2, 4), y), 255, 1)
        elif r < 0.85:  # transmitterboks: firkant med indre streker
            for _ in range(rng.randint(3, 6)):
                x = cx + rng.randint(-10, 10); y = cy + rng.randint(-4, 4)
                cv2.line(canvas, (x, y), (x+rng.randint(2,5), y), 255, 2)
            w, h = rng.randint(9, 15), rng.randint(9, 15)
            cv2.rectangle(canvas, (cx - w, cy - h), (cx + w, cy + h), 255, rng.randint(1, 2))
            for _ in range(rng.randint(2, 4)):
                y = cy + rng.randint(-h + 2, h - 2)
                cv2.line(canvas, (cx - w + 2, y), (cx - w + 2 + rng.randint(3, 2 * w - 4), y), 255, 1)
        else:          # fylt boks m/ slisse
            w, h = rng.randint(8, 16), rng.randint(6, 12)
            cv2.rectangle(canvas, (cx-w, cy-h//2), (cx+w, cy+h//2), 255, -1)
            cv2.line(canvas, (cx-1, cy-h//2), (cx-1, cy+h//2), 0, 2)
    return canvas

def degrade(img, rng):
    """Etterlign ekte rastering: strektykkelse, uskarphet, lav DPI, støy."""
    if rng.random() < 0.4:
        k = np.ones((rng.randint(1, 3),)*2, np.uint8)
        img = cv2.dilate(img, k) if rng.random() < 0.6 else cv2.erode(img, k)
    if rng.random() < 0.7:                       # lav-DPI simulering
        f = rng.uniform(0.45, 0.85)
        small = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        img = cv2.resize(small, (SIZE, SIZE), interpolation=cv2.INTER_CUBIC)
    if rng.random() < 0.6:
        img = cv2.GaussianBlur(img, (3, 3), 0)
    if rng.random() < 0.4:                       # salt/pepper
        m = np.random.default_rng(rng.randint(0, 9999)).random((SIZE, SIZE))
        img = img.copy(); img[m < 0.01] = 255; img[m > 0.995] = 0
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates", default="../pid-symbol-ai/templates")
    ap.add_argument("--n", type=int, default=800, help="eksempler per klasse")
    ap.add_argument("--out", default="synth")
    args = ap.parse_args()
    rng = random.Random(7)

    # gate-symbolene: bruk de RENE sløyfene lært av learn_from_legend.py
    gate_o = cv2.imread("gate_open.png", cv2.IMREAD_GRAYSCALE)
    gate_c = cv2.imread("gate_closed.png", cv2.IMREAD_GRAYSCALE)
    def tpls(codes):
        out = [t for t in (load_tpl(os.path.join(args.templates, f"{c}.png")) for c in codes)
               if t is not None]
        return out
    ball, globe_, check, bfly, others = tpls(BALL), tpls(GLOBE), tpls(CHECK), tpls(BFLY), tpls(OTHER)
    reducers = tpls(RED)
    if gate_o is None or gate_c is None or not others:
        raise SystemExit("fant ikke maler — pek --templates til pid-symbol-ai/templates")

    # "symbol-men-ikke-ventil": fittings og linjesymboler -> background
    import glob as _g
    non_valves = []
    for fp in _g.glob(os.path.join(args.templates, "FIT*.png")) + \
              _g.glob(os.path.join(args.templates, "LIN*.png")):
        if any(c in fp for c in RED):
            continue                     # reducer er egen klasse nå
        t = load_tpl(fp)
        if t is not None:
            non_valves.append(t)
    for c in EXOTIC:                     # eksotiske ventiler -> bakgrunnstrening
        t = load_tpl(os.path.join(args.templates, f"{c}.png"))
        if t is not None:
            non_valves.append(t)
    print(f"[i] {len(non_valves)} ikke-ventil-symboler til bakgrunnstrening")

    plan = {"gate_open": lambda: place(gate_o, rng),
            "gate_closed": lambda: place(gate_c, rng),
            "ball_valve": lambda: place(rng.choice(ball), rng),
            "globe_valve": lambda: place(rng.choice(globe_), rng),
            "check_valve": lambda: place(rng.choice(check), rng),
            "butterfly_valve": lambda: place(rng.choice(bfly), rng),
            "reducer": lambda: place(rng.choice(reducers), rng),
            "other_valve": lambda: place(rng.choice(others), rng)}
    for cls in list(plan) + ["background"]:
        d = os.path.join(args.out, cls); os.makedirs(d, exist_ok=True)
        for i in range(args.n):
            if cls == "background":
                r = rng.random()
                if r < 0.22:
                    canvas = np.zeros((SIZE, SIZE), np.uint8)
                    canvas = slash_decoys(canvas, rng)
                    if rng.random() < 0.4: canvas = slash_decoys(canvas, rng)
                    canvas = clutter(canvas, rng)
                elif r < 0.42:
                    canvas = np.zeros((SIZE, SIZE), np.uint8)
                    canvas = nozzle_decoys(canvas, rng)
                    canvas = clutter(canvas, rng)
                elif non_valves and r < 0.60:
                    canvas, box = place(rng.choice(non_valves), rng)
                    canvas = clutter(canvas, rng, avoid=box)
                elif r < 0.78:
                    canvas = np.zeros((SIZE, SIZE), np.uint8)
                    canvas = zigzag(canvas, rng)
                    if rng.random() < 0.5: canvas = zigzag(canvas, rng)
                    canvas = clutter(canvas, rng)
                else:
                    canvas = np.zeros((SIZE, SIZE), np.uint8)
                    canvas = clutter(canvas, rng, heavy=True)
                    canvas = arrows_and_shapes(canvas, rng)
            else:
                canvas, box = plan[cls]()
                canvas = clutter(canvas, rng, avoid=box)
            img = degrade(canvas, rng)
            cv2.imwrite(os.path.join(d, f"{cls}_{i:04d}.png"), img)
        print(f"[✓] {cls}: {args.n} eksempler")
    print(f"-> {args.out}/")

if __name__ == "__main__":
    main()