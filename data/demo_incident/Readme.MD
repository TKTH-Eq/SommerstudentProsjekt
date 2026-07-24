# Demo incident dataset (SYNTHETIC)

One historical-style incident, 15 alarms over 24 s, anchored 2024-11-07T03:14:00+00:00 (fictive night shift).

| file | content |
|---|---|
| `alarms.csv` | alarm & event journal: one row per activation |
| `trends.csv` | historian export: 1 Hz values per alarmed tag, 0–100 % of range, HI limit 80 / LO limit 20 |
| `incident.json` | metadata + the solution (root/cascade/noise) — keep hidden during the exercise |

**This is demonstration data.** The alarm order and cascade follow the structural model; the timestamps and process values are generated (each tag drifts from baseline before its alarm and crosses its limit at the alarm time). It shows the *format and workflow* of a historian-connected pilot — it is not measured plant data.
