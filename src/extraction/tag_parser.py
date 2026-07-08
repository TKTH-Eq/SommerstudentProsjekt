# src/extraction/tag_parser.py
"""Turn raw SCD tags like '42-XV2053A' into structured, typed objects."""
import re
from dataclasses import dataclass, field

VARIABLE = {"A":"analysis","E":"sensor","F":"flow","H":"hand/manual","J":"power",
    "K":"time","L":"level","P":"pressure","S":"speed/safety","T":"temperature",
    "U":"multivariable","V":"vibration","X":"unclassified","Z":"position"}

# type_code -> (meaning, flags)
KNOWN = {
    "XV":("on/off shutdown valve",{"valve":True}),
    "ESV":("emergency shutdown valve",{"valve":True,"safety":True}),
    "XY":("solenoid / relay",{}), "HV":("hand valve",{"valve":True,"manual":True}),
    "HS":("hand switch",{"manual":True}),
    "HIC":("hand indicating controller",{"manual":True,"controller":True}),
    "PT":("pressure transmitter",{"transmitter":True}),"PI":("pressure indicator",{}),
    "PIT":("pressure transmitter",{"transmitter":True}),
    "PDI":("diff-pressure indicator",{}),
    "TT":("temperature transmitter",{"transmitter":True}),"TI":("temperature indicator",{}),
    "TIT":("temperature transmitter",{"transmitter":True}),
    "FT":("flow transmitter",{"transmitter":True}),"FI":("flow indicator",{}),
    "FIT":("flow transmitter",{"transmitter":True}),
    "LT":("level transmitter",{"transmitter":True}),"LI":("level indicator",{}),
    "AIT":("analyser transmitter",{"transmitter":True}),
    "ZSH":("valve position switch, open",{"switch":True,"safety":True}),
    "ZSL":("valve position switch, closed",{"switch":True,"safety":True}),
    "XSH":("status switch, high",{"switch":True,"safety":True}),
    "XSL":("status switch, low",{"switch":True,"safety":True}),
    "FSH":("flow switch, high",{"switch":True,"safety":True}),
}
TAG_RE = re.compile(r"\b(\d{2})-([A-Z]{1,3})(\d{2,4})([A-Z]?)\b")

@dataclass
class TaggedObject:
    tag: str; system: str; type_code: str; loop: str; suffix: str
    description: str; variable: str
    flags: dict = field(default_factory=dict)
    source_file: str = ""

def parse_tag(raw: str, source_file: str = "") -> TaggedObject | None:
    m = TAG_RE.search(raw)
    if not m:
        return None
    system, type_code, loop, suffix = m.groups()
    desc, flags = KNOWN.get(type_code, (VARIABLE.get(type_code[0], "unknown"), {}))
    return TaggedObject(f"{system}-{type_code}{loop}{suffix}", system, type_code,
        loop, suffix, desc, VARIABLE.get(type_code[0], "unknown"),
        dict(flags), source_file)