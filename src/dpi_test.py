import os
os.environ["HULDRA_VISION_FRESH"] = "1"   # tving friske 300-dpi-kall forbi cachen

import sys, pathlib
sys.path.insert(0, "src")
from extraction.vision_extract import extract_tags_vision

for name in ["C025-W-HO13-P-_E-004-01.PDF",
             "C025-V-HO27-P-_E-001-01.PDF",
             "C025-W-HO82-P-_U-001-01.PDF"]:
    pdf = next(pathlib.Path("data/raw").rglob(name), None)
    if pdf is None:
        print(f"--- {name}: IKKE FUNNET under data/raw ---")
        continue
    print(f"--- {name} (300 dpi) ---")
    try:
        tags = extract_tags_vision(str(pdf), dpi=300)
        print(f"{len(tags)} tags:")
        for t in tags:
            print("  ", t)
    except Exception as e:
        print(f"feilet: {e}")