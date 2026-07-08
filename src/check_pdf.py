# peek_dgn.py — quick text peek, no dependencies, run now
import re
from pathlib import Path

folder = Path("data/raw/SCD")

def read_strings(path, min_len=4):
    data = path.read_bytes()
    out = []
    # ASCII strings
    out += re.findall(rb"[\x20-\x7e]{%d,}" % min_len, data)
    # UTF-16LE strings (common in DGN v8)
    out += re.findall((rb"(?:[\x20-\x7e]\x00){%d,}" % min_len), data)
    result = []
    for s in out:
        try:
            result.append(s.replace(b"\x00", b"").decode("ascii"))
        except Exception:
            pass
    return result

for dgn in sorted(folder.glob("*.DGN")) + sorted(folder.glob("*.dgn")):
    print("=" * 70)
    print(dgn.name)
    strings = read_strings(dgn)

    # Title / type lines
    titles = [s for s in strings if re.search(
        r"CONTROL DIAGRAM|Drawing title|SYSTEM|EXPORT|WATER|GAS|OIL|INJECT|MEG|WELL|SEPARAT|COMPRESS",
        s, re.I)]
    print("  -- titles / system --")
    for t in sorted(set(titles))[:10]:
        print("    ", t.strip())

    # Tags like 42-XV2053, 42-PF50A
    tags = sorted(set(re.findall(r"\b\d{2}-[A-Z]{2,3}\d{3,4}[A-Z]?\b", " ".join(strings))))
    print(f"  -- tags ({len(tags)}) --")
    print("    ", ", ".join(tags[:40]))