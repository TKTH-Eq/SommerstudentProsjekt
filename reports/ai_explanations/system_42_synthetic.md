# System 42 - DEMO PLANT - Gas Export (SYNTHETIC)

## Context (audit trail of exactly what was sent)

```
SYSTEM 42 - DEMO PLANT - Gas Export (SYNTHETIC)

TAG INVENTORY (by type):
  XV (on/off shutdown valve): DEMO-42-XV0001, DEMO-42-XV0002
  ESV (emergency shutdown valve): DEMO-42-ESV0010
  PT (pressure transmitter): DEMO-42-PT0100, DEMO-42-PT0101
  HIC (hand indicating controller): DEMO-42-HIC0200

SAFETY-CRITICAL TAGS: DEMO-42-ESV0010

COUPLED SYSTEMS (shared drawings):
  system 82 (DEMO ESD / Fire & Gas (SYNTHETIC)) - 4 shared drawing(s)
  system 64 (DEMO Gas Compression (SYNTHETIC)) - 2 shared drawing(s)

CONTROL-LOGIC NOTES (verbatim from drawings):
  - ESV0010 closes on confirmed gas or ESD level 2 signal from system 82.
  - HIC0200 output 0-100% sets MEG injection pump stroke, 80-950 litre/hour.
```

## AI explanation

> _No LLM backend configured (LLM_BASE_URL unset). This is the deterministic baseline: structured data only, no AI reasoning._

## Extracted structure

```
SYSTEM 42 - DEMO PLANT - Gas Export (SYNTHETIC)

TAG INVENTORY (by type):
  XV (on/off shutdown valve): DEMO-42-XV0001, DEMO-42-XV0002
  ESV (emergency shutdown valve): DEMO-42-ESV0010
  PT (pressure transmitter): DEMO-42-PT0100, DEMO-42-PT0101
  HIC (hand indicating controller): DEMO-42-HIC0200

SAFETY-CRITICAL TAGS: DEMO-42-ESV0010

COUPLED SYSTEMS (shared drawings):
  system 82 (DEMO ESD / Fire & Gas (SYNTHETIC)) - 4 shared drawing(s)
  system 64 (DEMO Gas Compression (SYNTHETIC)) - 2 shared drawing(s)

CONTROL-LOGIC NOTES (verbatim from drawings):
  - ESV0010 closes on confirmed gas or ESD level 2 signal from system 82.
  - HIC0200 output 0-100% sets MEG injection pump stroke, 80-950 litre/hour.
```

Configure an approved endpoint to generate the analytic sections.
