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
  F1 67 %** (≈ 1 027 fasit-tags totalt). Ekskluderes nozzle-tags fra fasiten
  (de er sjelden trykt som tekst), er recall **65 %**.
- To små, validerte regel-fikser løftet recall fra 26 % til 55 % — mer enn en
  dobling — uten at presisjonen falt. En Gemini-basert vision-reserve lukket
  deretter bilde-tegning-gapet (HO11: 0 → 2 treff, 100 % presisjon).
- Det gjenstående recall-gapet er ikke bare kartlagt, men **tallfestet**: av de
  bommede valve-/linje-taggene finnes bare 40 % som tekst i PDF-en i det hele
  tatt. Resten er tegnet som symboler og er per definisjon utenfor rekkevidde
  for enhver tekstmetode. Det realistiske taket for tekstuttrekk på dette
  settet er ~74 % recall (eks. nozzler).

## Metode

Tags trekkes ut fra PDF-enes tekstlag med to komplementære pass: sammensatte tags
(`27-PT4805`) via mønstergjenkjenning, og tags som er stablet inne i
instrument-bobler (type over nummer) via rekombinasjon av posisjonerte ord. Et
tredje pass — en Gemini-vision-reserve — trigges automatisk på tag-fattige
tegninger (< 3 tekst-tags) når `HULDRA_VISION=1` er satt, og leser tags direkte
fra det rasteriserte tegningsbildet. Modellsvaret filtreres mot et tag-mønster,
så fritekst og hallusinasjoner aldri slipper inn i uttrekket.

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
| + Vision-reserve | Gemini leser bilde-tegninger (HO11: 0 → 2 treff) | 87 % | 55 % | 67 % |

Regel-forbedringene ble funnet ved å lese diff-rapporten fra valideringen: den
viste at recall-tapet var konsentrert i to konkrete tag-former som mønstrene ikke
dekket. Hver fiks var én linje, og effekten ble målt mot fasit umiddelbart.
Vision-reserven flytter totaltallet lite (HO11 har bare 6 fasit-tags) — verdien
er at bilde-tegninger nå håndteres av samme pipeline, målt og uten forbehold.

## Hvor det gjenstående recall-gapet ligger

De resterende bommene fordeler seg på tre tydelige feilmoduser, hvorav bare den
første er en programvarefeil:

1. **Tette tegninger — reell, gjenværende uttreksfeil.** Noen få tegninger
   (HO27-002, HO20-002, HO82) har både lav recall og flere falske treff samtidig.
   Boble-rekombinasjonen sliter når tegningen er tett tegnet. Dette er det eneste
   sporet der mer arbeid i uttrekket kan flytte tallet — men gevinsten er usikker
   og risikoen er lavere presisjon. Analysene under bekrefter diagnosen: disse
   tegningene flyttes verken av nozzle-justeringen eller symbol-splitten.

2. **Symbol-only tags — metodens tak, nå tallfestet.** En stor andel fasit-tags
   (bl.a. håndventilene 27-4520 til 27-4542 og nozzler som `N1100`) finnes ikke
   som tekst i PDF-en i det hele tatt — de er tegnet som grafikk. Ingen regel kan
   hente ut tekst som ikke er der. Se «Symboltaket tallfestet» under.

3. **Bilde-tegninger — løst med vision-reserven.** Én tegning (HO11) har et
   tekstlag som bare inneholder tittelfelt og rutenett, mens selve innholdet er
   grafikk. Her ga tekstuttrekk null tags. Gemini-vision-reserven leser nå slike
   tegninger automatisk: på HO11 fant den 2 av 6 fasit-tags med 100 % presisjon,
   mens mønsterfilteret avviste 8 modellsvar som ikke var gyldige tags. De 4
   gjenstående bommene er nozzler, som ikke står som lesbar tekst — reserven
   fanger altså alt som faktisk finnes å lese. Reserven trigget også på én liten
   tegning (V-HO71, 1 tekst-tag) og var nøytral der: vision bekreftet teksten
   uten å forurense. Kostnad: 2 Gemini-kall for hele valideringskjøringen
   (gratis tier).

## Nozzle-justert recall

Nozzle-referanser (`N1`, `N1100`, …) står i DEXPI-fasiten som topologi, men er
sjelden trykt som lesbar tekst på tegningen. Med nozzler ekskludert fra fasiten
stiger recall fra 55 % til **65 %** — 164 av 462 bom (35 %) er nozzler.

Effekten er dramatisk på enkelttegninger: HO27-003 går fra 23 % til **86 %**
(79 av 83 bom var nozzler — tegningen var aldri et uttreksproblem), og V-HO64 og
HO11 når **100 %**. De tette tegningene (HO27-002, HO20-001/-002) påvirkes
derimot knapt — deres gap er reelle uttreksfeil, ikke fasit-artefakter, helt i
tråd med feilmodus-inndelingen over.

Justeringen er konservativ: treff antas nozzle-frie, så kun nevneren krympes.
Skulle enkelte nozzler faktisk være truffet, er det justerte tallet marginalt
for lavt — aldri for høyt.

## Symboltaket tallfestet

For hver bommet valve-/linje-tag er det sjekket om taggen finnes som tekst i
PDF-ens tekstlag i det hele tatt (substring-søk på normaliserte ord: full tag,
uten systemprefiks, og bare nummeret). Resultat, over 176 valve-/linje-bom på
13 tegninger:

| | Antall | Andel | Tolkning |
|---|---:|---:|---|
| Finnes som tekst | 70 | 40 % | Uttreksfeil — i prinsippet fiksbar |
| Symbol-only | 106 | 60 % | Metodens tak — utenfor rekkevidde for tekstuttrekk |

Dette bekrefter empirisk antakelsen om håndventil-seriene (27-45xxPV): flertallet
av valve-bommene er fysisk fraværende fra tekstlaget. Unntaket som bekrefter
regelen er HO20-002 (26 text-present mot 2 symbol-only) — den tette tegningen,
der gapet skyldes uttrekket selv (feilmodus 1). Text-present-tellingen er en
øvre grense (nummer-alene-treff kan gi falske positive), så symbol-only-andelen
er et *gulv*.

Fikses alle 70 text-present-bommene, lander recall på ~**74 %** eks. nozzler.
Det er det realistiske taket for enhver ren tekstmetode på dette settet — resten
krever symbolgjenkjenning (jf. `gatevalve-ai`) eller strukturerte leveranser.
Dette er prosjektets formatargument i ett tall.

## Begrensninger

- Uttrekket er tilnærmet, ment som et **førsteutkast for ingeniørgjennomgang**,
  ikke en autoritativ kilde.
- Recall er begrenset oppad av kildematerialet: der tags er tegnet som symboler
  fremfor tekst, kan tekstuttrekk aldri fange dem. Taket er nå målt til ~74 %
  (eks. nozzler) — se «Symboltaket tallfestet».
- Fasiten (DEXPI) har selv hull: flere «EXTRA»-treff viste seg å være ekte tags
  som manglet i XML-en, så den reelle presisjonen er noe høyere enn 87 %.
- SCD-ene skåres ikke her — DEXPI-filene dekker kun P&ID. SCD-siden av uttrekket
  brukes i P&ID↔SCD-avstemmingen, men er ikke målt mot en ekstern fasit.
- Tag-registeret (`build_tag_register.py`) bygges på den validerte ekstraktoren
  (samme kodevei som valideringen), så presisjons-/recall-tallene gjelder hele
  kjeden. Samlingen økte registeret fra 854 til 1 266 tags (nummer-først-former
  og kryss-systemtags den gamle registerlogikken ikke fanget) og avdekket at
  rundt to tredjedeler av SCD-ene mangler lesbart tekstlag helt — tekstlags-
  problemet er langt større på SCD-siden enn på P&ID-siden.

## Videre arbeid

- Se på de tette tegningene (HO27-002 m.fl.) hvis mer tekst-recall er ønskelig,
  med presisjon som vaktpost. De 70 text-present-bommene er kandidatlisten,
  sammen med de 59 taggene den gamle registerlogikken fanget men den validerte
  ekstraktoren bommer (FE/SI/HV-bobler, én-bokstavs-former) — enhver utvidelse
  måles mot fasiten før den beholdes.
- Utvide valideringen til flere tegninger etter hvert som DEXPI-filer blir
  tilgjengelige, for å bekrefte at tallet holder på et bredere utvalg.
- Symbolgjenkjenning (jf. `gatevalve-ai`) som tredje uttrekskanal for å angripe
  de 60 % symbol-only-bommene — tekst + vision + symboler, alle målt mot samme
  fasit.

## Reproduksjon

```
# mål uttrekket mot DEXPI-fasiten
python src\validate_against_dexpi.py --raw data\raw --out reports

# bryt ned hvor recall tapes (per klasse, per tegning, null-tegninger)
python src\analyze_validation_diffs.py --out reports

# samme kjøring med Gemini-vision-reserve på tag-fattige tegninger
set HULDRA_VISION=1
python src\validate_against_dexpi.py --raw data\raw --out reports_vision

# recall-tak-analyse: nozzle-ekskludering + valve/line text-present-splitt
python src\analyze_recall_ceiling.py --reports reports_vision --raw data\raw
```

Utdata: `reports\validation_report.csv` (presisjon/recall/F1 per tegning + TOTAL),
`reports\validation_diffs.csv` (hver MISSED/EXTRA-tag) og
`reports\validation_diff_summary.csv` (recall-tap per klasse og tegning).
Recall-tak-analysen skriver tabellene sine til terminalen.