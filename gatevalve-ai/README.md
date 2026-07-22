# gatevalve-ai — Enkel modell: inneholder tegningen gate valve (åpen/lukket)?

Bevisst smal modell, bygget nedenfra: to symboler, ett spørsmål, TRUE/FALSE-svar.

## Slik virker den

**1. Læring (`learn_from_legend.py`)** — modellen leser legendearket selv:
finner tekstene «GATE VALVE, OPEN» og «GATE VALVE, CLOSE», klipper symbolfeltet
som hører til hver, og isolerer KUN sløyfen (de to trekantene): tekst maskeres,
rammer og linjer rundt forkastes, kun den kompakte figuren i midten beholdes.
Til og med skillet åpen/lukket læres herfra (fyllgrad 0,14 vs 0,43).

**2. Sjekk (`check_drawing.py`)** — tre trinn per tegning:
- *Kandidater*: malmatch (begge sløyfene, flere størrelser, 0°/90°), kun
  lokale topper, NMS.
- *Verifisering*: geometriske krav som tekst, piler, sirkler og stolper ikke
  klarer å etterligne — blekket må ligge på et X med endestolper (åpen) eller
  inni to fylte trekanter med jevne ender og ~halv høyde ved kvartpunktene
  (lukket). Gjennomgående rørlinjer strippes fra utsnittet først.
- *Tilstand*: åpen vs. lukket avgjøres i ORIGINAL oppløsning ved erosjon med
  strektykkelsen (omriss forsvinner, fyll overlever) — oppløsningsuavhengig.

**Oppløsnings-ærlighet:** er symbolet for lite relativt til strektykkelsen
(< ~7,5× eller < 18 px), finnes ikke åpen/lukket-informasjonen fysisk i
bildet. Da svarer modellen «gate valve (tilstand usikker)» i stedet for å
gjette. Dette skjer på lavoppløselige skann — aldri på 150–300 dpi-PDF-er.

## Validert resultat

| Tegning | Fasit | Modellens svar |
|---|---|---|
| PT-111 valve-legende (150 dpi) | begge finnes | OPEN **TRUE** (0,87) · CLOSED **TRUE** (0,96) |
| PT-110 fitting-legende (150 dpi) | ingen | OPEN **FALSE** · CLOSED **FALSE** |
| HO27 P&ID (40 dpi skann, 33 gate valves) | finnes | «tilstand usikker» **TRUE** |
| HO11 rammeark (40 dpi skann) | ingen | alt **FALSE** |

## Bruk

```
py learn_from_legend.py U999-1-000--PT-111-01.PDF        (én gang)
py check_drawing.py min_pid.pdf --dpi 200                (per tegning)
py check_drawing.py skann.jpg                            (bilder går også)
```

Ut per tegning: TRUE/FALSE i terminalen, `<navn>_verdict.json` (maskinlesbart)
og `<navn>_proof.png` (funn markert: grønn=åpen, rød=lukket, oransje=usikker).

## Kjente begrensninger

- På ~40 dpi-skann er antallet funn omtrentlig og åpen/lukket utilgjengelig
  (informasjonen er fysisk borte i rasteren). Kjør originale PDF-er på
  150–300 dpi, så gjelder øverste rad i tabellen.
- Roterte ventiler håndteres i 0°/90°; skrå (45°) ventiler er sjeldne i
  denne standarden og tas ikke.
- Modellen svarer på tilstedeværelse, ikke telling — «antall funn» er en
  bonus, ikke et løfte.

## Veien videre (når dette er bevist hos deg)

Samme oppskrift skalerer: legg til flere symboler i læringssteget (ball valve,
check valve …) med hver sin geometriske signatur i verifiseringen, eller bytt
verifiseringen mot en liten CNN trent på maler + syntetiske plasseringer.
Arkitekturen (lær-fra-legende → kandidater → verifiser → svar) består.


---

# Del 2: Veiledet læring (ren bildegjenkjenning)

Nye moduler etter beslutningen om å satse alt på bildegjenkjenning:

| Fil | Hva |
|---|---|
| `make_synthetic.py` | Genererer merket treningsdata fra legendesymbolene: symbol + rørlinje + naborot + piler/sirkler/tekstfeller + lav-DPI-degradering. Fasiten er kjent fordi vi la symbolet der selv |
| `make_dataset.py` | Lager EKTE merkede utsnitt: kobler Model Broker-XML (klasse+posisjon) til tegningsbildet. Ingen Bentley/DGN nødvendig — XML-ene finnes allerede |
| `train_classifier.py` | HOG-trekk + RBF-SVM. Rapporterer nøyaktighet, forvekslingsmatrise, og evaluerer på ekte XML-merkede utsnitt |
| `classify_drawing.py` | Ende-til-ende med den TRENTE modellen i stedet for geometrireglene |

## Målte resultater (ærlige)

| Oppsett | Syntetisk validering | Kommentar |
|---|---|---|
| Første trening | 49 % | maler fra runde 1 var forurenset (ramme-rester) — trente på søppel |
| + rene maler | 76 % | rotårsaken funnet og fikset |
| + ikke-ventiler i bakgrunnsklassen | 74 % | mer realistisk negativklasse |

| Tegning (fasit) | Geometrisk pipeline | Lært pipeline |
|---|---|---|
| PT-111 (open+closed finnes) | TRUE/TRUE ✓ | TRUE/TRUE ✓ (10+10 funn) |
| PT-110 (ingen gate valves) | FALSE/FALSE ✓ | 4+3 falske funn ✗ |

## Tre lærdommer (viktigere enn tallene)

1. **Treningsdata-kvalitet slår alt.** Én forurenset malkilde kostet 25
   prosentpoeng. Sjekk alltid dataene visuelt før du klandrer modellen.
2. **Informasjon som er borte, kan ikke læres tilbake.** På ~40 dpi er
   åpen/lukket-skillet fysisk utvisket — samme grense gjelder mennesker.
   Tren og test på 150–300 dpi.
3. **Negativklassen må dekke det som faktisk finnes.** Klassifikatoren
   dyttet fittings inn i ventilklasser helt til den fikk se fittings i
   trening. Presisjon kommer fra det modellen har lært å avvise.

## Neste steg, i rekkefølge

1. Kjør `make_dataset.py` på begge XML-tegningene lokalt med `--dpi 200`
   -> ~140 EKTE merkede utsnitt i full kvalitet.
2. Sorter de ~45 GateValve-utsnittene i open/ og closed/ (5 minutter) —
   da har du ekte fasit også for tilstanden.
3. Tren på syntetisk + ekte blandet (`train_classifier.py` leser begge).
4. Beste arkitektur: geometrisk verifisering (presisjonen) + lært
   klassifikator (gate vs. ball vs. globe). Kombiner i classify_drawing.
5. Når datasettet passerer ~500 ekte utsnitt: bytt HOG+SVM mot en liten
   CNN (krever PyTorch lokalt) — samme mappestruktur fungerer rett inn.
