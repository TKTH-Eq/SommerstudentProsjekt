# Resultater — automatisk tag-uttrekk fra Huldra-tegninger

Sommerstudentprosjekt basert på åpne data fra Huldra (avviklet gassfelt, Equinor).
Målet er å trekke ut utstyrs- og instrument-tags automatisk fra eldre P&ID- og
SCD-tegninger (PDF), koble dem sammen på tvers av dokumenter, og bygge et
strukturert, søkbart kunnskapslag oppå en dokumentbunke som ellers bare er bilder.

Dette dokumentet oppsummerer **hvor godt uttrekket faktisk virker**, målt mot en
uavhengig fasit — ikke en demo, men et tall vi tør å stå for.

## Kort oppsummert

- Uttrekket er validert mot Semantum sine **DEXPI XML-filer** (ISO 15926,
  strukturert P&ID-eksport), som fungerer som fasit der de finnes.
- Målt på de 16 P&ID-ene som har både PDF og XML: **presisjon 87 %, recall 55 %,
  F1 67 %** (≈ 1 000 fasit-tags totalt).
- To små, validerte regel-fikser løftet recall fra 26 % til 55 % — mer enn en
  dobling — uten at presisjonen falt.
- Det gjenstående recall-gapet er kartlagt og forklart: mesteparten er tags som
  **ikke finnes som lesbar tekst** i kildefila (symboler / bilde-tegninger), altså
  en grense for tekstuttrekk som metode — ikke feil i koden.

## Metode

Tags trekkes ut fra PDF-enes tekstlag med to komplementære pass: sammensatte tags
(`27-PT4805`) via mønstergjenkjenning, og tags som er stablet inne i
instrument-bobler (type over nummer) via rekombinasjon av posisjonerte ord.

Valideringen matcher hver P&ID mot sin DEXPI-XML på tegningsnummer, normaliserer
begge tag-settene (store bokstaver, skilletegn fjernet) og regner presisjon
(andel uttrekte tags som er ekte), recall (andel fasit-tags som ble funnet) og F1.
Hver uenighet logges som enten **MISSED** (i XML, ikke funnet) eller **EXTRA**
(funnet, ikke i XML), slik at hvert avvik kan spores til enten en uttrekksfeil
eller reell dokumentasjonsdrift.

Bare tegninger med en XML skåres. Delvis fasitdekning svekker ikke tallet: man
validerer alltid på et utvalg, og et målt tall på utvalget estimerer resten.

## Resultater: effekten av hver forbedring

Alle tall er mikro-gjennomsnitt over de samme 16 tegningene (≈ 1 027 fasit-tags).

| Steg | Endring | Presisjon | Recall | F1 |
|---|---|---:|---:|---:|
| Utgangspunkt | Kun type-først-uttrekk | 76 % | 26 % | 38 % |
| + Nummer-først-tags | Fanger håndventiler (`27-4510PV`) | 86 % | 49 % | 62 % |
| + Maskin-tags | Fanger to-sifrede tags (`27-KA50`) | 87 % | 55 % | 67 % |

Begge forbedringene ble funnet ved å lese diff-rapporten fra valideringen: den
viste at recall-tapet var konsentrert i to konkrete tag-former som mønstrene ikke
dekket. Hver fiks var én linje, og effekten ble målt mot fasit umiddelbart.

## Hvor det gjenstående recall-gapet ligger

De resterende bommene fordeler seg på tre tydelige feilmoduser, hvorav bare den
første er en programvarefeil:

1. **Tette tegninger — reell, gjenværende uttreksfeil.** Noen få tegninger
   (HO27-002, HO20-002, HO82) har både lav recall og flere falske treff samtidig.
   Boble-rekombinasjonen sliter når tegningen er tett tegnet. Dette er det eneste
   sporet der mer arbeid i uttrekket kan flytte tallet — men gevinsten er usikker
   og risikoen er lavere presisjon.

2. **Symbol-only tags — metodens tak.** En stor andel fasit-tags (bl.a.
   håndventilene 27-4520 til 27-4542 og nozzler som `N1100`) finnes ikke som tekst
   i PDF-en i det hele tatt — de er tegnet som grafikk. Ingen regel kan hente ut
   tekst som ikke er der. Dette er en grense for tekstuttrekk, ikke en feil.

3. **Bilde-tegninger — krever OCR.** Én tegning (HO11) har et tekstlag som bare
   inneholder tittelfelt og rutenett, mens selve innholdet er grafikk. Her gir
   tekstuttrekk null tags korrekt. Slike tegninger krever OCR (Google Vision) på
   selve tegningsbildet. En OCR-reserve er bygget inn i uttrekkslaget og utløses
   automatisk på tag-fattige sider.

## Begrensninger

- Uttrekket er tilnærmet, ment som et **førsteutkast for ingeniørgjennomgang**,
  ikke en autoritativ kilde.
- Recall er begrenset oppad av kildematerialet: der tags er tegnet som symboler
  fremfor tekst, kan tekstuttrekk aldri fange dem. Et realistisk tak for ren
  tekstekstraksjon på dette settet ligger godt under 100 %.
- Fasiten (DEXPI) har selv hull: flere «EXTRA»-treff viste seg å være ekte tags
  som manglet i XML-en, så den reelle presisjonen er noe høyere enn 87 %.
- SCD-ene skåres ikke her — DEXPI-filene dekker kun P&ID. SCD-siden av uttrekket
  brukes i P&ID↔SCD-avstemmingen, men er ikke målt mot en ekstern fasit.
- Nozzler (`N…`) telles i dag som fasit-tags selv om de sjelden er tekst; å
  ekskludere dem ville gitt et mer rettferdig recall-tall.

## Videre arbeid

- Installere en ren rasteriserings-backend (`pypdfium2`) slik at OCR-reserven kan
  demonstreres ende-til-ende på bilde-tegningen HO11.
- Vurdere å ekskludere nozzler fra fasiten for et mer representativt recall-tall.
- Se på de tette tegningene (HO27-002 m.fl.) hvis mer tekst-recall er ønskelig,
  med presisjon som vaktpost.
- Utvide valideringen til flere tegninger etter hvert som DEXPI-filer blir
  tilgjengelige, for å bekrefte at tallet holder på et bredere utvalg.

## Reproduksjon

```
# mål uttrekket mot DEXPI-fasiten
python src\validate_against_dexpi.py --raw data\raw --out reports

# bryt ned hvor recall tapes (per klasse, per tegning, null-tegninger)
python src\analyze_validation_diffs.py --out reports

# samme kjøring med OCR-reserve på tag-fattige sider
set HULDRA_VISION=1
python src\validate_against_dexpi.py --raw data\raw --out reports_vision
```

Utdata: `reports\validation_report.csv` (presisjon/recall/F1 per tegning + TOTAL),
`reports\validation_diffs.csv` (hver MISSED/EXTRA-tag) og
`reports\validation_diff_summary.csv` (recall-tap per klasse og tegning).