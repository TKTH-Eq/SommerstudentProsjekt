"""The core data object: one tagged component or instrument."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from config import categorise

_TAG = re.compile(r"^(\d{2})-([A-Z]{2,4})(\d{3,4})([A-Z]?)$")


@dataclass
class EngineeringObject:
    tag: str                       # full tag, e.g. "27-PT4805"
    system: str = ""               # "27"
    type_code: str = ""            # "PT"
    number: str = ""               # "4805"
    suffix: str = ""               # "A"/"B"/"" (redundancy leg)
    category: str = "other"        # input/logic/output/equipment/other
    source: str = ""               # "P&ID" / "SCD" / filename
    confidence: float = 1.0

    @classmethod
    def from_tag(cls, tag: str, source: str = "", confidence: float = 1.0):
        m = _TAG.match(tag.strip().upper())
        if not m:
            return cls(tag=tag.strip().upper(), source=source, confidence=confidence)
        system, tc, num, suf = m.groups()
        return cls(tag=f"{system}-{tc}{num}{suf}", system=system, type_code=tc,
                   number=num, suffix=suf, category=categorise(tc),
                   source=source, confidence=confidence)

    @property
    def loop(self) -> str:
        """Loop id = system + number (redundant legs A/B share a loop)."""
        return f"{self.system}-{self.number}" if self.number else self.tag

    # --- alarm semantics derived from the tag (see analysis.alarm_priority) ---
    @property
    def _alarm(self) -> dict:
        from analysis.alarm_priority import alarm_semantics
        return alarm_semantics(self.type_code)

    @property
    def alarm_direction(self) -> str | None:
        """'high' / 'low' / None — from the tag's H/HH/L/LL annotation."""
        return self._alarm["direction"]

    @property
    def alarm_level(self) -> str | None:
        """'trip' (HH/LL) / 'alarm' (single H/L) / None."""
        return self._alarm["level"]

    @property
    def priority(self) -> int:
        """Proxy alarm priority 1..4 (1 = critical), derived from the tag."""
        return self._alarm["priority"]

    @property
    def priority_label(self) -> str:
        return self._alarm["priority_label"]

    def __hash__(self):
        return hash(self.tag)