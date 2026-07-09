"""
Synthetic sensor-signal simulation.

Generates a fluctuating measurement that drifts until it crosses a threshold
(e.g. a HH set point like the ones printed on the P&ID), which is what raises
the alarm that then feeds the root-cause engine. Pure stdlib, deterministic
with a seed, so the demo is reproducible.

This is FICTIONAL data for demonstration — it is not a process model and not
live readings. It exists to show the full chain: signal → threshold breach →
alarm → root-cause, which is the control-room decision-support story.
"""
from __future__ import annotations
import random


def simulate_series(baseline: float, threshold: float, steps: int = 40,
                    drift: float | None = None, noise: float | None = None,
                    seed: int = 7):
    """Return (values, breach_index). The signal fluctuates and trends toward
    the threshold, crossing it partway through. breach_index is the first step
    at or beyond the threshold (None if it never crosses)."""
    r = random.Random(seed)
    span = threshold - baseline
    if drift is None:
        drift = span / steps * 1.8          # trend that clearly reaches past the limit
    if noise is None:
        noise = abs(span) * 0.10            # fluctuation amplitude (does not accumulate)
    vals, breach = [], None
    for i in range(steps):
        trend = baseline + drift * i        # deterministic rising trend
        v = trend + r.uniform(-noise, noise)  # fluctuation around the trend
        vals.append(round(v, 2))
        crossed = v >= threshold if span >= 0 else v <= threshold
        if breach is None and crossed:
            breach = i
    return vals, breach


if __name__ == "__main__":
    vals, breach = simulate_series(baseline=40.0, threshold=100.0, steps=30)
    print(f"breach at step {breach} (value {vals[breach]}) of {len(vals)}")
    print("series:", vals)