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
| PDF-tekstuttrekk målt mot DEXPI-fasit (16 tegninger) | 87 % | 55 % | 67 % |

Recall er begrenset oppad av kildematerialet: tags tegnet som **symboler**
fremfor tekst kan tekstuttrekk aldri fange. Full oppdeling av gapet — reell
uttreksfeil vs. metodens tekstlags-tak — står i [`Results.md`](Results.md),
sammen med historien om hvordan validering-drevet iterasjon løftet recall fra
26 % til 55 %. Dette tallparet er også prosjektets sentrale **formatargument**:
det kvantifiserer hva PDF-leveranser koster, og hva DEXPI/AML-krav løser.

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
| ⚠️ HAZOP-forberedelse | Deterministisk arbeidsark (noder → avvik → årsaker → konsekvenser → barrierer) forankret i uttrekte tags; redigerbart med review-status; Excel-eksport i møteformat; valgfri AI-omskriving og **vision-utdrag** der Gemini leser selve tegningen og hvert tag-forslag verifiseres mot registeret | Prosjektfase: HAZID/HAZOP-støtte |
| ⚖️ HAZOP: PDF vs DEXPI | Samme arbeidsark-maskineri på samme tegning, to inputformater — barriere-andelen tallfester sikkerhetsargumentet for DEXPI | PDF vs DEXPI + HAZOP |
| 🎛️ Kontrollrom-assistent | Alarmdusj-scenario: skjult feil + støyalarmer fyres samtidig; assistenten gir strukturell brief per kandidat (uten å kåre vinner), operatøren beslutter, debrief skiller rot/symptom/støy; graf med opp-/nedstrøms-markering; valgfri forankret Gemini-Q&A | Drift: beslutningsstøtte i kontrollrom, alarm-rotårsak |

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

### Valgfritt: OCR-reserve (Google Vision)

Kun for skannede/bilde-baserte tegninger. Krever `uv sync --extra ocr`,
rasterisering (pypdfium2, følger med) og Google-legitimasjon:

```bash
set GOOGLE_APPLICATION_CREDENTIALS=C:\sti\til\service-account.json
set HULDRA_VISION=1              # skru på reserven (av som standard)
```

OCR utløses automatisk kun på tag-fattige sider.

## Eksempel-arbeidsflyt

```bash
# 1) mål uttrekket mot DEXPI-fasiten
python src/validate_against_dexpi.py --raw data/raw --out reports

# 2) bryt ned hvor recall tapes (per klasse, per tegning, null-tegninger)
python src/analyze_validation_diffs.py --out reports

# 3) generer HAZOP-arbeidsark for et system fra kommandolinjen
python src/analysis/hazop_prep.py 27

# 4) DEXPI-baserte HAZOP-noder (utstyrsforankrede seksjoner) for én tegning
python src/analysis/hazop_dexpi.py "data/raw/Semantum Huldra P&IDS/.../C025-V-HO27-P-_E-002-01.DGN.xml"

# 5) vision-utdrag med tag-verifisering for en P&ID (krever GEMINI_API_KEY)
python src/ai/hazop_vision.py "data/raw/P&ID/C025-V-HO27-P-_E-002-01.PDF"
```

Utdata i `reports/`: valideringsrapporter (CSV), kvalitetsrapport,
HAZOP-arbeidsark (CSV/XLSX per system), vision-utdrag (XLSX) og figurer.

## Mappestruktur

```
data/raw/
  P&ID/  SCD/                   tegninger (PDF)
  SCD Legend/  Symbols/         referansemateriale
  Semantum Huldra P&IDS/        DEXPI XML — fasit + strukturert kilde
src/
  app.py                        Streamlit-inngang (st.navigation, 8 sider)
  system_analysis[_dexpi].py    analysesidene (PDF- og DEXPI-matet)
  hazop.py / hazop_compare.py   HAZOP-sidene
  kontrollrom.py                kontrollrom-assistenten
  dexpi_graph.py / dexpi_vs_pdf.py / tag_oversikt.py
  config.py                     stier, tag-typer, kategorier, sikkerhetstyper
  models/engineering_object.py  datamodellen (tag → system/type/løkke/kategori)
  extraction/                   pdf_parser, tag_extractor, dexpi_parser, vision
  analysis/                     graf, konsistens, KPI, root_cause, signal_sim,
                                hazop_prep/_dexpi/_export, control_room
  ai/                           gemini_client (delt klient), operator_brief,
                                hazop_vision, explain_system
  neqsim_tools/                 hydratkurver + blowdown-animasjon (NeqSim)
  validate_against_dexpi.py     validering mot fasit
  analyze_validation_diffs.py   recall-tap-nedbryting
demos/DEXPI_VS_PDF.html         frittstående interaktiv formatdemo
reports/                        genererte rapporter og eksporter
Results.md                      valideringsmetode, tall og iterasjonshistorie
```

## Gjenbrukbare prompts, agenter og mønstre

Oppgaven etterspør gjenbrukbare artefakter. De viktigste, med plassering:

- **HAZOP-omskriving** — `HAZOP_PROMPT` i `src/analysis/hazop_prep.py`:
  omskriv/utvid et arbeidsark, kun tags fra gitt liste, generisk merkes.
- **Vision-lesing av tegning** — `PROMPT` i `src/ai/hazop_vision.py`:
  strukturert JSON, transkriber kun leselige tags, skill symboler fra tekst.
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
  networkx, PyMuPDF, pdfplumber, pandas/scipy/scikit-learn, openpyxl,
  matplotlib. NeqSim (Apache 2.0, krever Java) for termodynamikk.
- **AI-tjenester:** Google Gemini (gratis tier holdt til all utvikling og demo;
  merk rate-grenser — generer demo-resultater på forhånd). Google Cloud Vision
  som valgfri OCR-reserve (betalt per kall, kun bilde-tegninger).
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

- Recall-taket på 55 % er i hovedsak **metodens tak** (symbol-only-innhold),
  ikke en feil som kan fikses i tekstuttrekk — det er selve DEXPI-argumentet.
- PDF-avhengighetsgrafen er løkke-basert (koblinger *innen* løkker antas);
  ekte kryss-løkke-topologi krever DEXPI, som DEXPI-sidene viser.
- DEXPI HAZOP-seksjoner er grafbaserte tilnærminger til en HAZOP-leders
  nodekutt; tegninger med utagget utstyr gir grove seksjoner (→ minimumskrav).
- Redigeringer i HAZOP-arket lever per økt (session state), ikke i database.
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