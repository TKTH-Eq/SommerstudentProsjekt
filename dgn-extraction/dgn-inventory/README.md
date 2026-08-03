# dgn-inventory — Komponentoversikt fra DGN-baserte tegninger

To små skript, null avhengigheter, som svarer på «hva består denne tegningen av?»
ved å LESE svaret fra filstrukturen — ikke gjette fra piksler.

## Hvorfor dette virker der bildeanalysen feilet

I DGN er hvert symbol en **navngitt celle**. Når tegningen konverteres til DXF
blir hver celle en **blokk**, og hver plassering en **INSERT** med blokknavnet,
posisjon og rotasjon. Tag-tekstene ligger som egne tekstelementer med eksakte
koordinater. Ingen tolkning nødvendig — navnet står i filen.

## Arbeidsflyt — tre innganger

```
DGN V7 ────────────────────────────> dgn7_inventory.py  ──> CSV      (direkte!)
DGN V8 ──(ODA File Converter)──> DXF ──> dxf_inventory.py ──> CSV + HTML
Model Broker DEXPI-XML ────────────> list_components.py ──> CSV + HTML
```

`dgn7_inventory.py` leser V7-filer DIREKTE uten konvertering (ren Python,
selvkalibrerende offsets, `--debug` for feilsøk). Skriptet oppdager selv
om filen er V8 og sier fra. At symbolkodene deres er nøyaktig 6 tegn
(VAL001) er forresten et V7-fingeravtrykk: formatet tillater maks 6 tegn
i cellenavn.

**ODA File Converter** lastes ned gratis fra opendesign.com («ODA File Converter»).
Velg output-versjon f.eks. «R2018 ASCII DXF». Den konverterer hele mapper i ett.
(Alternativt: MicroStation kan eksportere DXF direkte, og organisasjonen deres
har åpenbart allerede en slik konvertering — XML-ene refererer til `.DGN.dxf`.)

## Bruk (Windows)

```
py dxf_inventory.py C025-V-HO27-P-_E-001-01.dxf
py list_components.py C025-V-HO27-P-_E-001-01_DGN.xml
```

Begge lager `<navn>_inventory.csv` og `<navn>_inventory.html` i samme mappe.

## Hva du får

- **Sammendrag**: antall pr. symbol/klasse (33 GateValve, 19 BallValve, ...)
- **Detaljliste**: hver instans med tag (f.eks. 27-4542PV), linjenummer
  (6"-PV-274508-ED200-7), dimensjon, posisjon og rotasjon
- **Ikke-mappede blokknavn** flagges i konsollen og gult i HTML-rapporten —
  legg dem til i `dexpi_mapping.json` for å få DEXPI-klasse

## Viktig ved første kjøring på ekte DXF

Cellenavnene i DGN-standarden deres er ikke nødvendigvis bokstavelig
`VAL001` — det kan være andre navn. Første kjøring viser deg de faktiske
navnene; da utvider du `dexpi_mapping.json` med dem (én gang), og alle
senere tegninger mapper automatisk.

## Begrensninger

- `dxf_inventory.py` leser ASCII-DXF. Får du «binær DXF»-feil: velg ASCII
  i ODA File Converter.
- Tag-kobling i DXF-varianten bruker nærmeste tekst (< 25 mm) som matcher
  tag-mønsteret `NN-XXnnn`/`NN-nnnXX`. Juster `TAG_RE` og avstanden i
  toppen av skriptet ved behov.
- `list_components.py` gir rikest resultat (linjenummer, dimensjon, spec)
  fordi Model Broker allerede har bygget topologien. DXF-varianten gir
  symbolnavn + posisjon + tag — nok til oversikt og til å bygge mapping.
