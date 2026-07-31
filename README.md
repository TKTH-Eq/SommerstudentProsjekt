# AI-muligheter for P&ID og SCD — Huldra-prototype

Sommerstudentprosjekt (Lisa Bruun Paulsen og Torstein K. W. Thomassen).
Bygget på **åpne data** fra Huldra (avviklet gassfelt, Equinor): P&ID- og
SCD-tegninger som PDF/DGN, pluss Semantum DEXPI-XML for et utvalg tegninger.

Prosjektet undersøker oppgavens kjernespørsmål: *hvordan kan moderne AI,
strukturert ingeniørdata og agentiske utviklingsverktøy forbedre effektivitet,
kostnad, kvalitet, sikkerhet og beslutningsstøtte for arbeidsprosesser rundt
P&ID og SCD — i prosjektutvikling og drift?* Svaret demonstreres, ikke bare
beskrives: alt under er kjørbar kode på ekte tegninger, og alle AI-uttrekk er
**validert mot en uavhengig fasit**.

> **Gjennomgående prinsipp:** AI-output er et førsteutkast med **målt** feilrate
> (presisjon 87 %, recall 55 % mot DEXPI-fasit), aldri en autoritativ kilde.
> Alt et verktøy foreslår refererer tags som faktisk finnes i uttrekket.
> Mønsteret heter **«LLM foreslår, strukturert register verifiserer»** og går
> igjen i hver eneste AI-funksjon i repoet.

---

## Innhold

1. [Hurtigstart](#1-hurtigstart)
2. [Nøkkeltall](#2-nøkkeltall)
3. [Arkitektur](#3-arkitektur)
4. [Repostruktur](#4-repostruktur)
5. [Installasjon og konfigurasjon](#5-installasjon-og-konfigurasjon)
6. [Streamlit-appen — alle 21 sider](#6-streamlit-appen--alle-21-sider)
7. [Kommandolinjeverktøy](#7-kommandolinjeverktøy)
8. [Datagrunnlaget](#8-datagrunnlaget)
9. [Uttrekkspipelinen i detalj](#9-uttrekkspipelinen-i-detalj)
10. [Validering og målemetode](#10-validering-og-målemetode)
11. [Symbolgjenkjenning — `gatevalve-ai`](#11-symbolgjenkjenning--gatevalve-ai)
12. [PDF → struktur (DEXPI-lite)](#12-pdf--struktur-dexpi-lite)
13. [Model Broker-sporet](#13-model-broker-sporet)
14. [AI-laget](#14-ai-laget)
15. [Regelkatalogen (R1–R16)](#15-regelkatalogen-r1r16)
16. [Gjenbrukbare prompts, agenter og mønstre](#16-gjenbrukbare-prompts-agenter-og-mønstre)
17. [Verktøy, lisenser og driftserfaring](#17-verktøy-lisenser-og-driftserfaring)
18. [Data, sikkerhet og compliance](#18-data-sikkerhet-og-compliance)
19. [Kjente begrensninger](#19-kjente-begrensninger)
20. [Feilsøking](#20-feilsøking)
21. [Utviklingskonvensjoner](#21-utviklingskonvensjoner)
22. [Kravsporing mot oppgavens leveranser](#22-kravsporing-mot-oppgavens-leveranser)
23. [Videre arbeid og pilotkandidater](#23-videre-arbeid-og-pilotkandidater)

---

## 1. Hurtigstart

```bash
git clone <repo-url> && cd SommerstudentProsjekt
uv sync                                   # installerer alle avhengigheter (~15 s)
uv run streamlit run src/app.py           # åpner appen på http://localhost:8501
```

Det er hele oppsettet. **Tegningene ligger i repoet** (140 MB under
`data/raw/`: 20 P&ID-er, 193 SCD-ark, 17 DEXPI-eksporter), og `reports/`
kommer med ferdig varme cacher — så appen har ekte data å vise fra første
sekund, uten nedlasting, API-nøkkel eller nettilgang.

Mangler du `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`
(Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`).
Du trenger ikke installere Python selv — `uv sync` henter versjonen prosjektet
er låst til (3.14, se `.python-version`) hvis du ikke har den.

Alt **deterministisk** — uttrekk, avstemming, grafer, HAZOP-ark,
kontrollrom-brief, regelscreening — virker uten API-nøkkel. AI-lagene
(omskriving, vision, Q&A) er tillegg oppå og krever `GEMINI_API_KEY` i `.env`.
Se [§5](#5-installasjon-og-konfigurasjon) for full oppsettguide.

Er du usikker på hvor du skal begynne, gir landingssiden (🏠 Home) tre
guidede stier: *formatargumentet på to minutter* (🆚), *AI-assistert HAZOP*
(⚠️) og *alarmdusj i kontrollrommet* (🎛️).

---

## 2. Nøkkeltall

Alle tall er målt, reproduserbare og skrevet av skriptene i repoet — ingen
er anslag.

### 2.1 Tag-uttrekk mot DEXPI-fasit

Mikro-gjennomsnitt over de **16 P&ID-ene som har både PDF og DEXPI-XML**
(≈ 1 027 fasit-tags). Kilde: `reports/validation_report.csv`.

| Kanal | Presisjon | Recall | F1 | Recall eks. nozzler |
|---|---:|---:|---:|---:|
| **Tekst alene** (produksjonspipelinen) | **87 %** | **55 %** | **67 %** | 65 % |
| Vision alene (Gemini på hele arket) | 84 % | 24 % | 37 % | 28 % |
| Tekst ∪ vision (opt-in) | 83 % | **61 %** | **70 %** | **72 %** |

### 2.2 Hvordan recall ble løftet

| Steg | Endring | Presisjon | Recall | F1 |
|---|---|---:|---:|---:|
| Utgangspunkt | kun type-først-uttrekk | 76 % | 26 % | 38 % |
| + nummer-først-tags | fanger håndventiler (`27-4510PV`) | 86 % | 49 % | 62 % |
| + maskin-tags | fanger to-sifrede tags (`27-KA50`) | 87 % | 55 % | 67 % |
| + vision-reserve | Gemini leser bilde-tegninger (HO11: 0 → 6 av 6) | 87 % | 55 % | 68 % |

Hver forbedring ble funnet ved å lese diff-rapporten fra valideringen, var
én linje kode, og ble målt mot fasiten umiddelbart. Arbeidsmåten
«valider → les diff → én fokusert fiks → mål igjen» er selve metodefunnet.

### 2.3 Recall-taket, tallfestet

Recall er begrenset oppad av kildematerialet: tags tegnet som **symboler**
fremfor tekst kan tekstuttrekk aldri fange. Over 176 valve-/linje-bom på
13 tegninger:

| | Antall | Andel | Tolkning |
|---|---:|---:|---|
| Finnes som tekst i PDF-en | 70 | 40 % | uttreksfeil — i prinsippet fiksbar |
| Symbol-only | 106 | 60 % | metodens tak — utenfor rekkevidde for tekst |

**Det realistiske taket for enhver ren tekstmetode på dette settet er
~74 % recall (eks. nozzler).** Dette tallparet er prosjektets sentrale
formatargument: det kvantifiserer hva PDF-leveranser koster, og hva
DEXPI/AML-krav løser.

### 2.4 Øvrige målte tall

| Måling | Resultat | Kilde |
|---|---|---|
| Rotårsak rangert #1, 20 % tapte alarmer | **98 %** (topp 3: 99 %) | `reports/eval_root_cause.json` |
| Rotårsak rangert #1, 40 % tapte alarmer | 94 % (topp 3: 97 %) | 800 scenarier per betingelse |
| Rotårsak, hardeste betingelse (dobbel feil + 20 % tap) | 94 % | 5 seeds × 4 støynivåer × 40 feil |
| Vision i full skala | 72 tegninger lest, 45 med funn, **360 tags** | `reports/vision_cache/tags/` |
| PDF→struktur: nodedekning vs DEXPI | 62 % (snitt) | `src/extraction/eval_topology.py` |
| PDF→struktur: symbol-only ventiler gjenvunnet | **528 totalt, ~33 per tegning** | samme |
| PDF→struktur: kant-/topologigjenvinning | **mislyktes** — 4 av 249 kanter skårbare | `PID_TO_STRUCTURE.md` |
| Tag-register (validert ekstraktor, alle ark) | 1 463 tags over 34 systemer | `reports_unified/tag_register.csv` |
| Symbolmodell (gatevalve-ai), syntetisk validering | 76 % | `gatevalve-ai/README.md` |

Full historie, feilmodusanalyse og alle delresultater: **[`Results.md`](Results.md)**.
PDF→struktur-eksperimentet i sin helhet: **[`PID_TO_STRUCTURE.md`](PID_TO_STRUCTURE.md)**.

---

## 3. Arkitektur

Fire lag, der hvert lag kan brukes uten laget over:

```
                    ┌───────────────────────────────────────────────┐
   LAG 4            │  Streamlit-app (src/app.py, 21 sider)         │
   presentasjon     │  + selvstendige HTML-eksporter (offline-trygt) │
                    └───────────────────┬───────────────────────────┘
                                        │
                    ┌───────────────────┴───────────────────────────┐
   LAG 3            │  Analyse (src/analysis/)                      │
   analyse          │  plant_model · root_cause · control_room ·    │
                    │  hazop_prep · hazop_dexpi · rule_screening ·  │
                    │  rule_catalog · graph_qa · kpi · time_to_trip │
                    │  drawing_search · neqsim_* · cause_effect     │
                    └───────────────────┬───────────────────────────┘
                                        │
   ┌────────────────────────────────────┴───────────────────────────┐
   │  LAG 2  Uttrekk (src/extraction/) + AI (src/ai/)               │
   │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
   │  │ tekstlag     │  │ DEXPI-XML    │  │ vision (Gemini)      │  │
   │  │ pdfplumber   │  │ dexpi_parser │  │ vision_extract       │  │
   │  │ tag_extractor│  │ (fasit+graf) │  │ hazop_vision         │  │
   │  └──────────────┘  └──────────────┘  └──────────────────────┘  │
   │  ┌──────────────────────────────────────────────────────────┐  │
   │  │ symbolgjenkjenning (gatevalve-ai, CNN/HOG+SVM)           │  │
   │  └──────────────────────────────────────────────────────────┘  │
   └────────────────────────────────────┬───────────────────────────┘
                                        │
                    ┌───────────────────┴───────────────────────────┐
   LAG 1            │  data/raw/  P&ID · SCD · SCD Legend ·         │
   rådata           │  Symbols · Semantum DEXPI-XML                 │
                    └───────────────────────────────────────────────┘

   TVERRGÅENDE:  validering (validate_against_dexpi, compare_channels,
                 eval_topology, eval_root_cause, vision_eval)
                 disk-caching (ai_cache, vision_cache) — demoen er offline-trygg
```

### Dataflyt, ende til ende

```
PDF/DGN ──► pdf_parser ──► tag_extractor ──┬──► tag_parser ──► EngineeringObject
                              │             │
                     (vision-reserve        └──► build_tag_register ──► reports/tag_register.{csv,json}
                      hvis < 3 tekst-tags)                                    │
                                                                              ▼
DEXPI-XML ──► dexpi_parser ──► data/processed/dexpi_{tags,connections,associations}.csv
                                       │                                      │
                                       ├──► plant_model (ETT anleggsgraf) ◄────┘
                                       │         │
                                       │         ├──► root_cause ──► control_room ──► 🎛️
                                       │         ├──► graph_qa ─────────────────────► 💬
                                       │         └──► anleggsoversikt ──────────────► 🏭
                                       │
                                       ├──► hazop_dexpi ──► hazop_prep ──► hazop_export ──► ⚠️ ⚖️
                                       ├──► rule_screening / rule_catalog ──────────► 📊
                                       └──► neqsim_system_report / time_to_trip ────► 🧪
```

### Tre designregler som forklarer det meste av koden

1. **Én kodevei per påstand.** Appen, batch-pipelinen og HTML-dashboardet
   importerer *de samme* modulene. De kan derfor aldri være uenige.
   `src/system_analysis.py` er et tynt skall over samme moduler som
   `src/main.py` og `src/dashboard.py`.
2. **Sider importerer aldri fra sider.** Streamlit-sider er skript; å
   importere en side kjører den. Delt logikk ligger i `src/utils/discovery.py`
   og `src/analysis/` — aldri i en sidefil.
3. **Feil skal være synlige.** Manglende designsystem gir rød banner, ikke
   stille fallback. Uverifiserte AI-tags markeres 🟠, ikke skjules.
   `cite()` i regelkatalogen *reiser feil* på ukjent proveniens.

---

## 4. Repostruktur

```
SommerstudentProsjekt/
├── README.md                    ← denne filen
├── Results.md                   validerings­historikk, feilmodus­analyse, alle tall
├── PID_TO_STRUCTURE.md          PDF→struktur-eksperimentet (komponenter ✅ / topologi ❌)
├── pyproject.toml               avhengigheter (uv/PEP 621)
├── uv.lock                      låst avhengighetsgraf
├── .streamlit/config.toml       EDS-inspirert lyst tema (Moss Green #007079)
│
├── src/
│   ├── app.py                   ENTRYPOINT — st.navigation + tema
│   ├── nav_pages.py             sideregister (single source of truth for navigasjon)
│   ├── ui.py                    designsystem: page_header, chips, pill, prio_badge
│   ├── config.py                stier + tag-taksonomi (INPUTS/LOGIC/OUTPUTS/EQUIPMENT)
│   ├── main.py                  batch-pipeline: P&ID+SCD → graf → analyser → rapporter
│   ├── dashboard.py             selvstendig HTML-dashboard (alt inlinet, virker offline)
│   ├── incident_context.py      delt hendelseskontekst — én situasjon, hele appen
│   │
│   ├── <21 sidefiler>           hjem.py, system_analysis.py, hazop.py, kontrollrom.py, …
│   │
│   ├── extraction/              LAG 2 — uttrekk
│   │   ├── pdf_parser.py        pdfplumber (tekst + posisjonerte ord + vektorgeometri)
│   │   ├── tag_extractor.py     pass a/b/c → tags (inkl. vision-reserve)
│   │   ├── tag_parser.py        rå tag → typet objekt
│   │   ├── tag_locator.py       tag → pikselbokser på rasteren
│   │   ├── vision_extract.py    Gemini-vision-uttrekk + diskcache
│   │   ├── dexpi_parser.py      DEXPI-XML → tags/koblinger/assosiasjoner
│   │   ├── pid_topology.py      PDF → «DEXPI-lite» komponent+koblingsmodell
│   │   └── eval_topology.py     måling av lifteren mot DEXPI
│   │
│   ├── analysis/                LAG 3 — 40+ analysemoduler (se §6/§7)
│   ├── ai/                      Gemini-klient, vision, HAZOP-omskriving, cache
│   ├── models/engineering_object.py   kjerneobjektet: én tagget komponent
│   ├── neqsim_tools/            termodynamikk: hydratkurver, blowdown, fluid-oppslag
│   ├── utils/discovery.py       delt datasøk uten sideeffekter
│   └── scripts/geometri_diagnose.py   frittstående geometri-feilsøking
│
├── gatevalve-ai/                symbolgjenkjenning (egen README)
│   ├── learn_from_legend.py     lær symboler fra legendearket
│   ├── check_drawing.py         geometrisk pipeline (kandidat → verifiser → tilstand)
│   ├── make_synthetic.py        syntetiske treningsdata
│   ├── make_dataset*.py         ekte merkede utsnitt fra Model Broker-XML
│   ├── train_classifier.py      HOG + RBF-SVM
│   ├── train_cnn.py             liten CNN (når datasettet er stort nok)
│   ├── train_verifiers.py       per-klasse verifikatorer
│   ├── classify_drawing.py      ende-til-ende med trent modell
│   ├── run_folds.py             kryssvalidering over tegningsfolds
│   └── results/                 deteksjoner per tegning + evaluering
│
├── data/
│   ├── raw/                     kildetegningene (se §8)
│   ├── processed/               avledede CSV-er (dexpi_tags, connections, …)
│   ├── cause_effect/            designet C&E-logikk (egen README + skjema)
│   ├── demo_incident/           SYNTETISK historisk hendelse (alarms/trends/json)
│   └── Equinor open data sharing license - Huldra.pdf
│
├── reports/                     alle genererte artefakter (se §8.3)
├── reports_unified/             registerbygg over HELE bunken
├── reports_vision/              valideringskjøring med vision-reserve på
├── reports_vision_check/        vision-second-opinion på regelfunn
├── reports_channels/            tekst vs vision vs union (150 dpi)
├── reports_channels_300/        samme eksperiment ved 300 dpi
│
├── tools/
│   ├── eval_agent.py            testrigg for kontrollrom-agenten (harde scenarier)
│   └── make_demo_incident.py    generer syntetisk hendelsesdatasett
└── notebooks/                   utforskende notebooks (tomme plassholdere)
```

---

## 5. Installasjon og konfigurasjon

### 5.1 Forutsetninger

| Krav | Versjon | Må du gjøre noe? |
|---|---|---|
| [`uv`](https://docs.astral.sh/uv/) | nyeste | **Ja** — eneste faktiske forutsetning |
| Python | 3.12+ (låst til 3.14) | Nei — `uv sync` henter den ved behov |
| Kildedata | — | Nei — tegningene ligger i repoet (§5.4) |
| Java (JRE/JDK) | 8+ | Kun for NeqSim (🧪-siden) |
| Gemini API-nøkkel | gratis tier | Kun for AI-lagene, som er valgfrie |

Installer `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                    # Linux/macOS
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"         # Windows
```

Java trengs kun for NeqSim-sporet. Mangler Java, feiler NeqSim-kallene med
en tydelig melding og resten av appen er upåvirket — sett
`HULDRA_NO_NEQSIM=1` for å hoppe over dem helt.

### 5.2 Installasjon

```bash
git clone <repo-url>
cd SommerstudentProsjekt
uv sync                              # installerer alt fra pyproject.toml + uv.lock
uv run streamlit run src/app.py      # start appen
```

`uv run` er det som gjør at du slipper å aktivere et virtuelt miljø manuelt.
Vil du heller aktivere det: `source .venv/bin/activate` (Windows:
`.venv\Scripts\activate`), så holder `streamlit run src/app.py`.

Valgfri ekstra (Anthropic-modell som alternativ til malen i operatør-brief
og systemsammendrag):

```bash
uv sync --extra anthropic
```

### 5.3 Miljøvariabler

Lag en `.env` i prosjektroten (gitignorert):

```dotenv
GEMINI_API_KEY=<din nøkkel>          # gratis tier fra Google AI Studio holder
GEMINI_MODEL=gemini-3.1-flash-lite   # valgfritt — standard i prosjektet
ANTHROPIC_API_KEY=<valgfritt>        # kun for alternativ brief-generator
```

| Variabel | Standard | Effekt |
|---|---|---|
| `GEMINI_API_KEY` | — | slår på hele AI-laget. Uten den: alt deterministisk virker, AI-knapper viser forklarende melding |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | modellvalg — byttbart uten kodeendring (se driftsrisiko i §17) |
| `ANTHROPIC_API_KEY` | — | lar `ai/operator_brief.py` og `ai/explain_system.py` bruke Anthropic i stedet for malen |
| `HULDRA_VISION` | `0` | `1` slår på vision-reserven i tag-uttrekket (pass c) |
| `HULDRA_VISION_FRESH` | `0` | `1` omgår diskcachen og tvinger nye API-kall |
| `HULDRA_NO_NEQSIM` | `0` | `1` hopper over alle NeqSim-kall (nyttig uten Java) |

På Windows: `set HULDRA_VISION=1`. På Linux/macOS: `export HULDRA_VISION=1`.

### 5.4 Data — du trenger ikke skaffe noe

**Tegningene er allerede i repoet.** Huldra-dataene er offentlig publisert
(lisens: `data/Equinor open data sharing license - Huldra.pdf`) og
versjonert med koden, så et klon gir deg alt: 20 P&ID-er, 193 SCD-ark,
17 DEXPI-eksporter og symbolbibliotekene — se [§8](#8-datagrunnlaget) for
strukturen.

Det samme gjelder `reports/`: tag-registeret, valideringsrapportene og
vision-/AI-cachene er committet, så appen viser ekte, målte tall før du har
kjørt en eneste kommando. Vil du regenerere dem selv, står kommandoene i
[§7](#7-kommandolinjeverktøy).

Er oppsettet riktig? Åpne 🏠 **Home** → **🩺 Demo readiness**. Den sjekker
data, cacher og nøkler og sier hva som eventuelt mangler. Rett etter et klon
skal alt være grønt bortsett fra `GEMINI_API_KEY`, som er valgfri.

<details>
<summary>Vil du bruke dine egne tegninger i stedet?</summary>

Legg dem under `data/raw/P&ID/` og `data/raw/SCD/`. To ting må stemme:

- **Filnavnet bærer systemnummeret** (`C025-V-HO27-P-_E-002-01.PDF` → system
  27). Systemet leses fra navnet, ikke fra tegningen — se §8.1.
- **P&ID og SCD for samme system må ha samme systemkode**, ellers finner ikke
  avstemmingen paret.

DEXPI-XML er valgfritt, men uten det faller fasitmålingen, 🧭-siden,
🔗-topologien og regelscreeningen bort — de krever strukturerte data, og det
er hele poenget deres.
</details>

### 5.5 Valgfritt: Model Broker-konfigurasjon

Sidene **⚙️ Model Broker config** og **🧩 Symbol variants** leser en
referansekonfigurasjon eksportert fra Semantum Model Broker. Fila er ikke i
repoet (ikke offentlig publisert) og forventes her:

```
data/broker/Huldra DEXPI P&ID 2.0_configuration.json
```

Mangler den, viser begge sidene en feilmelding og stopper — resten av appen
er upåvirket. Stien kan overstyres i tekstfeltet øverst på hver side.

### 5.6 Valgfritt: vision-reserve for bilde-tegninger

Noen tegninger har et tekstlag som bare inneholder tittelfelt og rutenett,
mens innholdet er grafikk. For disse finnes en Gemini-basert vision-reserve
som leser tags direkte fra tegningsbildet (rasterisert med `pypdfium2` —
ren pip-avhengighet, ingen systeminstallasjon).

```bash
export HULDRA_VISION=1               # av som standard
```

Egenskaper:

- **Utløses automatisk** kun på tag-fattige tegninger (< 3 tekst-tags).
- **Filtreres**: modellsvaret matches mot et tag-mønster før noe slippes inn.
- **Caches** til `reports/vision_cache/tags/` (én lesbar JSON per tegning) —
  gjentatte kjøringer er gratis, og kvotebegrensede kjøringer kan gjenopptas.
  **Feil caches aldri**, de prøves bare på nytt.
- **Målt**: på valideringstegningen HO11 leser reserven alle 6 fasit-tags —
  100 % presisjon og recall. I full skala: hele bunken (72 bilde-lesninger,
  360 tags) i én kjøring på gratis tier.

### 5.7 Varm cachen før en demo

```bash
python src/ai/warm_vision_cache.py "data/raw/P&ID/C025-V-HO27-P-_E-002-01.PDF"
python src/ai/warm_vision_checks.py 27 24     # regelfunn-second-opinions
```

Kjør kvelden før, se over resultatene i appen, og commit `reports/vision_cache/`
— da virker demoen selv helt offline.

---

## 6. Streamlit-appen — alle 21 sider

```bash
streamlit run src/app.py            # kjør fra prosjektroten
```

Sidene registreres i `src/nav_pages.py` (ikke en `pages/`-mappe — dette er
bevisst, se §21). Kolonnen til høyre viser hvilket nøkkelspørsmål i oppgaven
hver side svarer på.

### 6.1 Oversikt og formatargument

| Side | Hva den viser | Oppgavespørsmål |
|---|---|---|
| 🏠 **Home** (`hjem.py`) | Landingsside: hva dette er, de ærlige nøkkeltallene som KPI-er lest live fra `eval_root_cause.json`, og tre guidede stier inn i appen. Egen «demo readiness»-sjekk før presentasjon | kontekst |
| 🆚 **DEXPI vs PDF** (`dexpi_vs_pdf.py`) | Interaktiv side-om-side: samme tegning rekonstruert fra begge kilder («tags er tekst; topologi er det ikke»). Venstre panel er DEXPI-modellen med alle oppgitte koblinger, høyre er hva PDF-tekstlaget gir alene — komponenter uten lesbar tekst markeres 🔴 **?**, og høyre panel har null koblinger. Hover for å spore hva noe henger sammen med. **Alt beregnes ved lasting** av `extraction.dexpi_parser` + `extraction.tag_extractor`, for **alle 16** tegninger som har begge kilder, så siden ikke kan drive fra den målte pipelinen. Nedlastingsknapp skriver ut gjeldende visning som selvstendig HTML | PDF vs DEXPI |
| 🏭 **Plant overview** (`anleggsoversikt.py`) | Anleggsmodellen på tegningsnivå: 17 noder, én per ark, koblet der linjenumre beviser at arkene deler fysisk rør. Etableringsbildet før enhver anleggsdekkende demo | Data/LCI: én modell, ikke 17 dokumenter |

### 6.2 Systemanalyse

| Side | Hva den viser | Oppgavespørsmål |
|---|---|---|
| 📄 **System analysis (PDF)** (`system_analysis.py`) | Per system: P&ID↔SCD-avstemming, KPI-er, sikkerhetsregister, failure explorer, operatør-brief, alarm-rotårsak, live signalsimulering, interaktiv avhengighetsgraf — fra PDF-uttrekk (løkke-basert) | prosjektfase: inkonsistenser · drift: systemforståelse |
| 🧭 **System analysis (DEXPI)** (`system_analysis_dexpi.py`) | Speil av forrige side, matet fra DEXPI: **oppgitte** koblinger, kryss-løkke-konsekvenser, DEXPI↔PDF-avstemming som viser recall-gapet per tegning. Samme analysemoduler — kun input er byttet | Data/LCI: hva strukturerte formater forbedrer |
| 🏷️ **Tag register** (`tag_oversikt.py`) | Tag-register på tvers av systemer og kilder, med BOTH/PID_ONLY/SCD_ONLY-status. Kjører samme uttrekk som pipelinen, så tallene kan ikke avvike | datauttrekk og strukturering |
| 🔗 **DEXPI topology** (`dexpi_graph.py`) | Ekte `FromID→ToID`-topologi fra DEXPI-filene, tegnet med samme interaktive SVG som PDF-siden — samme verktøy, bedre data | Data/LCI |
| 🧬 **DEXPI properties** (`dexpi_egenskaper.py`) | Tag-dekoder: klikk en tag fra hverandre posisjon for posisjon, se hvilke verdier som faktisk forekommer. Model Broker har allerede gjort segmenteringen (part1/part2/part3) — den leses tilbake her | minimumskrav: tag-konvensjoner |

### 6.3 Sikkerhet og kvalitet

| Side | Hva den viser | Oppgavespørsmål |
|---|---|---|
| ⚠️ **HAZOP preparation** (`hazop.py`) | Deterministisk arbeidsark (noder → avvik → årsaker → konsekvenser → barrierer) forankret i uttrekte tags. Redigerbart med review-status og **autolagring mellom møter** (`reports/hazop_store/`), Excel-eksport i møteformat, valgfri AI-omskriving, og **vision-utdrag** der Gemini leser selve tegningen og hvert tag-forslag verifiseres mot registeret | HAZID/HAZOP-støtte |
| ⚖️ **HAZOP: PDF vs DEXPI** (`hazop_compare.py`) | Samme arbeidsark-maskineri på samme tegning, to inputformater: venstre = løkkebaserte noder fra PDF, høyre = utstyrsforankrede seksjoner fra DEXPI. Barriere-andelen tallfester sikkerhetsargumentet for DEXPI | PDF vs DEXPI + HAZOP |
| 📊 **Compliance dashboard** (`compliance_dashboard.py`) | Anleggsdekkende opprulling av de strukturelle regelfunnene (R1–R3, R8–R9) over ALLE tegninger: totaler, system×regel-varmekart, alvorlighet per system, valgfri Gemini-skrevet 3-setnings «tilstand»-oppsummering forankret i tallene. Nedbrytningstabell med filtre + CSV. Funn er **screeningkandidater**, ikke avvik | kvalitet/avvik på tvers · ledelsesrapport |

### 6.4 Drift og beslutningsstøtte

| Side | Hva den viser | Oppgavespørsmål |
|---|---|---|
| 🎛️ **Control-room assistant** (`kontrollrom.py`) | Alarmdusj-scenario: skjult feil + støyalarmer fyres samtidig. Assistenten gir strukturell brief per kandidat (**uten å kåre vinner**), operatøren beslutter, debrief skiller rot/symptom/støy. Graf med opp-/nedstrøms-markering, tid-til-settpunkt via NeqSim, valgfri forankret Gemini-Q&A. Publiserer hendelseskonteksten til resten av appen | beslutningsstøtte, alarm-rotårsak |
| 💬 **Plant Q&A** (`graf_qa.py`) | Spør hele anlegget på naturlig språk — svaret **beregnes** fra den sammenslåtte DEXPI-grafen + tag-registeret, ikke genereres av en chatbot. Intents: `downstream`, `upstream`, `neighbors`, `path`, `protects`, `trips_closing`, `loop`, `section`, `list_type`. Gemini brukes kun i kantene (tolke spørsmål inn, omformulere fakta ut) og hvert foreslått tag verifiseres mot registeret før grafen svarer | systemforståelse, avhengigheter, sikkerhetsfunksjoner |
| 🔎 **Find the drawing** (`finn_tegning.py`) | Søk i P&ID-ene på naturlig språk — rangerer ark etter en profil bygd fra tag-registeret (typekoder utvidet til ord: «PT» → *pressure transmitter*) pluss cachede 30-sekunders vision-sammendrag. Valgfri Gemini-utvidelse legger kun til søkeord (synonymer, NO↔EN). Se topptreffet med zoom/panorer | slutt å lete etter riktig ark |
| 📝 **30-sec summary** (`tegning_sammendrag.py`) | Vision-modellen leser ett P&ID-ark og gir rask orientering — hva arket viser, nøkkelutstyr, hovedfarer (HAZOP-fokus) — pluss taggene den leste, hver verifisert mot registeret (✅ i register / 🟠 ikke i register). Cachet til disk, offline-trygg | rask orientering på ukjent ark |
| 🧪 **NeqSim simulation** (`neqsim_side.py`) | To faner, begge forankret i DEXPI-eksporten: (1) **fluidoversikt** — alle fluidkoder på en tegning med NeqSim-beregnet tetthet/Z-faktor/molmasse; (2) **feilsimulering** — velg en komponent som «feiler», se hvilke objekter som isoleres strukturelt, og få den fysiske konsekvensen beregnet | kobling til simulerings-/beregningsverktøy |

### 6.5 Symboler, tegninger og struktur

| Side | Hva den viser | Oppgavespørsmål |
|---|---|---|
| 🔍 **Drawing analysis** (`tegningsanalyse.py`) | Velg en P&ID, la symbolmodellen (`gatevalve-ai`) lese den, se hvilke komponenter tegningen inneholder — med symbolbilder (brukeren lærer symbolene) og bevisbilde som viser HVOR funnene er. Inkluderer likhetspanel: hvilke andre tegninger ligner denne, målt på hva symbolmodellen fant | symbolgjenkjenning |
| 🧩 **PDF → structure** (`pid_struktur.py`) | Komponentuttrekk fra PDF-en alene (tekst-tags + CNN-ventilsymboler + rørløp sporet fra rasteren), «DEXPI-lite»-eksport og måling mot DEXPI. ✅ **Komponentinventar virker** (~62 % av tags + symbol-only ventiler tekst aldri når). ❌ **Topologi/kanttracing virker IKKE** og er forlatt — grafen er beholdt som dokumentert negativt resultat. Se [`PID_TO_STRUCTURE.md`](PID_TO_STRUCTURE.md) | hva som kan gjenskapes fra legacy-PDF, og grensene |
| ⚙️ **Model Broker config** (`broker_konfig.py`) | Les en Model Broker-konfigurasjon (205 mønstre), sammenlign den mot DEXPI-outputen, finn **dekningsgapet** (DEXPI-klasser uten mønster, mønstre uten treff) og **generer et tillegg** til konfigurasjonen fra det symbolmodellen fant | verktøykonfigurasjon som leveranse |
| 🎯 **Reference symbols** (`referansevelger.py`) | Marker én ren forekomst av et symbol, se nøyaktig hva geometrileseren får ut av det, lagre det som referanse. Fjerner tvetydigheten «feil boks eller feil lesing?» ved å la mennesket sette boksen | mønstergenerering, feilsøking |
| 🧩 **Symbol variants** (`variantkart.py`) | Hvor mange måter er en ventil tegnet på tvers av bunken, og hvor mange av dem kjenner konfigurasjonen allerede? Premisset — lest ut av konfigurasjonen, ikke antatt: Model Broker holder et **variantbibliotek** (14 mønstre mot GateValve, 3 mot CheckValve), ikke ett mønster per symboltype | hvorfor symbolgjenkjenning er vanskelig i praksis |

---

## 7. Kommandolinjeverktøy

Alt i appen har en CLI-tvilling. Kjør fra prosjektroten.

### 7.1 Anbefalt arbeidsflyt

```bash
# 1) mål uttrekket mot DEXPI-fasiten
python src/validate_against_dexpi.py --raw data/raw --out reports

# 2) bryt ned hvor recall tapes (per klasse, per tegning, null-tegninger)
python src/analyze_validation_diffs.py --out reports

# 3) tallfest recall-taket: nozzle-ekskludering + symbol-vs-tekst-splitt
python src/analyze_recall_ceiling.py --reports reports --raw data/raw

# 4) samme validering, men med vision-reserven på
export HULDRA_VISION=1
python src/validate_against_dexpi.py --raw data/raw --out reports_vision

# 5) sammenlign kanalene tekst / vision / union mot samme fasit
python src/compare_channels.py --out reports_channels

# 6) bygg tag-registeret over HELE bunken
python src/build_tag_register.py

# 7) hent ekte topologi ut av DEXPI-XML-ene
python src/analysis/parse_dexpi_data.py

# 8) generer HAZOP-arbeidsark for et system
python src/analysis/hazop_prep.py 27

# 9) DEXPI-baserte HAZOP-noder (utstyrsforankrede seksjoner) for én tegning
python src/analysis/hazop_dexpi.py "data/raw/Semantum Huldra P&IDS/.../C025-V-HO27-P-_E-002-01.DGN.xml"

# 10) selvstendig HTML-dashboard for ett system
python src/dashboard.py 27          # → reports/index.html, dobbeltklikk for å åpne
```

### 7.2 Fullstendig verktøyliste

**Pipeline og rapportering**

| Kommando | Hva den gjør |
|---|---|
| `python src/main.py [system\|filer]` | orkestrert pipeline: P&ID + SCD → graf → analyser → rapporter |
| `python src/dashboard.py <system>` | selvstendig HTML-dashboard, alt inlinet (ingen server, ingen internett) |
| `python src/build_tag_register.py` | tag-register + P&ID↔SCD-avstemming over hele bunken |
| `python src/analysis/explore_data.py` | filinventar + lesbarhetsanalyse av alle PDF-er |
| `python src/analysis/extract_system_names.py` | utleder systemnummer → systemnavn fra tittelfelt |
| `python src/analysis/visualize_more.py` | donut, stablet søyle, samforekomst-heatmap, nettverksgraf |
| `python src/analysis/ml_cluster.py` | TF-IDF + KMeans-clustering av tegninger, PCA-plott |

**Validering og evaluering**

| Kommando | Hva den måler |
|---|---|
| `python src/validate_against_dexpi.py` | presisjon/recall/F1 per tegning + TOTAL mot DEXPI-fasit |
| `python src/analyze_validation_diffs.py` | hvor recall tapes: per tag-klasse, per tegning, null-tegninger |
| `python src/analyze_recall_ceiling.py` | nozzle-justert recall + symbol-vs-tekst-splitt av bommene |
| `python src/compare_channels.py` | tekst vs vision vs union, identisk matching |
| `python src/analysis/vision_eval.py` | re-verifiserer cachede vision-kjøringer mot BEGGE registre (CONFIRMED_BOTH / RECOVERED / TEXT_ONLY / …) |
| `python src/extraction/eval_topology.py` | nodedekning + kant-P/R/F1 for PDF→struktur-lifteren |
| `python src/eval_root_cause.py` | rotårsak-hitrate over syntetiske feil i ekte topologi |
| `python tools/eval_agent.py` | kontrollrom-agenten mot harde scenarier (hit, t_correct, false positives) |
| `python measure_accuracy.py [--runs N]` | uttrekk mot håndlaget fasit i `ground_truth.txt`, per kategori |
| `python compare_extraction.py [pdf]` | vision vs deterministisk uttrekk, vision-only bøttet |

**Analyse og AI**

| Kommando | Hva den gjør |
|---|---|
| `python src/analysis/graph_qa.py "<spørsmål>"` | Plant Q&A fra kommandolinjen |
| `python src/analysis/plant_model.py` | syr alle DEXPI-tegninger sammen til ÉN graf |
| `python src/analysis/root_cause.py` | alarm → rotårsak vs konsekvens |
| `python src/analysis/control_room.py` | kandidat-brief for en alarmdusj |
| `python src/analysis/rule_screening.py` | strukturelle regelfunn (R1–R9) |
| `python src/analysis/rule_catalog.py` | utvidet regelsett (R10–R16) med klausulproveniens |
| `python src/analysis/alarm_bridge.py` | alarmpunkt → tegningstag (navnenormalisering) |
| `python src/analysis/alarm_priority.py` | alarmprioritet/-retning utledet fra tag-bokstavene |
| `python src/analysis/time_to_trip.py` | tid til settpunkt, NeqSim-korrigert (Z ≈ 0,91 ved 50 bara) |
| `python src/analysis/cause_effect.py` | leser designet C&E-logikk fra `data/cause_effect/*.csv` |
| `python src/ai/ce_vision.py <SCD-PDF>` | vision-uttrekk av C&E-matrisen fra et SCD-ark |
| `python src/ai/ce_vision.py --selftest` | hele C&E-kjeden uten API-nøkkel |
| `python src/ai/warm_vision_cache.py <pdf…>` | varm vision-cachen før demo |
| `python src/ai/warm_vision_checks.py [system…]` | varm second-opinion-cachen for regelfunn |
| `python src/analysis/neqsim_system_report.py` | fluidkoder + NeqSim-egenskaper for en hel tegning |
| `python src/analysis/simulate_component_failure.py` | strukturell + fysisk konsekvens av komponentsvikt |
| `python src/neqsim_tools/neqsim_hydrate_viz.py` | hydratkurve + animert blowdown mot hydratgrensen |
| `python tools/make_demo_incident.py --out data/demo_incident` | generer syntetisk hendelsesdatasett |

**Symbolgjenkjenning** — se [§11](#11-symbolgjenkjenning--gatevalve-ai).

---

## 8. Datagrunnlaget

### 8.1 `data/raw/` — kildetegningene

```
data/raw/
├── P&ID/                        40 filer  — 20 P&ID-ark, hvert som PDF + DGN
├── SCD/                        193 filer  — 99 PDF + 93 DGN (SCD-ark)
├── SCD Legend/                   6 filer  — legendeark (symbolforklaringer)
├── Symbols/                     16 filer  — symbolbibliotek (U999-serien, PT-100…)
└── Semantum Huldra P&IDS/
    └── Equinor 2026-02-18 …/    22 XML   — DEXPI-eksport (fasit for 16 P&ID-er)
```

Totalt: 141 PDF, 113 DGN, 22 XML. DEXPI-XML-ene dekker kun P&ID-siden —
det er derfor SCD-uttrekket ikke har en uavhengig fasit (se §19).

Filnavnene koder informasjon som brukes gjennomgående:

```
C025 - W  - HO27 - P - _E-002-01 . PDF
 │     │     │     │    │
 │     │     │     │    └── arknummer/revisjon
 │     │     │     └─────── disiplin (P = prosess, J = SCD)
 │     │     └───────────── system («HO27» → system 27)
 │     └─────────────────── V/W (områdekode)
 └───────────────────────── prosjekt-/anleggskode
```

Systemnummeret hentes fra filnavnet, ikke fra tegningsinnholdet — det er
den eneste kilden som er pålitelig når tekstlaget er flatet ut.

### 8.2 `data/processed/` — avledede datasett

| Fil | Rader | Innhold |
|---|---:|---|
| `dexpi_tags.csv` | 6 405 | ett plantobjekt per rad: id, tag, kategori, komponenttype, x/y (mm), tegning |
| `dexpi_connections.csv` | 1 900 | fysiske/signal-koblinger (grafkanter, `FromID→ToID`) |
| `dexpi_associations.csv` | 3 568 | semantiske assosiasjoner («is located in», «is a part of») |
| `tags.csv` | 639 | tags fra PDF-tekstuttrekk |
| `file_inventory.csv` | 272 | komplett filoversikt + tekstlengde per PDF (lesbarhet) |
| `fluid_codes_all_drawings.csv` | 72 | fluidkoder per tegning (`FluidCodeAssignmentClass`) |
| `clusters.csv` | 72 | KMeans-clustering av tegninger |
| `extraction_evaluation.csv` | 28 | uttrekksevaluering per tegning |

### 8.3 `reports/` — genererte artefakter

| Sti | Innhold |
|---|---|
| `tag_register.{csv,json}` | tag-registeret (854 tags i standardkjøringen) |
| `reconciliation{,_summary}.csv` | P&ID↔SCD-avstemming per system |
| `validation_report.csv` | presisjon/recall/F1 per tegning + TOTAL |
| `validation_diffs.csv` | hver enkelt MISSED/EXTRA-tag |
| `validation_diff_summary.csv` | recall-tap per klasse og tegning |
| `vision_eval.csv` | 140 vision-tags klassifisert mot begge registre |
| `eval_root_cause.json` | rotårsak-evalueringen (5 betingelser × 800 scenarier) |
| `safety_register.csv` | sikkerhetsfunksjoner utledet fra tag-typer |
| `flagged_issues.csv` · `quality_report.md` | kvalitetsflagg |
| `hazop_store/` | autolagrede HAZOP-arbeidsark (én JSON per system) |
| `hazop_system_*.xlsx` | Excel-eksport i møteformat |
| `finding_dispositions/` | ingeniørens disponering av regelfunn (godtatt/avvist/verifisert) |
| `vision_cache/` | verifiserte vision-utdrag + rasteren modellen så |
| `vision_cache/tags/` | 86 cachede vision-tag-lesninger |
| `ai_cache/` | HAZOP-nodeomskrivinger + Q&A-svar |
| `figures/` | 14 genererte figurer (donut, heatmaps, clusters, nettverksgraf) |
| `system_dependency_graph.{json,html,png}` | avhengighetsgrafen i tre formater |
| `index.html` | selvstendig dashboard |

**Parallelle rapportmapper** (samme skript, ulike innstillinger):
`reports_vision/` (vision-reserve på), `reports_vision_check/` (second-opinion
på regelfunn), `reports_unified/` (registerbygg over hele bunken — 1 463 tags),
`reports_channels/` og `reports_channels_300/` (kanaleksperimentet ved 150 og
300 dpi).

### 8.4 `data/cause_effect/` — designet styringslogikk

Avhengighetsgrafen sier hva som *kan* henge sammen; C&E-logikken sier hva
som er *designet* til å skje («LAHH tripper → steng XV»). Skjema:

```
drawing,cause_tag,effect_tag,function,source,verified,note
```

To kilder til rader: håndført av ingeniør (`verified=ja`), eller vision-uttrekk
via `src/ai/ce_vision.py` (**alltid** `verified=nei` — utkast, ikke lest logikk).
Rader med `verified=nei` vises med eksplisitt advarsel i appen. Se
[`data/cause_effect/README.md`](data/cause_effect/README.md) for full spesifikasjon.

> **Ærlig status:** mappen inneholder foreløpig ingen datarader, og prosjektet
> har **ingen uavhengig C&E-fasit**. Presisjon/recall for C&E-uttrekket er
> derfor ikke målt. `ce_vision.compare_to_manual()` er måleapparatet — det
> trenger ett håndført ark å måle mot.

### 8.5 `data/demo_incident/` — syntetisk hendelse

Én historisk-formet hendelse: 15 alarmer over 24 s, forankret i en fiktiv
nattevakt. `alarms.csv` (A&E-journalformat), `trends.csv` (historian-eksport,
1 Hz), `incident.json` (metadata + fasit for debrief). Alarmrekkefølgen og
kaskaden følger den *ekte* strukturmodellen; tidsstempler og prosessverdier
er generert. Dette viser **formatet og arbeidsflyten** for en historian-koblet
pilot — det er ikke målte anleggsdata.

---

## 9. Uttrekkspipelinen i detalj

### 9.1 Tre komplementære pass

Tags opptrer i flere former på disse tegningene, og hvert pass tar én form:

**Pass a — inline sammensatte tags.** Mønstergjenkjenning på tekstlaget:
`27-PT4805`, kryss-system `63-XV4800`. Redundante instrumenter skrevet med
kombinert suffiks (`27-PT4250A/B` = to fysiske enheter i én etikett) ekspanderes
så **begge** ben fanges.

**Pass b — stablede tags i instrumentbobler.** Typen står over nummeret i én
kolonne (`PT` / `4805`). Disse rekombineres ved å klynge posisjonerte ord fra
`pdfplumber` — samme nærhetsterskler som `tag_locator.py` bruker når den skal
tegne bokser rundt taggen igjen. Systemprefikset (`27-`) kommer fra **filnavnet**,
ikke fra tegningen.

**Pass c — vision-reserve (opt-in).** Utløses automatisk når pass a+b gir
< 3 tags (bilde-tegning). Rasteriserer siden med `pypdfium2`, sender til Gemini,
filtrerer svaret mot et tag-mønster. Se §5.6.

### 9.2 Normalisering og matching

Samme fysiske instrument skrives på mange måter i kildene:

```
HV 2264   ≡   13-HV-2264   ≡   13-2264HV
```

Normaliseringen kollapser på **(type, nummer)**-paret: store bokstaver,
skilletegn fjernet, prefiks/suffiks-varianter samlet. Dette er
`_type_number`-mønsteret i `ai/hazop_vision.py`, og det brukes både i
validering, tag-verifisering og alarm-broen (`analysis/alarm_bridge.py`,
som håndterer `27PT4805` / `27-PT-4805` / `HO27_PT_4805`).

### 9.3 Tag-taksonomi

`src/config.py` kategoriserer hver typekode:

| Kategori | Koder |
|---|---|
| `input` | PT, TT, LT, FT, PI, TI, LI, FI, PDI, PDT, PDIT, AE, SI, ZS, ZL, LSH, LSL, LSHH, PSH, FSH, PSE |
| `logic` | PIC, LIC, TIC, FIC, PY, LY, TY, FY, HS, XY |
| `output` | XV, ZV, FV, LV, PV, FO, PSV |
| `equipment` | KA (kompressor), PA (pumpe), VG (trykktank), VD (drum) |

Sikkerhetsfunksjoner plukkes ut av `SAFETY_TYPES` (XV, PSV, LSH, LSHH, PSH,
FSH, HS, ZS, ZL) og `SAFETY_SUFFIXES` (AHH, ALL, HH, LL). Bokstavene bærer
også alarmprioritet og -retning — `analysis/alarm_priority.py` utleder
«LAHH = Level Alarm High-High → trip-nivå, retning HIGH» direkte fra taggen.

### 9.4 Fra tag til objekt til graf

```
rå tag  →  tag_parser  →  EngineeringObject(tag, system, type, nummer, kategori)
                                     │
                                     ├──► build_dependency_graph  (løkkebasert, PDF)
                                     └──► dexpi_parser + plant_model  (oppgitt, DEXPI)
```

Den løkkebaserte grafen er **ærlig merket som en tilnærming**: den sporer ikke
rør- eller signallinjer, men grupperer tags i funksjonelle løkker etter delt
løkke-id (system + nummer) og kobler `input → logic → output` innenfor hver
løkke. Ekte kryss-løkke-topologi krever DEXPI — som er hele poenget med
DEXPI-sidene.

`plant_model.py` syr alle DEXPI-tegninger sammen til ÉN graf via to
sammenføyningsmekanismer strukturerte data gir: **delte linjenumre** (samme
rørtag på to ark ER den samme fysiske linjen) og **delte tags**. Det er dette
som gjør kryss-tegnings-resonnering mulig — feil respekterer ikke arkgrenser.

---

## 10. Validering og målemetode

### 10.1 Hvordan valideringen fungerer

`validate_against_dexpi.py` matcher hver P&ID mot sin DEXPI-XML på
tegningsnummer, normaliserer begge tag-settene og regner presisjon, recall og F1.
Fasit-tags hentes fra fem steder i XML-en:

```xml
TagName="27-PT4805"                                    instrument/ventil-elementer
<GenericAttribute Name="tagName"              …>       gjentatt instrumenttag
<GenericAttribute Name="valveTag"             …>       håndventiler (27-4510PV)
<GenericAttribute Name="TagNameAssignmentClass" …>     hovedutstyr
<GenericAttribute Name="PipelineTag"          …>       rørlinjetags
```

Hver uenighet logges som **MISSED** (i XML, ikke funnet) eller **EXTRA**
(funnet, ikke i XML), slik at hvert avvik kan spores til enten en uttrekksfeil
eller reell dokumentasjonsdrift.

Kun tegninger med en XML skåres. Delvis fasitdekning svekker ikke tallet: man
validerer alltid på et utvalg, og et målt tall på utvalget estimerer resten.

### 10.2 De tre feilmodusene i recall-gapet

1. **Tette tegninger — reell, gjenværende uttreksfeil.** HO27-002, HO20-002,
   HO82 har både lav recall og flere falske treff. Boble-rekombinasjonen sliter
   når tegningen er tett. Det eneste sporet der mer arbeid kan flytte tallet.
2. **Symbol-only tags — metodens tak.** 60 % av valve-/linje-bommene finnes
   ikke som tekst i PDF-en overhodet. Ingen regel kan hente ut tekst som ikke
   er der.
3. **Bilde-tegninger — løst.** HO11 hadde tekstlag med kun tittelfelt og
   rutenett. Vision-reserven leser nå alle 6 fasit-tags.

### 10.3 Kanaleksperimentet

Med hele bunken vision-lest ble et siste eksperiment mulig: kjøre vision på
**alle** 16 fasit-tegningene og skåre tre kanaler med identisk matching
(`compare_channels.py` importerer matchingen fra validatoren — den kopierer
den ikke).

**Union bryter dødvannet i de tette tegningene:** +6 poeng recall for
−3 poeng presisjon, og gevinsten kommer nettopp der ingen tidligere forbedring
nådde (HO27-002: 27 → 42 %, HO20-002: 44 → 57 %, HO63/HO64 når 98–100 %).

**Vision alene er ikke et alternativ — nå målt, ikke antatt.** 24 % recall:
modellen kollapser på de største arkene (HO27-001, HO13, HO82: 0 %) og
hallusinerer på HO20-001 (19 % presisjon). Der den virker er den skarp
(94–100 % presisjon på seks tegninger).

**Høyere oppløsning hjelper ikke der det teller.** De tre kollaps-tegningene
ble re-lest ved 300 dpi (`reports_channels_300/`). HO27-001 gikk 0 → 35 tags
med 89 % presisjon — men alt vision nå leste hadde tekstkanalen fra før, så
union sto stille. HO13 ga fortsatt null (flaskehalsen er innholdsmengde per
bilde, ikke skarphet — flislegging er medisinen). Og HO82 produserte 8
plausible, internt konsistente linjetags i jevn serie som **alle** var
fraværende i fasiten — en selvsikker hallusinasjon som passerte mønsterfilteret.
Adaptiv dpi-økning er derfor ikke tatt i produksjon: null union-gevinst,
målbar presisjonsrisiko. HO82-serien er samtidig det beste enkelteksemplet i
materialet på hvorfor «LLM foreslår, register verifiserer» er nødvendig —
**plausibilitet er ikke sannhet**.

### 10.4 Rotårsak-evalueringen

`src/eval_root_cause.py` gjør assistentens kjernepåstand («roten forklarer
mest») til et reproduserbart tall. For hver syntetiske feil bygges den
forskjøvne alarmdusjen (kaskade + støy), samme `candidate_brief` som UI-et
bruker kjøres, og rangeringen til den *sanne* roten registreres.

| Betingelse | Scenarier | Hit #1 | Hit topp-3 | Snittrangering |
|---|---:|---:|---:|---:|
| Ideell (én feil, alle alarmer ringer) | 800 | 100 % | 100 % | 1,00 |
| 20 % tapte alarmer | 800 | 98,1 % | 99,4 % | 1,03 |
| 40 % tapte alarmer (speiler recall-gapet) | 800 | 94,0 % | 97,2 % | 1,09 |
| Dobbel uavhengig feil | 800 | 95,0 % | 95,0 % | 1,00 |
| Dobbel feil + 20 % tap (hardest) | 800 | 94,2 % | 94,0 % | 1,01 |

Kjørt på **ekte Huldra-topologi**, 5 seeds × 4 støynivåer × 40 feil.
100 %-tallet under ideelle betingelser er forventet av konstruksjon —
20 %-tallet er den ekte testen.

`tools/eval_agent.py` er den harde varianten: seks scenarieakser (ren kaskade,
støyende trender, hard støy, støyalarm først, dobbel feil, langsom drift) og
måler i tillegg `t_correct` (hvor tidlig den ledende hypotesen ble — og forble —
korrekt) og prematurandel for tidlige varsler.

### 10.5 Vision-evalueringen

`analysis/vision_eval.py` besvarer spørsmålet «hvor mange av vision-modellens
*nye kandidater* er ekte?» — uten nye API-kall. Den leser de cachede
vision-kjøringene og re-verifiserer hvert modell-nevnt tag mot **begge**
registrene:

| Klasse | Betydning |
|---|---|
| `CONFIRMED_BOTH` | i tekstlaget og i DEXPI — korrekt lesing, ikke noe nytt |
| `RECOVERED` | i DEXPI, **ikke** i tekstlaget — vision gjenvant en bit av recall-gapet |
| `TEXT_ONLY` | i tekstlaget, ikke i DEXPI |
| øvrige | kandidat/ukjent — flagges, aldri antas |

---

## 11. Symbolgjenkjenning — `gatevalve-ai`

Bevisst smal modell, bygget nedenfra: to symboler, ett spørsmål, TRUE/FALSE-svar.
Full dokumentasjon: [`gatevalve-ai/README.md`](gatevalve-ai/README.md).

### 11.1 Arkitektur

```
lær fra legende  →  kandidater  →  verifiser  →  tilstand
```

1. **Læring** (`learn_from_legend.py`) — modellen leser legendearket selv:
   finner tekstene «GATE VALVE, OPEN»/«CLOSE», klipper symbolfeltet, isolerer
   KUN sløyfen (tekst maskeres, rammer forkastes). Selv skillet åpen/lukket
   læres herfra (fyllgrad 0,14 vs 0,43).
2. **Kandidater** — malmatch (begge sløyfer, flere størrelser, 0°/90°), kun
   lokale topper, NMS.
3. **Verifisering** — geometriske krav tekst, piler, sirkler og stolper ikke
   klarer å etterligne. Gjennomgående rørlinjer strippes først.
4. **Tilstand** — åpen vs lukket avgjøres i ORIGINAL oppløsning ved erosjon
   med strektykkelsen (omriss forsvinner, fyll overlever) — oppløsningsuavhengig.

**Oppløsnings-ærlighet:** er symbolet for lite relativt til strektykkelsen
(< ~7,5× eller < 18 px), finnes ikke åpen/lukket-informasjonen fysisk i bildet.
Da svarer modellen «tilstand usikker» i stedet for å gjette.

### 11.2 Målte resultater

| Tegning | Fasit | Modellens svar |
|---|---|---|
| PT-111 valve-legende (150 dpi) | begge finnes | OPEN **TRUE** (0,87) · CLOSED **TRUE** (0,96) |
| PT-110 fitting-legende (150 dpi) | ingen | OPEN **FALSE** · CLOSED **FALSE** |
| HO27 P&ID (40 dpi skann, 33 gate valves) | finnes | «tilstand usikker» **TRUE** |
| HO11 rammeark (40 dpi skann) | ingen | alt **FALSE** |

Veiledet læring (HOG + RBF-SVM):

| Oppsett | Syntetisk validering | Kommentar |
|---|---:|---|
| Første trening | 49 % | maler fra runde 1 var forurenset (ramme-rester) |
| + rene maler | 76 % | rotårsaken funnet og fikset |
| + ikke-ventiler i bakgrunnsklassen | 74 % | mer realistisk negativklasse |

### 11.3 Tre lærdommer

1. **Treningsdata-kvalitet slår alt.** Én forurenset malkilde kostet 25
   prosentpoeng. Sjekk dataene visuelt før du klandrer modellen.
2. **Informasjon som er borte, kan ikke læres tilbake.** På ~40 dpi er
   åpen/lukket-skillet fysisk utvisket — samme grense gjelder mennesker.
3. **Negativklassen må dekke det som faktisk finnes.** Klassifikatoren dyttet
   fittings inn i ventilklasser helt til den fikk se fittings i trening.
   Presisjon kommer fra det modellen har lært å **avvise**.

### 11.4 Bruk

```bash
cd gatevalve-ai
python learn_from_legend.py U999-1-000--PT-111-01.PDF    # én gang
python check_drawing.py min_pid.pdf --dpi 200            # geometrisk pipeline
python make_synthetic.py                                 # syntetiske treningsdata
python make_dataset.py --dpi 200                         # ekte merkede utsnitt fra XML
python train_classifier.py                               # HOG + SVM
python classify_drawing.py min_pid.pdf                   # trent modell, ende-til-ende
python run_folds.py                                      # kryssvalidering
python make_report.py                                    # samlerapport
```

Ut per tegning: TRUE/FALSE i terminalen, `<navn>_verdict.json` (maskinlesbart)
og `<navn>_proof.png` (funn markert: grønn = åpen, rød = lukket, oransje =
usikker). Deteksjoner lagres i `gatevalve-ai/results/*_detections.json` og
brukes videre av `pid_topology.py` og `analysis/symbol_crosscheck.py`.

### 11.5 Symbol-kryssjekk uten API-kall

`analysis/symbol_crosscheck.py` gir en **lokal, offline second opinion** på
regelfunn: der `ai/hazop_vision.vision_check_finding` spør en skymodell om å
se på arket, gjør denne modulen samme jobb med de lokale CNN-deteksjonene.
Ingen API-kall, deterministisk, kjører offline. Broen er koordinatbasert.

---

## 12. PDF → struktur (DEXPI-lite)

Den **konstruktive** siden av formatargumentet: resten av repoet *måler* hva
legacy-PDF taper; denne prototypen prøver å *produsere* den manglende
strukturen fra tegningen selv — og fester et målt tall på resultatet.

### Dommen

| | Status |
|---|---|
| ✅ **Komponentinventar fra PDF** | **VIRKER.** ~62 % av DEXPI-tags **pluss ~33 symbol-only ventiler per tegning** som tekstlaget ikke kan se. Emitteres som en strukturert, nedlastbar liste |
| ❌ **Topologi / kanttracing** | **VIRKER IKKE på disse dataene. Forlatt.** Av 249 tag-til-tag-adjacenser over 16 tegninger er kun **4** i det hele tatt skårbare |

**Å gå fra legacy-PDF til en koblet DEXPI-modell er ikke oppnåelig med denne
tilnærmingen.** Kant-outputen er beholdt kun som illustrasjon av forsøket og
feilmodusene — ikke som gjenvunnet topologi.

### Hvorfor topologien feilet — og hvorfor det er et funn

1. **Fysisk rør modelleres gjennom *utaggede* mellomelementer.** I denne
   Semantum-eksporten er et rørløp `komponent → nozzle → rørsegment → nozzle →
   komponent`, der nozzler og segmenter ikke bærer tag. Direkte tag-til-tag-
   adjacens finnes derfor knapt — koblingen lever på elementer en tag-nivå-
   konsument aldri ser.
2. **Node-recall komponerer på begge endepunkter.** En kant er kun skårbar hvis
   *begge* tags ble uttrukket; ved 62 % nodedekning er det ~0,38 av kantene
   allerede før årsak (1).
3. **Det meste eksporten kaller *connectivity* er signal-/løkkekoblinger**
   (`PT↔PI`, `ZS↔ZL`, `FIC↔FT` — samme løkkenummer), ikke sporbart prosessrør.
   Rastersporeren gjenvinner *fysisk* linjeadjacens, som er reell og internt
   konsistent, men er ganske enkelt **en annen graf** enn eksportens
   funksjonelle modell.

### Direkte input til «minimumskrav for maskinlesbare leveranser»

- **Krev tagget, tag-til-tag-koblingsinformasjon**, eller en dokumentert,
  oppløsbar mapping fra rørsegment-/nozzle-elementer til komponentene de
  forbinder. Ellers må selv en *native DEXPI*-konsument utlede topologi på nytt.
- **Disambiguer koblingssemantikk** (prosessrør vs signal/funksjonell løkke) —
  «koblet» betyr to forskjellige ting i dag.
- En PDF→struktur-lift er levedyktig for **komponentinventar** i dag;
  **topologi** fra legacy-PDF krever symbolforankrede nodeposisjoner og full
  linjefølging, og er det vanskeligere, senere steget.

### Kjør den

```bash
python src/extraction/pid_topology.py C025-V-HO27-P-_E-002-01   # én tegning → statistikk
python src/extraction/eval_topology.py                          # mål alle 16
```

Utdata skrives til `reports/pid_structure/`. Full analyse inkludert
symbolforankrings-eksperimentet: [`PID_TO_STRUCTURE.md`](PID_TO_STRUCTURE.md).

---

## 13. Model Broker-sporet

Semantum Model Broker er det kommersielle verktøyet som produserte DEXPI-filene.
Tre moduler undersøker hvordan man *konfigurerer* et slikt verktøy — som er den
reelle jobben når nye tegninger skal digitaliseres.

**Premisset, lest ut av konfigurasjonen (ikke antatt):** en Model Broker-
konfigurasjon er **ikke** ett mønster per symboltype. Den er et
**variantbibliotek** som vokste etter hvert som nye ark ble møtt. Huldra-
konfigurasjonen holder 205 mønstre, hvorav **14 mot GateValve** (1 til 65
primitiver, fem av dem med navnet «Gate Valve Closed»), 8 mot
ControlledActuator og 3 mot CheckValve.

| Modul | Hva den gjør |
|---|---|
| `analysis/broker_config.py` | leser konfigurasjonen, finner **dekningsgapet** (DEXPI-klasser i outputen uten mønster; mønstre uten treff), og **genererer et tillegg** fra det symbolmodellen fant |
| `analysis/symbol_reference.py` | et menneske plukker én ren forekomst av et symbol; den blir fasit for hva symbolet består av, og alt annet måles mot den. Løser generatorens feilmodus: den manglet ikke kunnskap om ventiler, den manglet en *referanse* — gitt en region full av primitiver kunne den ikke skille «disse fem kurvene er ventilen» fra «denne ene kurven er en rørbend» |
| `analysis/variant_survey.py` | hvor mange måter er en ventil tegnet på tvers av bunken, og hvor mange av dem kjenner konfigurasjonen? |
| `analysis/dexpi_properties.py` | hva er faktisk I DEXPI-filene — objektklasser, generiske attributter, koblingspunkter, og tag-dekomposisjonen Model Broker allerede utførte |

Et mønster er ikke en bounding box: det er et sett vektorprimitiver med
kontrollpunkt-koordinater i lokalt koordinatsystem, pluss terminaler
(koblingspunkter med posisjon og kardinalitet), pluss en mapping til en
DEXPI-klasse, pluss ~15 toleranseparametre. `src/scripts/geometri_diagnose.py`
finnes for når geometrileseren ikke finner noe: den dumper hva `pdfplumber`
faktisk ser, i seks varianter, så du ser hvilken (om noen) treffer.

---

## 14. AI-laget

### 14.1 Prinsippene

1. **AI foreslår, register verifiserer.** Hvert tag en modell nevner
   klassifiseres mot tag-registeret: `verified` (finnes i uttrekket),
   `new_candidate` (velformet, ikke i registeret), `unknown`. Et uverifisert
   tag skjules ikke — det **flagges**.
2. **AI er alltid valgfritt.** Hver AI-funksjon har en deterministisk
   fallback. Uten `GEMINI_API_KEY` virker uttrekk, avstemming, grafer,
   HAZOP-ark, regelscreening og kontrollrom-brief uendret.
3. **AI brukes i kantene, ikke i kjernen.** I Plant Q&A tolker modellen
   spørsmålet inn og omformulerer fakta ut — men **grafen** svarer.
4. **Alt caches til disk.** Demoen skal aldri henge på at et API svarer i
   øyeblikket. Cachede svar vises med tidsstempel, så ingen forveksler dem
   med et live kall. **Feil caches aldri.**

### 14.2 Modulene

| Modul | Rolle |
|---|---|
| `ai/gemini_client.py` | ÉN langlivet klient for hele appen. Løser den kjente `Cannot send a request, as the client has been closed` under Streamlit: engangs-klienten `genai.Client().models.generate_content(...)` holdes ikke av noe, og kan bli GC-et mellom reruns. Klienten gjenopprettes transparent hvis den melder seg lukket |
| `ai/ai_cache.py` | diskcache for alle AI-utdata: vision-utdrag, rasteren modellen så, HAZOP-nodeomskrivinger |
| `ai/hazop_vision.py` | vision-assistert HAZOP-utdrag + `verify_tags`/`_type_number` — verifiseringsmønsteret hele repoet bruker |
| `ai/drawing_summary.py` | 30-sekunders orientering på ett ark, hvert tag verifisert |
| `ai/ce_vision.py` | leser C&E-matrisen av SCD-ark → utkastrader (alltid `verified=nei`) |
| `ai/explain_system.py` | naturlig­språklig systemsammendrag, faller tilbake på mal |
| `ai/operator_brief.py` | operatør-brief med fast struktur (SITUATION · POSSIBLE FAILURE MODES · IMMEDIATE IMPACT · WHERE TO INVESTIGATE · RECOMMENDED FIRST CHECKS · NOTE). To implementasjoner bak én funksjon: deterministisk mal (offline) og AI-versjon på **samme fakta** |
| `ai/warm_vision_cache.py` · `ai/warm_vision_checks.py` | kveld-før-demo-rutiner |
| `extraction/vision_extract.py` | vision-tag-uttrekk med gjenopptakbar diskcache |

### 14.3 Hvorfor verifiseringen er hele poenget

En multimodal modell som leser en tett P&ID gjør selvsikre transkripsjonsfeil
(`LSL548` vs `LSL0548` er et kjent duplikatmønster i dette datasettet) og kan
finne på plausible tags. Et **uverifisert** vision-utdrag er derfor verre enn
ingen. HO82-serien i §10.3 — 8 plausible, internt konsistente, helt oppdiktede
linjetags — er beviset.

---

## 15. Regelkatalogen (R1–R16)

Regelscreening finner det tegningen **ikke** viser. HAZOP-arket beskriver avvik
for det som ER på tegningen; regelmodulene finner det som ser ut til å MANGLE.

> **Dette krever beviselig strukturerte data.** Fra en PDF kan fravær av en
> linje ikke skilles fra et uttrekksbom (45 %-recall-gapet). Regelmodulene
> kjører derfor **kun på DEXPI-modellen**.

> **Funn er screeningkandidater, ikke avvik.** Hver regel bærer en peker til
> standarden den utleder fra, og `analysis/finding_disposition.py` lar en
> ingeniør lukke sløyfen: *godtatt* (reelt gap), *avvist* (falsk positiv, med
> begrunnelse) eller *verifisert* (barrieren finnes på arket, bare ikke i
> uttrekket). Disponeringen lagres på en **stabil funn-id** (regel + tags), så
> den overlever en rerun.

| Regel | Hva den finner | Standardfamilie |
|---|---|---|
| **R1** | seksjon med trykkregulering/-måling, men ingen avlastningsvei | NORSOK P-001 / API 521 |
| **R2** | SHH/SLL-trippfunksjon uten aksjonsvei (ingen XV/ventil) | NORSOK S-001 / IEC 61511 |
| **R3** | seksjon med ≥ 4 medlemmer, men ingen trykkovervåking | NORSOK P-001 |
| **R4** | måleinstrument ikke gjenfunnet på SCD | NORSOK I-005, B.2.2 |
| **R5** | aktuert ventil ikke gjenfunnet på SCD | NORSOK I-005, B.2.1.3 |
| **R6** | shutdown-funksjon ikke gjenfunnet på SCD | NORSOK I-005, B.2.3.2 |
| **R7** | reguleringsfunksjon ikke gjenfunnet på SCD | NORSOK I-005, B.2.3.1 |
| **R8** | aktuert nedstengingsventil (XV/ESV) uten posisjonstilbakemelding | NORSOK I-001 / I-005 |
| **R9** | trippsensor som er eneste ben (ingen voting) | IEC 61511 / NORSOK I-002 |
| **R10–R12** | henger den **designede** C&E-logikken sammen? | NORSOK I-005 (nedstengingslogikk) |
| **R13** | strukturelle funn over én tegnings DEXPI-modell | NORSOK P-001 / API 521 |
| **R14** | løkkenivå-funn | NORSOK I-005 / P-002 |
| **R15** | redundansfunn (anleggsdekkende) | IEC 61511 |
| **R16** | nær-duplikate tags (anleggsdekkende) | NORSOK Z-001 |

**Klausulproveniens er obligatorisk.** `rule_catalog.cite()` **reiser feil** på
ukjent proveniens. Tre nivåer, med vilje ubehagelig tydelige: `verified`
(klausultekst er sjekket), og to svakere nivåer som merkes som sådan i UI-et.
R1–R3 og R8–R9 er implementert i `rule_screening.py` og brukes av
compliance-dashboardet; R10–R16 ligger i `rule_catalog.py`, som utvider
**uten å røre** `screen()`/`screen_scd_coverage()` — de gir bit-identisk
resultat som før, så `hazop.py`, `compliance_dashboard.py` og
`warm_vision_checks.py` er upåvirket.

---

## 16. Gjenbrukbare prompts, agenter og mønstre

Oppgaven etterspør gjenbrukbare artefakter. De viktigste, med plassering:

| Artefakt | Hvor | Hva den gjør |
|---|---|---|
| **Tag-verifiseringsmønsteret** | `verify_tags`/`_type_number` i `ai/hazop_vision.py` | normaliser på (type, nummer)-paret på tvers av skrivemåter (`HV 2264` ≡ `13-HV-2264` ≡ `13-2264HV`), klassifiser hvert AI-nevnt tag som bekreftet/kandidat/ukjent. **Prosjektets viktigste gjenbrukbare idé** — gjelder langt utover HAZOP |
| **HAZOP-omskriving** | `HAZOP_PROMPT` i `analysis/hazop_prep.py` | omskriv/utvid et arbeidsark, kun tags fra gitt liste, generisk merkes eksplisitt |
| **Vision-lesing av tegning** | `PROMPT` i `ai/hazop_vision.py` og `extraction/vision_extract.py` | strukturert JSON, transkriber kun leselige tags, aldri finn opp — kombinert med mønsterfilter på svaret |
| **Forankret operatør-Q&A** | prompten i `kontrollrom.py` | svar kun fra gitte fakta, aldri finn opp tags, ikke avslør fasit i treningsmodus |
| **Intent-ekstraksjon til graf-query** | `_INTENTS` + parser i `analysis/graph_qa.py` | fritt formulert spørsmål → `{"intent": …, "tags": [...]}`; grafen svarer, ikke modellen |
| **Query-utvidelse uten å endre svaret** | `analysis/drawing_search.py` | AI legger **kun til** søkeord (synonymer, NO↔EN); rangeringen er fortsatt deterministisk |
| **Delt AI-klient** | `ai/gemini_client.py` | én langlivet klient med gjenoppretting (løser «client has been closed» under Streamlit) |
| **Disk-cache-mønsteret** | `ai/ai_cache.py`, `extraction/vision_extract.py` | vellykkede svar caches med tidsstempel; **feil caches aldri**. Gjør kvotebegrensede kjøringer gjenopptakbare og demoer offline-trygge |
| **Struktur-agnostisk motor** | `analysis/control_room.py` | tar alarmer + graf, gir brief. Bytt scenariegeneratoren med en alarmfeed, så er samme brief operativ støtte — det er pilotsteget |
| **Adapter mot fremmed CLI-modul** | `analysis/neqsim_seam.py` | fanger stdout fra en modul som ikke skal endres, degraderer til klar melding i stedet for exception. Kontrollrommet skal aldri krasje fordi en konsekvensberegning var utilgjengelig |

---

## 17. Verktøy, lisenser og driftserfaring

### 17.1 Kjernestack (åpen kildekode, ingen lisenskost)

| Pakke | Rolle |
|---|---|
| Python 3.12+ | språk |
| `streamlit` ≥ 1.36 | app-rammeverk (krever `st.navigation`/`st.Page`) |
| `pdfplumber` | tekst + **posisjonerte ord** + vektorgeometri (valgt over PyMuPDF nettopp for de posisjonerte ordene — nødvendig for å rekombinere stablede boble-tags) |
| `pymupdf` | supplerende PDF-lesing |
| `pypdfium2` | rasterisering (ren pip-avhengighet — ingen systeminstallasjon, i motsetning til Poppler/Ghostscript) |
| `networkx` | grafmodellen |
| `pandas` · `numpy` · `scipy` | datahåndtering |
| `scikit-learn` | clustering, HOG+SVM |
| `matplotlib` · `seaborn` · `altair` · `plotly` | visualisering |
| `openpyxl` | HAZOP-eksport i Excel-møteformat |
| `pillow` | bildebehandling |
| `python-dotenv` | `.env`-håndtering |
| `google-genai` | Gemini-klient |
| `neqsim` ≥ 3.0 | termodynamikk (Apache 2.0, **krever Java 8+**) |

Valgfritt: `anthropic` ≥ 0.40 (`uv sync --extra anthropic`) som alternativ
brief-generator.

### 17.2 AI-tjenester

**Google Gemini — én tjeneste, én nøkkel, for hele AI-laget** inkludert
vision-reserven. Gratis tier holdt til all utvikling og demo, inkludert full
vision-lesning av hele tegningsbunken — takket være disk-caching.

**Erfart driftsrisiko:** modellgenerasjoner avvikles på uker-til-måneder.
`gemini-2.5-flash-lite` forsvant for nye brukere **midt i prosjektperioden**.
Mottiltaket er todelt og bør være standard i enhver produksjonsintegrasjon:

1. **Konfigurerbart modellvalg** (`GEMINI_MODEL`) — byttet ble gjort med én
   miljøvariabel, ingen kodeendring.
2. **Validering mot fasit etter bytte** — HO11 gikk fra 2 til 6 av 6 treff
   etter overgangen til `gemini-3.1-flash-lite`. Uten fasiten ville vi ikke
   visst om byttet var en forbedring eller en regresjon.

### 17.3 Kommersielle verktøy

**Semantum Model Broker** produserte DEXPI-filene som fungerer som fasit.
Kommersielt verktøy; filene var levert som del av datasettet. Se §13 for hva
konfigurasjonen av et slikt verktøy faktisk innebærer.

### 17.4 Agentiske utviklingsverktøy

Agentiske kodeverktøy ble brukt gjennom hele utviklingen og var avgjørende for
tempoet — se metodekapitlet i rapporten. Arbeidsmåten som ga resultatene er
enkel og gjentakbar:

> **valider → les diff → én fokusert fiks → mål igjen**

Den løftet recall fra 26 % til 55 % i tre iterasjoner, hver på én kodelinje.
Dokumentert i [`Results.md`](Results.md).

---

## 18. Data, sikkerhet og compliance

- Kun **offentlig publiserte** Huldra-data og syntetiske eksempler er brukt.
  Lisensen ligger i repoet: `data/Equinor open data sharing license - Huldra.pdf`.
- **Ingen** intern, begrenset eller konfidensiell informasjon er lastet opp til
  AI-tjenester.
- API-nøkler ligger i `.env`, som er gitignorert. Ingen nøkler i kode, historikk
  eller rapporter.
- **Alle alarm-, trend- og sensordata i demonstrasjonene er syntetiske.**
  `data/demo_incident/` er generert; tidsstempler og prosessverdier er ikke
  målte anleggsdata. Alarmrekkefølge og kaskade følger den ekte strukturmodellen,
  men det gjør dem ikke til virkelige hendelser.
- Model Broker-konfigurasjonen (`data/broker/…json`) er **ikke** i repoet — den
  er ikke offentlig publisert. Sider som trenger den melder fra og stopper.
- Genererte varianter av broker-filer (`*__varianter.json`, `*__plus_*.json`)
  er gitignorert.
- HAZOP-arbeidsark regenereres ved hver sidelasting og har ustabil radrekkefølge
  — de er artefakter, ikke versjonerte resultater, og er derfor gitignorert
  (`reports/hazop_worksheet.csv`, `reports/hazop_system_*.xlsx`,
  `reports/hazop_{pdf,dexpi}_*.csv`). Den **lagrede** tilstanden i
  `reports/hazop_store/` er derimot bevisst versjonerbar.

---

## 19. Kjente begrensninger

**Uttrekk**

- Recall-taket er i hovedsak **metodens tak**, ikke en feil som kan fikses i
  tekstuttrekk — og det er nå målt: 60 % av valve-/linje-bommene er symbol-only,
  og taket for tekstmetoden er ~74 % recall (eks. nozzler). Det er selve
  DEXPI-argumentet, i tall.
- **Fasiten har selv hull.** Flere «EXTRA»-treff viste seg å være ekte tags som
  manglet i XML-en, så den reelle presisjonen er noe **høyere** enn 87 %.
- **SCD-ene skåres ikke** — DEXPI-filene dekker kun P&ID. SCD-siden brukes i
  P&ID↔SCD-avstemmingen, men er ikke målt mot en ekstern fasit.
- Rundt **to tredjedeler av SCD-ene mangler lesbart tekstlag helt**
  (bildeeksporter) — enda et argument for strukturerte leveranser. Disse leses
  nå av vision-reserven (360 tags fra 45 bilde-ark, cachet og reproduserbart).
- Tag-registeret bygges på den validerte ekstraktoren (samme kodevei som
  valideringen), så valideringstallene gjelder hele kjeden.

**Topologi og grafer**

- PDF-avhengighetsgrafen er **løkke-basert** — koblinger *innen* løkker antas.
  Ekte kryss-løkke-topologi krever DEXPI, som DEXPI-sidene viser.
- **PDF→DEXPI-topologi er ikke oppnåelig** med rastersporing på disse dataene
  (§12). Komponentinventar virker; kanttracing gjør ikke.
- Kontrollrom-assistenten viser **strukturell nåbarhet, ikke prosesskonsekvens**.
  Grafen kjenner ikke redundans, bypass eller reguleringsmarginer.

**HAZOP og regler**

- DEXPI HAZOP-seksjoner er **grafbaserte tilnærminger** til en HAZOP-leders
  nodekutt. Tegninger med utagget utstyr gir grove seksjoner — som i seg selv
  er et minimumskrav-funn.
- Løkkebaserte HAZOP-noder (PDF-siden) **tilnærmer, men erstatter ikke**
  seksjonsbaserte noder.
- Regelfunn er **screeningkandidater**, ikke avvik. Standardreferansene er
  indikative; kun de merket `verified` har sjekket klausultekst.
- Et lagret HAZOP-ark er et **øyeblikksbilde** av uttrekket det ble bygget fra.
  En egen knapp bygger nytt fra dagens uttrekk.

**C&E og AI**

- Prosjektet har **ingen uavhengig C&E-fasit**. Presisjon/recall for
  C&E-vision-uttrekket er derfor ikke målt (§8.4).
- Vision alene er **ikke** et alternativ til tekstuttrekk (24 % recall, kollapser
  på store ark, kan hallusinere selvsikkert). Den er en reserve og et opt-in
  union-tillegg.
- Modell-livssykluser på uker-til-måneder er en reell driftsrisiko ved
  gratis-tier-API-er (§17.2).

**Symbolgjenkjenning**

- På ~40 dpi-skann er antall funn omtrentlig og åpen/lukket **utilgjengelig** —
  informasjonen er fysisk borte i rasteren. Kjør originale PDF-er på 150–300 dpi.
- Roterte ventiler håndteres i 0°/90°; skrå (45°) ventiler tas ikke.
- Modellen svarer på **tilstedeværelse, ikke telling** — «antall funn» er en
  bonus, ikke et løfte.

---

## 20. Feilsøking

| Symptom | Årsak og løsning |
|---|---|
| `Cannot send a request, as the client has been closed` | engangs-Gemini-klient GC-et av Streamlit. **Bruk `ai/gemini_client.generate()`** — den holder én langlivet klient og gjenoppretter den ved behov |
| Rød banner: «Designsystemet ble ikke lastet» | `src/ui.py` mangler eller feiler. Appen kjører videre med standardutseende — bevisst «loud on failure» |
| HAZOP-siden viser System-analyse ved første klikk | en side importerte fra en annen side. Sidefiler er skript; import kjører dem. **Importer fra `utils/discovery.py`, aldri fra en sidefil** |
| `KeyError: 'url_pathname'` ved sidelenking | `st.page_link` med filnavn under `st.navigation`. Bruk `PAGES["key"]` fra `nav_pages.py`, eller knapp + `st.switch_page` som i `hjem.py` |
| NeqSim-kall feiler / JVM starter ikke | Java 8+ mangler. Installer JRE, eller sett `HULDRA_NO_NEQSIM=1` for å hoppe over |
| Vision-siden gir 429 / kvotefeil | gratis tier er brukt opp. Cachen gjør kjøringen **gjenopptakbar** — kjør igjen senere, kun ucachede tegninger koster kvote |
| Vision returnerer det samme gamle svaret | diskcachen treffer. Sett `HULDRA_VISION_FRESH=1` for å tvinge nytt kall |
| Vision-reserven utløses aldri | den trigges kun på tegninger med < 3 tekst-tags, og kun med `HULDRA_VISION=1` |
| ⚙️/🧩-sidene stopper med feilmelding | Model Broker-konfigurasjonen mangler (§5.5). Resten av appen er upåvirket |
| NeqSim-/DEXPI-sider finner ingen data | `data/processed/*.csv` er ikke bygget. Kjør `python src/analysis/parse_dexpi_data.py` |
| `extract_region_geometry()` fant ingenting | kjør `python src/scripts/geometri_diagnose.py <pdf> <detections.json>` — den dumper hva `pdfplumber` faktisk ser, i seks varianter |
| Tallene i appen avviker fra `Results.md` | sjekk hvilken rapportmappe som leses (`reports/` vs `reports_vision/` vs `reports_unified/`) — de er ulike kjøringer, ikke uenige tall |

---

## 21. Utviklingskonvensjoner

Fem regler koden faktisk følger, og hvorfor:

1. **Sider importerer aldri fra sider.** En Streamlit-sidefil er et skript;
   `import system_analysis` kjører hele siden. Delt oppdagelseslogikk ligger i
   `src/utils/discovery.py`.
2. **Sider registreres i `nav_pages.py`, ikke i en `pages/`-mappe.**
   `nav_pages.PAGES` er single source of truth, slik at både `app.py` og
   enhver side kan lenke trygt til den *samme* `st.Page`-instansen.
3. **`st.set_page_config` finnes kun i `app.py`.** Kravet følger av
   `st.navigation`.
4. **Én kodevei per påstand.** App, batch-pipeline og HTML-dashboard importerer
   samme moduler. Hvis et tall skal endres, endres det ett sted.
5. **Feil skal være synlige.** Manglende designsystem → rød banner. Ukjent
   klausulproveniens → exception. Uverifisert AI-tag → 🟠, ikke skjult.
   Utilgjengelig NeqSim → klar melding, ikke krasj.

Nye analyser legges i `src/analysis/` som en modul med `if __name__ == "__main__"`
(CLI-tvilling), og eksponeres deretter av en tynn sidefil. Nesten alle 40+
analysemoduler følger dette mønsteret — se listen i §7.2.

---

## 22. Kravsporing mot oppgavens leveranser

| Leveranse (oppgaveteksten) | Hvor |
|---|---|
| Repo med README, oppsett, eksempel-arbeidsflyt | denne filen (§5, §7) |
| ≥ 2 fungerende AI-demonstrasjoner | 21 app-sider, hvorav 8 med AI-lag (§6) |
| Rapport med funn, begrensninger, verktøy, pilotkandidater | egen rapport (leveres separat) + `Results.md`, `PID_TO_STRUCTURE.md` |
| PDF vs strukturert format-sammenligning | `Results.md`, 🆚- og ⚖️-sidene, §2.3, §12 |
| Verktøy-/lisensanbefaling | §17 + rapportens kap. 3.4 |
| Presentasjon/demo for stakeholders | appen + landingssidens tre stier + selvstendig HTML-eksport fra 🆚-siden og `src/dashboard.py` |
| Gjenbrukbare prompts/agenter/skills | §16 |
| Dashboard/grafvisualisering med topologi, kompleksitet, flagg | 🏠/📄/🧭/🏭-sidene (KPI-er, mest koblede komponenter, kvalitetsflagg) + 📊 compliance-dashboardet |
| Minimumskrav for maskinlesbare leveranser | rapporten, empirisk begrunnet: recall-tak (§2.3), utagget mellomelement-topologi (§12), tag-konvensjonsvariasjon (§9.2), utagget utstyr i HAZOP-seksjoner (§19) |
| Kobling til simulerings-/beregningsverktøy | 🧪 NeqSim-siden, `analysis/neqsim_system_report.py`, `analysis/time_to_trip.py` |
| Kobling til sensor-/alarmdata for rotårsak i drift | `analysis/alarm_bridge.py` (navnenormalisering — der ekte integrasjoner ryker), 🎛️-siden, `data/demo_incident/` |
| Pilotforslag | §23 |

---

## 23. Videre arbeid og pilotkandidater

### Hovedpilotkandidat: kontrollrom-motoren mot en ekte alarmfeed

`analysis/control_room.py` er **datakilde-agnostisk**. Den tar alarmer + graf
og gir en strukturell brief per kandidatrot. Bytt scenariegeneratoren med en
alarmfeed fra SAS/IMS, så er samme brief operativ støtte. Broen som mangler er
allerede skrevet og er den delen som faktisk ryker i ekte integrasjoner:
`analysis/alarm_bridge.py` normaliserer et alarmpunktnavn (`27PT4805`,
`27-PT-4805`, `HO27_PT_4805`) til tegningstagget. Rotårsak-motoren er målt til
94–98 % hit #1 under realistisk alarmtap.

### Uttrekk

- Angrip de **70 text-present-bommene** (de tette tegningene HO27-002 m.fl.)
  hvis mer tekst-recall er ønskelig — med presisjon som vaktpost. Alt måles mot
  fasiten før det beholdes.
- Utvid valideringen til flere tegninger etter hvert som DEXPI-filer blir
  tilgjengelige.
- **Flislegging** av store ark for vision-kanalen: HO13 gir null selv ved
  300 dpi fordi flaskehalsen er innholdsmengde per bilde, ikke skarphet.
- **Symbolgjenkjenning som tredje uttrekskanal** mot de 60 % symbol-only-bommene
  — tekst + vision + symboler, alle målt mot samme fasit.

### Struktur

- **Leader-line-følging** for tagget-ventil → symbol-assosiasjon.
  Nærmeste-nabo-forankring er utilstrekkelig (målt: 220–370 px til nærmeste
  deteksjon, og den er som regel en *annen* ventil).
- Linjekryssinger uten knutepunktprikk slår sammen to løp; i dag flagget som
  `junction`, ikke løst.
- Flytretning gjenvinnes ikke fra piksler — koblingene er urettede.

### Måling

- **Fyll ut ett C&E-ark for hånd.** Det er en liten jobb, og det er det som
  gjør en målt feilrate for C&E-uttrekket mulig — på linje med resten av
  prosjektet. `ce_vision.compare_to_manual()` er måleapparatet og venter.

---

## Lisens og kreditering

Kildedata: Huldra åpne data fra Equinor, under lisensen i
`data/Equinor open data sharing license - Huldra.pdf`.
DEXPI-filene er produsert av Semantum Model Broker og var levert som del av
datasettet.

Prosjektet er utført som sommerstudentprosjekt av **Lisa Bruun Paulsen** og
**Torstein K. W. Thomassen**.
