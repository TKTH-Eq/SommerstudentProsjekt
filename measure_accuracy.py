"""
Measure extraction accuracy against a manual ground-truth set.

Put your cleaned truth in  ground_truth.txt  (one tag per line; blank lines and
lines starting with # are ignored). Then:

    python measure_accuracy.py                 # deterministic + 1 vision run
    python measure_accuracy.py --runs 3        # union 3 vision runs (more robust)

Reports precision / recall / F1 per category (instrument, line, other) for the
deterministic extractor and for vision, plus the specific tags each one missed
or produced that are not in the truth.

Precision = of what the method reported, how much is correct.
Recall    = of the true tags, how many the method found.
"""
import sys, os, re
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from dotenv import load_dotenv
load_dotenv()

from config import ALL_TYPES
from extraction.tag_extractor import extract_tags

PDF = "data/raw/P&ID/C025-V-HO27-P-_E-001-01.PDF"
GROUND_TRUTH = "ground_truth.txt"
runs = 1
if "--runs" in sys.argv:
    _i = sys.argv.index("--runs")
    if _i + 1 < len(sys.argv):
        runs = int(sys.argv[_i + 1])


def normalize(tag):
    """Return a set of normalized tags (expands A/B combined forms)."""
    t = tag.strip().upper().replace(" ", "")
    t = t.split(".")[0]                          # drop .AHH / .ALL
    t = re.sub(r"\((?:G|T|M)\)", "", t)          # drop (G)/(T)/(M)
    m = re.match(r"(.+?)([A-Z])/([A-Z])$", t)    # 27-PT4250A/B -> A and B
    if m:
        return {m.group(1) + m.group(2), m.group(1) + m.group(3)}
    return {t} if t else set()


def load_set(strings):
    out = set()
    for s in strings:
        out |= normalize(s)
    return out


def category(tag):
    core = tag.split("-")[-1]
    if re.fullmatch(r"\d{3,6}[A-Z]{1,3}", core):
        return "line"
    if re.fullmatch(r"[A-Z]{2}\d{5,6}", core):
        return "line"
    m = re.fullmatch(r"([A-Z]{2,4})\d{2,4}[A-Z]?", core)
    if m and m.group(1) in ALL_TYPES:
        return "instrument"
    return "other"


def by_category(tags):
    d = defaultdict(set)
    for t in tags:
        d[category(t)].add(t)
    return d


def score(truth, found):
    tp, fp, fn = truth & found, found - truth, truth - found
    p = len(tp) / len(found) if found else 0.0
    r = len(tp) / len(truth) if truth else 0.0
    f1 = 2*p*r/(p+r) if (p+r) else 0.0
    return p, r, f1, sorted(fn), sorted(fp)


def report(name, truth_cat, found_cat):
    print(f"\n=== {name} ===")
    print(f"{'category':12} {'truth':>6} {'found':>6} {'prec':>6} {'recall':>7} {'F1':>6}")
    for cat in ("instrument", "line", "other"):
        truth, found = truth_cat.get(cat, set()), found_cat.get(cat, set())
        if not truth and not found:
            continue
        p, r, f1, fn, fp = score(truth, found)
        print(f"{cat:12} {len(truth):>6} {len(found):>6} {p:>6.0%} {r:>7.0%} {f1:>6.0%}")
        if fn:
            print(f"    missed ({len(fn)}): {fn}")
        if fp:
            print(f"    extra, not in truth ({len(fp)}): {fp}")


def run_vision(pdf, n):
    from extraction.vision_extract import extract_tags_vision
    acc = set()
    for i in range(n):
        acc |= load_set(extract_tags_vision(pdf))
    return acc


def main():
    if not os.path.exists(GROUND_TRUTH):
        sys.exit(f"Missing {GROUND_TRUTH} — one tag per line.")
    lines = [l.strip() for l in open(GROUND_TRUTH, encoding="utf-8")
             if l.strip() and not l.startswith("#")]
    truth = load_set(lines)
    truth_cat = by_category(truth)
    print(f"Ground truth: {len(truth)} tags "
          f"(instrument {len(truth_cat['instrument'])}, "
          f"line {len(truth_cat['line'])}, other {len(truth_cat['other'])})")

    det = load_set(extract_tags(PDF))
    report("DETERMINISTIC", truth_cat, by_category(det))

    try:
        vis = run_vision(PDF, runs)
        report(f"VISION (union of {runs} run{'s' if runs>1 else ''})",
               truth_cat, by_category(vis))
        report("COMBINED (deterministic ∪ vision)", truth_cat, by_category(det | vis))
    except Exception as e:
        import traceback
        print("\n[vision failed — full error below]")
        traceback.print_exc()


if __name__ == "__main__":
    main()