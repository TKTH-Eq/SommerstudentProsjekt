# PDF → structure lifter (prototype)

*The constructive side of the format argument.* The rest of the repo **measures**
what legacy PDF P&IDs lose (87 % precision / 55 % recall, symbol-only tags, a
loop-based topology that only *assumes* connections). This prototype tries to
**manufacture** the missing structure from the drawing itself and attaches a
measured accuracy to it — answering the brief's Data/LCI question *"what can be
achieved with legacy PDFs, and what are the practical limitations?"* with
numbers rather than assertions.

Code: [`src/extraction/pid_topology.py`](src/extraction/pid_topology.py) (the
lift + export), [`src/extraction/eval_topology.py`](src/extraction/eval_topology.py)
(measurement against DEXPI). **DEXPI is used only in the evaluation** — feeding
it back into the lift would defeat the purpose. Everything the lift consumes is
PDF-derived.

## Pipeline

```
nodes  = text-extracted tags (instruments/equipment)            [extraction.tag_*]
       + CNN-detected valve symbols the text layer never tagged  [gatevalve-ai]
edges  = pipe runs traced off the raster: ink − text − symbols − border,
         dilated to bridge dashes, connected-component labelled; components on
         the same pipe branch are connected (a branch touching >2 nodes is
         flagged a junction/header).
export = "DEXPI-lite" JSON + illustrative XML — components + connections
```

Run it:

```bash
python src/extraction/pid_topology.py C025-V-HO27-P-_E-002-01   # one drawing → stats
python src/extraction/eval_topology.py                          # measure all 16
```

## What it recovers (measured, 16 drawings with DEXPI + cached CNN detections)

| Metric | Result |
|---|---|
| Node coverage vs DEXPI tags (text) | **62 %** (mean) — consistent with the validated extractor's recall |
| Symbol-only valves recovered **beyond** text (CNN) | **528 total, ~33 per drawing** |
| Pipe edges traced from the raster | ~106 per drawing |

The **symbol-only valves are the headline win**: 33 valve components per drawing
that carry no readable tag and are therefore invisible to text extraction, but
which the CNN sees and the lift places into the structured model. That is the
55 %-recall gap being partially *filled*, not just measured — exactly the
content a machine-readable deliverable is supposed to carry.

## The connectivity finding (the important part)

Edge recovery is reported as a **capability count, not a precision/recall score
against DEXPI** — deliberately, and the reason is itself a result worth putting
in the report:

> Across the 16 drawings, the DEXPI export contains **249 tag-to-tag *process*
> adjacencies**, but only **4** of them have *both* endpoints recoverable from
> the PDF. So tag-level edge scoring has almost no valid targets.

Two compounding causes, both instructive:

1. **Physical piping is modelled through *untagged* intermediate elements.** In
   this Semantum export a pipe run is `component → nozzle → pipe-segment →
   nozzle → component`, where the nozzles and segments carry no tag. Direct
   tag-to-tag process adjacency therefore barely exists — the connectivity lives
   on elements a tag-level consumer never sees.
2. **Node recall compounds on both endpoints.** An edge is only scoreable if
   *both* of its tags were extracted; at 62 % node recall that is ~0.38 of
   edges even before cause (1).

A third, separate observation: most of what the export labels *connectivity* is
**signal / instrument-loop** links (e.g. `PT↔PI`, `ZS↔ZL`, `FIC↔FT` — same loop
number), not traceable process pipe. The raster tracer recovers *physical* line
adjacency (e.g. line `…2007PL ↔ …2008PL`), which is real and internally
consistent but is simply a **different graph** than the export's functional
model.

### Why this matters for Wisting

This is direct, empirical input to the deliverable *"minimum requirements for
future machine-readable P&ID/SCD deliverables"*:

- **Require tagged, tag-to-tag connectivity**, or a documented, resolvable
  mapping from pipe-segment/nozzle elements to the components they join.
  Otherwise even a *native DEXPI* consumer must re-derive topology.
- **Disambiguate connection semantics** (process pipe vs signal/functional
  loop) in the deliverable — "connected" means two different things today.
- A PDF→structure lift is viable for **component inventory** (instruments,
  valves, equipment) today; **topology** from legacy PDFs needs symbol-anchored
  node positions and full line-following, and is the harder, later step.

## Limitations / future work

- Node positions come from the **tag text**, not the component symbol where pipes
  attach — the main reason physical tracing under-connects. Anchoring valve
  nodes to CNN symbol centres (already available) is the next improvement.
- Line **crossings without a junction dot** merge two runs into one component;
  flagged as `junction` edges, not resolved.
- Connectivity is **undirected** — flow direction is not recovered from pixels.
- The DEXPI-lite XML is **illustrative**, not schema-valid Proteus; it shows the
  shape of the deliverable, not a drop-in import file.

Example outputs are written to `reports/pid_structure/` by the run commands above.
