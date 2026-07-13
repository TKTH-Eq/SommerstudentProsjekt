# SommerstudentProsjekt — automatisk tag-uttrekk fra Huldra-tegninger

Prosjekt for Lisa og Torstein. Basert på åpne data fra Huldra (avviklet
gassfelt, Equinor).

Eldre P&ID- og SCD-tegninger finnes stort sett bare som PDF — en bunke A0-ark
som er ugjennomtrengelig for søk og analyse. Dette prosjektet trekker ut
utstyrs- og instrument-tags automatisk fra tegningene, kobler dem sammen på
tvers av dokumenter, og bygger et strukturert, søkbart kunnskapslag oppå
dokumentbunken: hvilke tags finnes, hvor de kommer fra, hvordan de henger
sammen, og hvor P&ID og SCD er uenige.

Uttrekket er **validert mot en uavhengig fasit** (Semantum DEXPI XML): målt til
presisjon 87 %, recall 55 % på de tegningene som har fasit. Se
[`RESULTS.md`](RESULTS.md) for metode, tall og begrensninger.

> Uttrekket er tilnærmet — et førsteutkast for ingeniørgjennomgang, ikke en
> autoritativ kilde.

## Hva prosjektet gjør

- **Trekker ut tags** fra P&ID- og SCD-PDF-er via tekstlaget, med OCR-reserve
  (Google Vision) for tegninger der innholdet er grafikk fremfor tekst.
- **Avstemmer P&ID mot SCD** per system: felles tags, kun-P&ID (mekanikk),
  kun-SCD (styringslogikk) og reelle avvik å granske.
- **Bygger en avhengighetsgraf** (input → logikk → output) og et failure/
  root-cause-lag for å svare på «hva påvirker en endring her» og «hvor kan et
  symptom komme fra».
- **Validerer uttrekket** mot DEXPI-XML og rapporterer presisjon/recall/F1 pluss
  hver enkelt uenighet.
- **Presenterer alt** i en Streamlit-app med en analyse-side per system og en
  tag-oversikt på tvers av systemer.

## Kom i gang

Krever Python 3.12+. Prosjektet bruker [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                         # installer avhengigheter fra uv.lock
```

Legg tegningene under `data/raw/` (se mappestrukturen under). Start så appen:

```bash
streamlit run src/app.py
```

### Valgfritt: OCR-reserve (Google Vision)

Bare nødvendig for skannede / bilde-baserte tegninger. Krever poppler eller
`pypdfium2` for rasterisering, pakken `google-cloud-vision`, og Google-
legitimasjon:

```bash
pip install google-cloud-vision
set GOOGLE_APPLICATION_CREDENTIALS=C:\sti\til\service-account.json
set HULDRA_VISION=1             # skru på reserven (av som standard)
```

OCR utløses automatisk kun på tag-fattige sider, så vanlige kjøringer gjør ingen
API-kall.

## Bruk

### Validering mot fasit

```bash
# mål uttrekket mot DEXPI-fasiten
python src/validate_against_dexpi.py --raw data/raw --out reports

# bryt ned hvor recall tapes (per klasse, per tegning, null-tegninger)
python src/analyze_validation_diffs.py --out reports
```

Utdata i `reports/`: `validation_report.csv` (presisjon/recall/F1 per tegning +
TOTAL), `validation_diffs.csv` (hver MISSED/EXTRA-tag), og
`validation_diff_summary.csv` (recall-tap per klasse og tegning).

## Mappestruktur

```
data/raw/
  P&ID/                        P&ID-tegninger (PDF)
  SCD/                         SCD-tegninger (PDF)
  SCD Legend/                  forklaring av SCD-logikkblokker (referanse)
  Symbols/                     symbolbibliotek (referanse)
  Semantum Huldra P&IDS/       DEXPI XML — fasit for validering
  processed/                   avledede data

src/
  app.py                       Streamlit-inngang (st.navigation)
  system_analysis.py           analyse-side per system
  tag_oversikt.py              tag-oversikt på tvers av systemer
  config.py                    stier, tag-typer, farger, sikkerhetstyper
  extraction/
    pdf_parser.py              tekst / posisjonerte ord / render + OCR-reserve
    tag_extractor.py           tag-uttrekk (to pass) + typede objekter
  analysis/                    graf, konsistens, KPI, failure/root-cause, sim
  ai/                          operatør-brief
  models/                      EngineeringObject
  validate_against_dexpi.py    validering mot DEXPI-fasit
  analyze_validation_diffs.py  bryter ned recall-tapet

reports/                       genererte CSV-er, grafer, kvalitetsrapport
notebooks/                     utforskende analyse
tests/                         tester
```

> Modul-oversikten under `analysis/` og `ai/` er beskrevet ut fra hvordan de
> brukes i appen — juster om noe har flyttet seg eller heter annerledes.

## Nøkkeltall

| | Presisjon | Recall | F1 |
|---|---:|---:|---:|
| Uttrekk målt mot DEXPI (16 tegninger) | 87 % | 55 % | 67 % |

Recall er begrenset oppad av kildematerialet: der tags er tegnet som symboler
fremfor tekst, kan tekstuttrekk aldri fange dem. Full oppdeling av det
gjenstående gapet — reell uttreksfeil vs. metodens tekstlags-tak — står i
[`RESULTS.md`](RESULTS.md).

## Status

Fungerende pipeline med validert nøyaktighet. Videre arbeid: OCR ende-til-ende
på bilde-tegninger, mer tekst-recall på tette tegninger, og bredere
fasit-dekning etter hvert som flere DEXPI-filer blir tilgjengelige.