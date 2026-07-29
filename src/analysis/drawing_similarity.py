"""
src/analysis/drawing_similarity.py
=====================================================================
Which drawings resemble each other, measured by what the symbol model found
on them.

Two drawings that are both mostly closed ball valves and check valves are
probably the same kind of sheet — two trains of the same utility system, say,
or the same package delivered twice. That is worth knowing for three reasons:

  configuration  a Model Broker pattern that works on one sheet in a group is
                 likely to work on the rest. Group first, configure once.
  review         if you have checked one drawing carefully, its neighbours
                 need less attention than a sheet that resembles nothing.
  odd ones out   a drawing similar to nothing else is either genuinely unusual
                 or the detector failed on it. Both are worth a look, and the
                 second is the more common.

Method, and why it is deliberately plain: counts per class are turned into
proportions (so a big sheet does not simply resemble every other big sheet),
compared with cosine similarity, and grouped by single-linkage agglomeration
at a threshold the user sets. No sklearn, no scipy — numpy only, which is
already in the stack. Thirty lines you can read and argue with beats a
clustering library whose defaults nobody checked.

Single linkage is chosen on purpose: it chains, so a group is "connected by
similarity" rather than "tight around a centre". For finding families of
sheets that is the behaviour you want, and the threshold makes it explicit.

Pure functions, no Streamlit.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


# ------------------------------------------------------------------ loading
def load_profiles(results_dir: Path | str,
                  tiers: tuple[str, ...] = ("confident", "sikker")
                  ) -> dict[str, dict[str, int]]:
    """drawing stem -> {class: count}, read from *_detections.json.

    Detections rather than verdicts, because the tier is needed: a drawing
    whose findings are all "possible" resembles other uncertain drawings for
    reasons that have nothing to do with what is on them. Pass tiers=() to
    count everything.
    """
    out: dict[str, dict[str, int]] = {}
    for f in sorted(Path(results_dir).glob("*_detections.json")):
        try:
            dets = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                       # noqa: BLE001
            continue
        counts: dict[str, int] = {}
        for d in dets:
            if tiers and d.get("tier", "confident") not in tiers:
                continue
            cls = d.get("cls")
            if cls:
                counts[cls] = counts.get(cls, 0) + 1
        if counts:
            out[f.name[:-len("_detections.json")]] = counts
    return out


def to_matrix(profiles: dict[str, dict[str, int]],
              normalise: bool = True) -> tuple[list[str], list[str], np.ndarray]:
    """(drawings, classes, matrix). Rows are drawings, columns are classes.

    Normalised rows turn counts into composition — "what this drawing is made
    of" rather than "how much of it there is". Without that, similarity mostly
    measures sheet size.
    """
    drawings = sorted(profiles)
    classes = sorted({c for p in profiles.values() for c in p})
    m = np.zeros((len(drawings), len(classes)), dtype=float)
    for i, d in enumerate(drawings):
        for j, c in enumerate(classes):
            m[i, j] = profiles[d].get(c, 0)
    if normalise:
        totals = m.sum(axis=1, keepdims=True)
        totals[totals == 0] = 1.0
        m = m / totals
    return drawings, classes, m


# --------------------------------------------------------------- similarity
def cosine_matrix(m: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity, 0..1 for non-negative vectors."""
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = m / norms
    sim = unit @ unit.T
    return np.clip(sim, 0.0, 1.0)


def cluster(labels: list[str], sim: np.ndarray,
            threshold: float = 0.85) -> list[list[str]]:
    """Single-linkage groups: connected components of the graph where an edge
    exists when similarity is at or above the threshold.

    A drawing similar to nothing comes back as a group of one, which is the
    useful answer rather than a missing one.
    """
    n = len(labels)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= threshold:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    groups: dict[int, list[str]] = {}
    for i, lab in enumerate(labels):
        groups.setdefault(find(i), []).append(lab)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))


def neighbours(drawing: str, labels: list[str], sim: np.ndarray,
               top: int = 8) -> list[tuple[str, float]]:
    """The most similar drawings to one, excluding itself."""
    if drawing not in labels:
        return []
    i = labels.index(drawing)
    order = np.argsort(-sim[i])
    return [(labels[j], float(sim[i, j])) for j in order
            if labels[j] != drawing][:top]


def distinctive_classes(drawing: str, profiles: dict[str, dict[str, int]],
                        top: int = 4) -> list[tuple[str, float, float]]:
    """Classes over-represented on this drawing versus the whole set.

    Answers "why is this one different" in the same terms as the grouping:
    (class, share here, share everywhere).
    """
    if drawing not in profiles:
        return []
    here = profiles[drawing]
    here_total = sum(here.values()) or 1
    all_counts: dict[str, int] = {}
    for p in profiles.values():
        for c, n in p.items():
            all_counts[c] = all_counts.get(c, 0) + n
    all_total = sum(all_counts.values()) or 1
    rows = []
    for c, n in here.items():
        mine = n / here_total
        theirs = all_counts.get(c, 0) / all_total
        rows.append((c, mine, theirs))
    rows.sort(key=lambda r: -(r[1] - r[2]))
    return rows[:top]


def summary(profiles: dict[str, dict[str, int]], threshold: float = 0.85
            ) -> dict:
    """Everything a page needs, in one call."""
    drawings, classes, m = to_matrix(profiles)
    sim = cosine_matrix(m)
    groups = cluster(drawings, sim, threshold)
    return {"drawings": drawings, "classes": classes, "matrix": m,
            "similarity": sim, "groups": groups,
            "singletons": [g[0] for g in groups if len(g) == 1]}


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "gatevalve-ai/results"
    prof = load_profiles(src)
    if not prof:
        print(f"Fant ingen *_detections.json under {src}")
        raise SystemExit(1)
    s = summary(prof, threshold=float(sys.argv[2]) if len(sys.argv) > 2 else 0.85)
    print(f"{len(s['drawings'])} tegninger · {len(s['classes'])} klasser\n")
    for i, g in enumerate(s["groups"], 1):
        tag = "alene" if len(g) == 1 else f"{len(g)} tegninger"
        print(f"Gruppe {i} ({tag}):")
        for d in g:
            top = distinctive_classes(d, prof, 2)
            hint = ", ".join(f"{c} {a:.0%}" for c, a, _ in top)
            print(f"   {d:38s} {hint}")
        print()