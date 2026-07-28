# Cause & effect — designet styringslogikk

Her ligger anleggets **cause-and-effect-logikk**: hva som er *designet* til å
skje, i motsetning til avhengighetsgrafen som bare sier hva som *kan* henge
sammen. Det er forskjellen på «27-PSH4811 kan nå 27-XV4813 strukturelt» og
«27-PSH4811 STENGER 27-XV4813 på PSD».

`src/analysis/cause_effect.py` leser hver `*.csv` i denne mappen, og
`src/kontrollrom.py` bruker resultatet i operatør-briefen og i debriefens
«designed response»-sjekk.

## Skjema

```
drawing,cause_tag,effect_tag,function,source,verified,note
```

| Kolonne | Betydning |
|---|---|
| `drawing` | arket raden er lest fra (stem, uten filendelse) |
| `cause_tag` | initierende funksjon, f.eks. `27-PSH4811` |
| `effect_tag` | aktuert element, f.eks. `27-XV4813` |
| `function` | kort aksjonstekst, f.eks. `PSD: steng innløp` |
| `source` | hvor på arket, f.eks. `SCD E-101, C&E-felt B4` |
| `verified` | `ja`/`nei` — **`nei` vises med eksplisitt advarsel i appen** |
| `note` | fritekst; vision-rader bærer verifiseringsstatus her |

Tags valideres mot tag-registeret og normaliseres, så `27-PT 4804` og
`27-PT4804` matcher. Rader med ukjente tags **slettes ikke** — de beholdes og
flagges.

## To kilder til rader

**1. Håndført.** En ingeniør leser arket og fyller inn. Sett `verified=ja`.
Filnavn fritt, f.eks. `system27.csv`.

**2. Vision-uttrekk.** `src/ai/ce_vision.py` leser C&E-matrisen av SCD-arket
med Gemini og skriver `vision_<ark>.csv`. Disse radene:

- står **alltid** som `verified=nei` — de er utkast, ikke lest logikk
- bærer tag-verifiseringsstatus i `note` (`verified` / `verified_loose` /
  `new_candidate`)
- skrives med registerets skrivemåte der den kan avgjøres entydig, med
  modellens råtranskripsjon bevart i `note` (`lest "27-4814XV"`)

```bash
python src/ai/ce_vision.py "data/raw/SCD/C025-V-HO27-J-_E-101-01.PDF"
python src/ai/ce_vision.py --selftest      # hele kjeden uten API-nøkkel
```

Arbeidsflyten er **gjennomgang, ikke tillit**: kjør uttrekket, les gjennom
radene mot arket, sett `verified=ja` på det som stemmer, rett eller stryk
resten. Først da regnes logikken som lest.

## Status

Mappen inneholder foreløpig ingen datarader. `ce_vision.py` er broen som skal
fylle den — men merk at prosjektet **ikke har en uavhengig C&E-fasit** slik det
har DEXPI-fasit for tag-uttrekket. Presisjon/recall for C&E-uttrekket er derfor
**ikke målt** ennå. `ce_vision.compare_to_manual()` er måleapparatet; det
trenger et håndført ark å måle mot. Å fylle ut ett ark for hånd er det som gjør
tallet mulig — og det er en liten jobb sammenlignet med verdien av å kunne
oppgi en målt feilrate på linje med resten av prosjektet.
