"""
Seam between the control room and the NeqSim failure-consequence chain
(analysis/simulate_component_failure.py — the other student's module).

Design constraint honoured here: DO NOT modify that module. Its functions
print to stdout (CLI design), so this adapter captures the output and
returns it as text, alongside the structural result. If anything in the
chain is unavailable (processed CSVs not built, NeqSim/Java missing, tag
not on the drawing), the adapter degrades to a clear message instead of an
exception — the control room must never crash because a consequence
estimate was unavailable.

Chain per call:
  1. load the drawing's rows from data/processed/dexpi_*.csv
  2. simulate_failure(): remove the component, find what gets isolated
  3. neqsim_consequence(): hydrate-risk estimate for the isolated segment
     (explicitly a simplified illustration — see that module's caveats)
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"


def consequence_for(drawing_stem: str, tag: str) -> dict:
    """{'ok': bool, 'summary': str, 'affected': [tags], 'log': str}.

    drawing_stem: e.g. 'C025-V-HO27-P-_E-001-01' (no .DGN suffix)
    tag: component tag as shown in the app, e.g. '27-4510PV'
    """
    try:
        import pandas as pd
        from analysis.simulate_component_failure import (
            load_graph, simulate_failure, neqsim_consequence)
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "affected": [], "log": "",
                "summary": f"Consequence module unavailable: {e}"}

    need = ["dexpi_tags.csv", "dexpi_connections.csv", "dexpi_associations.csv"]
    if not all((PROCESSED / f).exists() for f in need):
        return {"ok": False, "affected": [], "log": "",
                "summary": "data/processed/ is missing — run "
                           "analysis/parse_dexpi_data.py first (see README)."}

    try:
        tags = pd.read_csv(PROCESSED / "dexpi_tags.csv")
        conns = pd.read_csv(PROCESSED / "dexpi_connections.csv")
        assocs = pd.read_csv(PROCESSED / "dexpi_associations.csv")
        G, sub_t = load_graph(tags, conns, assocs, drawing_stem)
        if tag not in set(sub_t["tag_name"].dropna()):
            return {"ok": False, "affected": [], "log": "",
                    "summary": f"{tag} is not present in the processed "
                               f"DEXPI data for {drawing_stem}."}

        buf = io.StringIO()
        with redirect_stdout(buf):
            res = simulate_failure(G, sub_t, tag)
            xmls = list((ROOT / "data" / "raw").rglob(f"{drawing_stem}.DGN.xml"))
            neqsim_consequence(len(res["affected_ids"]),
                               xml_path=xmls[0] if xmls else None,
                               sub=sub_t, fail_id=res["fail_id"])
        affected = sorted(res["affected_tags"]["tag_name"].dropna().tolist())
        return {"ok": True, "affected": affected, "log": buf.getvalue(),
                "summary": f"Removing {tag} isolates {len(res['affected_ids'])} "
                           f"objects ({len(affected)} tagged) from the rest of "
                           f"the system."}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "affected": [], "log": "",
                "summary": f"The consequence calculation failed: {e}"}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    r = consequence_for(sys.argv[1] if len(sys.argv) > 1 else
                        "C025-V-HO27-P-_E-001-01",
                        sys.argv[2] if len(sys.argv) > 2 else "27-4510PV")
    print(r["summary"])
    print("affected:", r["affected"][:10])
    print("--- log from the chain ---")
    print(r["log"])