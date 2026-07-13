"""Compare vision vs deterministic tag extraction, with vision-only bucketed."""
import sys, os, re
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from dotenv import load_dotenv
load_dotenv()

from config import ALL_TYPES as TYPES
from extraction.tag_extractor import extract_tags
from extraction.vision_extract import extract_tags_vision

pdf = sys.argv[1] if len(sys.argv) > 1 else "data/raw/P&ID/C025-V-HO27-P-_E-001-01.PDF"


def norm(t):
    return t.split(".")[0].replace(" ", "").upper()


def classify(tag):
    """line number | instrument | other."""
    core = tag.split("-")[-1]
    if re.fullmatch(r"\d{3,5}[A-Z]{1,3}", core):      # 4502PV  (digits then letters)
        return "line"
    if re.fullmatch(r"[A-Z]{2}\d{5,6}", core):        # PV274506 (letters then long number)
        return "line"
    m = re.fullmatch(r"([A-Z]{2,4})(\d{2,4})([A-Z]?)", core)
    if m and m.group(1) in TYPES:                     # PT4805, KA50, SI4203
        return "instrument"
    return "other"


det = {norm(t) for t in extract_tags(pdf)}
vis = {norm(t) for t in extract_tags_vision(pdf)}

both = sorted(det & vis)
det_only = sorted(det - vis)
vis_only = sorted(vis - det)

buckets = defaultdict(list)
for t in vis_only:
    buckets[classify(t)].append(t)

print(f"deterministic tags : {len(det)}")
print(f"vision tags        : {len(vis)}")
print(f"AGREE (on both)    : {len(both)}   ({100*len(both)//max(len(det),1)}% of deterministic)")
print()
print(f"DETERMINISTIC ONLY ({len(det_only)}) — real tags vision missed:")
print(f"  {det_only}")
print()
print("VISION ONLY, bucketed:")
print(f"  line numbers ({len(buckets['line'])}) — a category the deterministic ignores:")
print(f"    {buckets['line']}")
print(f"  instrument/equipment ({len(buckets['instrument'])}) — vision extended coverage, verify:")
print(f"    {buckets['instrument']}")
print(f"  other / likely misreads ({len(buckets['other'])}) — verify:")
print(f"    {buckets['other']}")