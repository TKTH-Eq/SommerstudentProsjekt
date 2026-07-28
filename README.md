# AI-muligheter for P&ID og SCD — Huldra-prototype

Sommerstudentprosjekt (Lisa Bruun Paulsen og Torstein K. W. Thomassen).
Bygget på **åpne data** fra Huldra (avviklet gassfelt, Equinor): P&ID- og
SCD-tegninger som PDF, pluss Semantum DEXPI-XML for et utvalg tegninger.

Prosjektet undersøker oppgavens kjernespørsmål: *hvordan kan moderne AI,
strukturert ingeniørdata og agentiske utviklingsverktøy forbedre effektivitet,
kostnad, kvalitet, sikkerhet og beslutningsstøtte for arbeidsprosesser rundt
P&ID og SCD — i prosjektutvikling og drift?* Svaret demonstreres, ikke bare
beskrives: alt under er kjørbar kode på ekte tegninger, og alle AI-uttrekk er
**validert mot en uavhengig fasit**.

> Gjennomgående prinsipp: AI-output er et førsteutkast med **målt** feilrate
> (presisjon 87 %, recall 55 % mot DEXPI-fasit), aldri en autoritativ kilde.
> Alt et verktøy foreslår refererer tags som faktisk finnes i uttrekket.

## Nøkkeltall

| | Presisjon | Recall | F1 |
|---|---:|---:|---:|
| PDF-tekstuttrekk + vision-reserve, målt mot DEXPI-fasit (16 tegninger) | 87 % | 55 % | 68 % |
| Samme, med nozzler ekskludert fra fasiten | 87 % | ~66 % | — |

Recall er begrenset oppad av kildematerialet: tags tegnet som **symboler**
fremfor tekst kan tekstuttrekk aldri fange. Dette taket er nå **målt**: av de
bommede valve-/linje-taggene finnes bare 40 % som tekst i PDF-en overhodet, og
det realistiske taket for tekstmetoden er ~74 % recall (eks. nozzler). Full
oppdeling av gapet — reell uttreksfeil vs. metodens tekstlags-tak — står i
[`Results.md`](Results.md), sammen med historien om hvordan validering-drevet
iterasjon løftet recall fra 26 % til 55 %. Dette tallparet er også prosjektets
sentrale **formatargument**: det kvantifiserer hva PDF-leveranser koster, og
hva DEXPI/AML-krav løser.

## Demonstrasjonene (Streamlit-appen)

`streamlit run src/app.py` gir åtte sider. Kolonnen til høyre viser hvilket
nøkkelspørsmål i oppgaven hver side svarer på.

| Side | Hva den viser | Oppgavespørsmål |
|---|---|---|
| 🏠 System-analyse | Per system: P&ID↔SCD-avstemming, KPI-er, failure explorer, operatør-brief, alarm-rotårsak, live signalsimulering, interaktiv avhengighetsgraf — fra PDF-uttrekk (løkke-basert) | Prosjektfase: inkonsistenser · Drift: systemforståelse, rotårsak |
| 🧭 System-analyse (DEXPI) | Samme analyser, matet fra DEXPI: **oppgitte** koblinger, kryss-løkke-konsekvenser, DEXPI↔PDF-avstemming som viser recall-gapet per tegning | Data/LCI: hva strukturerte formater forbedrer |
| 🏷️ Tag-oversikt | Tag-register på tvers av systemer og kilder | Datauttrekk og strukturering |
| 🔗 DEXPI-topologi | Ekte FromID→ToID-topologi fra DEXPI-filene | Data/LCI |
| 🆚 DEXPI vs PDF (demo) | Interaktiv side-om-side: samme tegning rekonstruert fra begge kilder («tags er tekst; topologi er det ikke») — ligger også frittstående i `demos/DEXPI_VS_PDF.html` | PDF vs DEXPI-sammenligningen |
| ⚠️ HAZOP-forberedelse | Deterministisk arbeidsark (noder → avvik → årsaker → konsekvenser → barrierer) forankret i uttrekte tags; redigerbart med review-status og **autolagring mellom møter**; Excel-eksport i møteformat; valgfri AI-omskriving og **vision-utdrag** der Gemini leser selve tegningen og hvert tag-forslag verifiseres mot registeret | Prosjektfase: HAZID/HAZOP-støtte |
| ⚖️ HAZOP: PDF vs DEXPI | Samme arbeidsark-maskineri på samme tegning, to inputformater — barriere-andelen tallfester sikkerhetsargumentet for DEXPI | PDF vs DEXPI + HAZOP |
| 🎛️ Kontrollrom-assistent | Alarmdusj-scenario: skjult feil + støyalarmer fyres samtidig; assistenten gir strukturell brief per kandidat (uten å kåre vinner), operatøren beslutter, debrief skiller rot/symptom/støy; graf med opp-/nedstrøms-markering; valgfri forankret Gemini-Q&A | Drift: beslutningsstøtte i kontrollrom, alarm-rotårsak |
| 🔎 Finn riktig tegning | Søk i P&ID-ene på naturlig språk — rangerer ark etter en profil bygd fra tag-registeret (typekoder utvidet til ord, «PT» → pressure transmitter) pluss cachede 30-sek vision-sammendrag (der «separator»/«flare» kommer fra). Valgfri Gemini-utvidelse av søket (synonymer, NO↔EN) legger kun til søkeord. Se topptreffet med zoom/panorer | Drift/prosjekt: slutt å lete etter riktig ark |
| 📊 Compliance-dashboard | Anleggsdekkende opprulling av de strukturelle regelfunnene (R1–R3, R8–R9) over ALLE tegninger: totaler, system×regel-varmekart, alvorlighet per system, og en valgfri Gemini-skrevet 3-setningers «tilstand»-oppsummering forankret i tallene. Nedbrytningstabell med filtre + CSV. Funn er screeningkandidater | Prosjekt: kvalitet/avvik på tvers · ledelsesrapport |
| 📝 30-sekunders sammendrag | Vision-modellen leser ett P&ID-ark og gir en rask orientering — hva arket viser, nøkkelutstyr, hovedfarer (HAZOP-fokus) — pluss taggene den leste, hver verifisert mot registeret (✅ i register / 🟠 ikke i register). Cachet til disk, så demoen er offline-trygg. | Drift/prosjekt: rask orientering på ukjent ark |
| 💬 Plant Q&A (GraphRAG) | Spør hele anlegget på naturlig språk — svaret BEREGNES fra den sammenslåtte DEXPI-grafen + tag-registeret, ikke generert av en chatbot. Intent + tags trekkes ut, grafen svarer (nedstrøms/oppstrøms, vei mellom to tags, barrierer, trip→ventil, løkke, seksjon, lister), hvert tag er ekte. Valgfritt Gemini-lag brukes kun i KANTENE — tolker fritt formulerte spørsmål til en strukturert spørring, og omformulerer de hentede faktaene — men hvert tag AI foreslår verifiseres mot registeret før grafen svarer. «LLM foreslår, register verifiserer» på anleggsnivå | Drift: systemforståelse, avhengigheter, sikkerhetsfunksjoner |
| 🧩 PDF → struktur | Komponentuttrekk fra PDF-en alene (tekst-tags + CNN-ventilsymboler), «DEXPI-lite»-eksport og måling mot DEXPI. ✅ **Komponentinventar virker** (~62 % av tags + symbol-only ventiler tekst aldri når). ❌ **Topologi/kanttracing virker IKKE** på disse dataene og er forlatt — PDF→koblet DEXPI er ikke oppnåelig med denne tilnærmingen; grafen er beholdt som dokumentert negativt resultat. Se [`PID_TO_STRUCTURE.md`](PID_TO_STRUCTURE.md) | Data/LCI: hva som kan gjenskapes fra legacy-PDF, og grensene |

I tillegg: NeqSim-broen (`src/neqsim_tools/`) plotter hydratkurver med
MEG-inhibering og animerer en trykkavlastning mot hydratgrensen — koblingen
mellom uttrekt systeminformasjon og simuleringsverktøy.

## Kom i gang

Krever **Python 3.12+** og [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                          # installerer alle avhengigheter (pyproject.toml)
```

Legg tegningene under `data/raw/` (struktur under). AI-funksjonene (valgfrie)
trenger en Gemini-nøkkel i `.env` i prosjektroten:

```
GEMINI_API_KEY=<din nøkkel>      # gratis tier fra Google AI Studio holder
```

Start appen:

```bash
streamlit run src/app.py
```

Alt deterministisk (uttrekk, avstemming, graf, HAZOP-ark, kontrollrom-brief)
virker **uten** nøkkel; AI-lagene (omskriving, vision, Q&A) er tillegg oppå.

### Valgfritt: vision-reserve for bilde-tegninger

Noen få tegninger har et tekstlag som bare inneholder tittelfelt og rutenett,
mens innholdet er grafikk. For disse finnes en Gemini-basert vision-reserve som
leser tags direkte fra tegningsbildet (rasterisert med pypdfium2 — ren
pip-avhengighet, ingen systeminstallasjon). Samme `GEMINI_API_KEY` som resten
av AI-laget; ingen andre legitimasjoner trengs.

```bash
set HULDRA_VISION=1              # skru på reserven (av som standard)
```

Reserven utløses automatisk kun på tag-fattige tegninger (< 3 tekst-tags), og
modellsvaret filtreres mot et tag-mønster før noe slippes inn i uttrekket.
Vellykkede kall caches til `reports/vision_cache/tags/` (én lesbar JSON per
tegning), så gjentatte kjøringer er gratis og kvotebegrensede kjøringer kan
gjenopptas — feil caches aldri, de prøves bare på nytt. Modellen velges med
`GEMINI_MODEL` i `.env` (standard i prosjektet: gemini-3.1-flash-lite). I full
skala: hele tegningsbunken (72 bilde-lesninger, 360 tags) i én kjøring på
gratis tier. På valideringstegningen HO11 leser reserven alle 6 fasit-tags —
100 % presisjon og recall.

## Eksempel-arbeidsflyt

```bash
# 1) mål uttrekket mot DEXPI-fasiten
python src/validate_against_dexpi.py --raw data/raw --out reports

# 2) bryt ned hvor recall tapes (per klasse, per tegning, null-tegninger)
python src/analyze_validation_diffs.py --out reports

# 3) tallfest recall-taket: nozzle-ekskludering + symbol-vs-tekst-splitt
python src/analyze_recall_ceiling.py --reports reports --raw data/raw

# 4) generer HAZOP-arbeidsark for et system fra kommandolinjen
python src/analysis/hazop_prep.py 27

# 5) DEXPI-baserte HAZOP-noder (utstyrsforankrede seksjoner) for én tegning
python src/analysis/hazop_dexpi.py "data/raw/Semantum Huldra P&IDS/.../C025-V-HO27-P-_E-002-01.DGN.xml"
```

## Gjenbrukbare prompts, agenter og mønstre

Oppgaven etterspør gjenbrukbare artefakter. De viktigste, med plassering:

- **HAZOP-omskriving** — `HAZOP_PROMPT` i `src/analysis/hazop_prep.py`:
  omskriv/utvid et arbeidsark, kun tags fra gitt liste, generisk merkes.
- **Vision-lesing av tegning** — `PROMPT` i `src/ai/hazop_vision.py` og
  `src/extraction/vision_extract.py`: strukturert JSON, transkriber kun
  leselige tags, aldri finn opp — kombinert med mønsterfilter på svaret.
- **Forankret operatør-Q&A** — prompten i `src/kontrollrom.py`: svar kun fra
  gitte fakta, aldri finn opp tags, ikke avslør fasit i treningsmodus.
- **Tag-verifiseringsmønsteret** — `verify_tags`/`_type_number` i
  `hazop_vision.py`: normaliser på (type, nummer)-paret på tvers av
  skrivemåter (`HV 2264` ≡ `13-HV-2264` ≡ `13-2264HV`), klassifiser hvert
  AI-nevnt tag som bekreftet/kandidat/ukjent. Dette mønsteret — **LLM
  foreslår, strukturert register verifiserer** — er prosjektets viktigste
  gjenbrukbare idé og gjelder langt utover HAZOP.
- **Delt AI-klient** — `src/ai/gemini_client.py`: én langlivet klient med
  gjenoppretting (løser kjent «client has been closed»-feil under Streamlit).

## Verktøy, lisenser og utviklingsoppsett (erfart)

- **Kjernestack (åpen kildekode, ingen lisenskost):** Python 3.12, Streamlit,
  networkx, PyMuPDF, pdfplumber, pypdfium2, pandas/scipy/scikit-learn,
  openpyxl, matplotlib. NeqSim (Apache 2.0, krever Java) for termodynamikk.
- **AI-tjenester:** Google Gemini — én tjeneste, én nøkkel, for hele AI-laget
  inkludert vision-reserven (gratis tier holdt til all utvikling og demo,
  inkludert full vision-lesning av tegningsbunken takket være disk-caching).
  Erfart driftsrisiko: modellgenerasjoner avvikles på uker-til-måneder
  (2.5-flash-lite forsvant for nye brukere midt i prosjektet); mottiltaket er
  konfigurerbart modellvalg (`GEMINI_MODEL`) pluss validering mot fasit etter
  bytte.
- **Strukturert fasit:** Semantum Model Broker-produserte DEXPI-filer
  (kommersielt verktøy; filene var levert som del av datasettet).
- **Agentiske kodeverktøy** ble brukt gjennom hele utviklingen og var
  avgjørende for tempoet — se metodekapitlet i rapporten. Arbeidsmåten
  «valider → les diff → én fokusert fiks → mål igjen» (26 % → 55 % recall)
  er dokumentert i `Results.md`.

## Data og compliance

Kun **offentlig publiserte** Huldra-data og syntetiske eksempler er brukt.
Ingen intern, begrenset eller konfidensiell informasjon er lastet opp til
AI-tjenester. API-nøkler ligger i `.env` (gitignorert). Alle alarm-/sensordata
i demonstrasjonene er syntetiske.

## Kjente begrensninger (kortversjon)

- Recall-taket er i hovedsak **metodens tak**, ikke en feil som kan fikses i
  tekstuttrekk — og det er nå målt: 60 % av valve-/linje-bommene er
  symbol-only, og taket for tekstmetoden er ~74 % recall (eks. nozzler).
  Det er selve DEXPI-argumentet, i tall.
- PDF-avhengighetsgrafen er løkke-basert (koblinger *innen* løkker antas);
  ekte kryss-løkke-topologi krever DEXPI, som DEXPI-sidene viser.
- DEXPI HAZOP-seksjoner er grafbaserte tilnærminger til en HAZOP-leders
  nodekutt; tegninger med utagget utstyr gir grove seksjoner (→ minimumskrav).
- Redigeringer i HAZOP-arket autolagres til `reports/hazop_store/` (én
  lesbar JSON per system) og overlever økten — arbeidsark kan tas opp igjen
  møte for møte. Et lagret ark er et øyeblikksbilde av uttrekket det ble
  bygget fra; en egen knapp bygger nytt fra dagens uttrekk.
- Tag-registeret bygges på den validerte ekstraktoren, så valideringstallene
  gjelder hele kjeden. Rundt to tredjedeler av SCD-ene mangler lesbart
  tekstlag helt — enda et argument for strukturerte leveranser; disse leses nå
  av vision-reserven (360 tags fra 45 bilde-ark, cachet og reproduserbart).
- Kontrollrom-assistenten viser strukturell nåbarhet, ikke prosesskonsekvens;
  scenariene er syntetiske. Motoren (`analysis/control_room.py`) er
  datakilde-agnostisk — bytt scenariegeneratoren med en alarmfeed, så er
  samme brief operativ støtte. Det er pilotsteget.

## Kravsporing mot oppgavens leveranser

| Leveranse (oppgaveteksten) | Hvor |
|---|---|
| Repo med README, oppsett, eksempel-arbeidsflyt | denne filen |
| ≥ 2 fungerende AI-demonstrasjoner | 8 app-sider (tabellen over) |
| Rapport med funn, begrensninger, verktøy, pilotkandidater | egen rapport (leveres separat) |
| PDF vs strukturert format-sammenligning | `Results.md`, 🆚- og ⚖️-sidene, `demos/DEXPI_VS_PDF.html` |
| Verktøy-/lisensanbefaling | seksjonen over + rapportens kap. 3.4 |
| Presentasjon/demo for stakeholders | appen + `demos/` |
| Gjenbrukbare prompts/agenter/skills | seksjonen over |
| Dashboard/grafvisualisering med topologi, kompleksitet, flagg | 🏠/🧭-sidene (KPI-er, mest koblede komponenter, quality flags) |
| Minimumskrav for maskinlesbare leveranser | rapporten (empirisk begrunnet: recall-tak, utagget utstyr, tag-konvensjonsvariasjon) |
| Pilotforslag | rapporten (alarmfeed-integrasjon av kontrollrom-motoren er hovedkandidat) |