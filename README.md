# Huldra P&ID / SCD analysis

Turns legacy P&ID and SCD PDFs into structured, queryable data and runs two
analyses on it: **P&ID↔SCD consistency checking** and **failure propagation**.
Built for the Wisting / Huldra summer-student assignment.

## What it does

```
P&ID + SCD PDF ──▶ extraction ──▶ EngineeringObjects ──▶ dependency graph
                                                            │
                        ┌───────────────────────────────────┼───────────────┐
                consistency check              KPIs / quality        failure propagation
                (flagged_issues.csv)           (quality_report.md)   (graph query)
```

Reports written to `reports/`:
- `tags.csv` — every extracted tag, typed and categorised
- `flagged_issues.csv` — P&ID↔SCD discrepancies to verify
- `quality_report.md` — complexity KPIs + quality flags
- `safety_register.csv` — safety/shutdown-related tags
- `system_dependency_graph.{png,html,json}` — the graph
- `ai_explanations/system_<n>.md` — natural-language summary

## Setup

```bash
uv venv && source .venv/bin/activate     # or: python -m venv .venv
uv pip install -r requirements.txt        # pdfplumber, networkx, matplotlib, pillow
sudo apt-get install -y poppler-utils     # provides pdftoppm for rendering
```

Put drawings in `data/raw/P&ID/` and `data/raw/SCD/` (filenames contain the
system code, e.g. `…-HO27-…`).

## Run

```bash
python src/main.py 27                     # runs on the HO27 P&ID + SCD pair
python src/main.py                        # defaults to system 27
python src/check_pdf.py data/raw/SCD/C025-V-HO00-J-_E-021-02.PDF   # diagnose a PDF
```

### Interactive app (pick a system, run live)

```bash
pip install streamlit
streamlit run src/app.py
```

Lists every system that has BOTH a P&ID and an SCD in `data/raw/`, lets you
pick one, and runs the whole pipeline live — KPIs, consistency, safety
register, the interactive graph and the failure explorer with an operator
brief. A thin shell over the same modules as `main.py`. For a fixed, portable
handout instead (double-click, no server), use `python src/dashboard.py 27`
which writes a self-contained `reports/index.html`.

## How extraction works (and its limits)

Tags appear two ways: inline (`27-PT4805`) and stacked inside instrument
bubbles (`type` over `number`), so extraction combines a regex pass with
positional word-clustering. It is a **first pass for engineer review, not
truth** — e.g. it currently flags `LSL548` vs `LSL0548` as a near-duplicate,
which is exactly the kind of thing a human must resolve.

Text-layer quality varies by drawing. `check_pdf.py` reports whether a PDF is
`text-extractable`, `vector but text is outlined` (→ needs a vision model), or
`raster` (→ needs OCR). The HO27 pair is text-extractable; the older HO00 SCD
has outlined text and would need the vision path.

## Optional AI summary

`src/ai/explain_system.py` calls a model if `ANTHROPIC_API_KEY` is set, else it
writes a deterministic templated summary so the pipeline always runs. For
Equinor-internal drawings, point the client at the approved Azure deployment.

## Next steps

- Add vector-geometry connectivity (`pdfplumber` lines/curves) so the graph
  reflects real piping/signal links, not loop-number grouping.
- Wire a vision model into extraction for outlined-text / raster drawings.
- Add a `pyDEXPI` loader so a DEXPI file feeds the *same* graph and analyses.