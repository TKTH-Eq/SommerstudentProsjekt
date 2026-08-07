# gatevalve-ai

`gatevalve-ai` is a computer-vision pipeline for locating and classifying P&ID symbols in engineering drawings.

The project started as a narrow gate-valve detector and evolved into a hybrid pipeline that combines deterministic PDF/image preprocessing, candidate generation, a small convolutional neural network (CNN), class-specific binary verifiers, and drawing-level evaluation against DEXPI-derived ground truth.

The intended use is **human-in-the-loop decision support**. The model proposes symbol locations and classes; it is not intended to approve or populate engineering data without review.

---

## Why this project exists

When a drawing PDF is converted to structured data, tools such as Semantum Model Broker may require a user to identify or configure the symbol variants used on the drawing. Looking up symbols in legends and manually checking many occurrences is repetitive work.

`gatevalve-ai` explores whether machine learning can reduce that work by:

- locating likely symbols on a P&ID;
- classifying the proposed symbol;
- exposing confidence and an annotated proof image;
- providing machine-readable detections with original drawing coordinates; and
- supplying detections that can be used by the wider Sommerprosjekt application when surveying Model Broker symbol variants.

The CNN **does not generate vector geometry**. It works on rasterized image crops. In the wider application, a detection's class and bounding box can be used as a region selector, after which vector geometry is read from the original PDF separately.

---

## Current pipeline

The current implementation is a hybrid of conventional computer vision and learned models:

```text
P&ID PDF / image
      |
      v
Render PDF and mask text
      |
      v
Mask margins and title block
      |
      v
Candidate generation
   /             \
template       connected-
matching       component proposals
   \             /
      v
Candidate crop
      |
      v
Canonicalization
(remove long pipes, isolate symbol,
rotate, center, resize to 64x64)
      |
      v
10-class CNN
      |
      v
Class-specific binary verifier
(where available)
      |
      v
Confidence tier + sanity filtering
      |
      v
Deduplication
      |
      v
verdict.json + proof.png + detections.json
```

Candidate generation and preprocessing are deterministic. The learned parts are the main CNN and the class-specific binary verifiers.

---

## Supported classes

The current main CNN contains ten classes:

| CNN class | Meaning |
|---|---|
| `background` | non-symbol / negative candidate |
| `ball_closed` | closed ball valve |
| `ball_open` | open ball valve |
| `butterfly_valve` | butterfly valve |
| `check_valve` | check valve |
| `gate_closed` | closed gate valve |
| `gate_open` | open gate valve |
| `globe_valve` | globe valve |
| `other_valve` | grouped needle / plug / angle-valve family |
| `reducer` | pipe reducer |

For second-stage verification, open and closed states are merged into their physical class:

- `ball_open` + `ball_closed` -> `ball_valve`
- `gate_open` + `gate_closed` -> `gate_valve`

The verifier answers **"is this really this physical class?"**. The main CNN remains responsible for the open/closed state.

---

## Repository status

The repository contains code, candidate templates and selected evaluation outputs.

The following important runtime/training artefacts are **generated locally and are not currently tracked in Git**:

```text
model_cnn.pt
verifiers.pt
dataset/
synth/
```

This means a fresh clone must either:

1. receive compatible trained model files separately; or
2. build the dataset and retrain the models using the steps below.

The engineering drawings and DEXPI/XML source data are also expected to be supplied outside this repository.

---

# Installation

## Python

The project was developed and evaluated with Python 3 and CPU-based PyTorch on Windows.

A virtual environment is recommended:

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

## Core dependencies

The project environment used the following relevant package versions:

```text
numpy==2.5.0
opencv-python==5.0.0.93
pypdfium2==5.11.0
pdfplumber==0.11.10
joblib==1.5.3
scikit-image==0.26.0
scikit-learn==1.9.0
torch==2.13.0+cpu
```

A practical installation is:

```bat
pip install numpy==2.5.0 opencv-python==5.0.0.93 ^
    pypdfium2==5.11.0 pdfplumber==0.11.10 ^
    joblib==1.5.3 scikit-image==0.26.0 scikit-learn==1.9.0
```

For a CPU-only PyTorch installation:

```bat
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

The full Sommerprosjekt Python environment contains additional packages that are not required by `gatevalve-ai`; therefore the complete `pip freeze` is intentionally not reproduced here.

---

# Quick start

## Classify one drawing

If `model_cnn.pt` and `verifiers.pt` are available in the repository directory:

```bat
py classify_drawing.py "C:\path\to\drawing.PDF" --dpi 200 --model model_cnn.pt
```

`classify_drawing.py` automatically loads `verifiers.pt` when the file is present.

To also write the individual detections used by downstream analysis:

```bat
py classify_drawing.py "C:\path\to\drawing.PDF" ^
    --dpi 200 ^
    --model model_cnn.pt ^
    --dump-detections
```

Useful options:

```text
--only-gates              report only open/closed gate valves
--dump-detections         write every accepted detection to JSON
--dump-candidates         write all classified candidates for debugging
--no-cand-components      disable connected-component candidate proposals
--cand-mirror             also sweep mirrored candidate templates
--keep-text               do not mask text from the PDF text layer
--full-sheet              search margins/title block as well
--mode recall             default operating mode
--mode precision          stricter mode; includes the strong gate geometry check
--no-non-gate-verifier    disable second-stage verifiers
```

> Note: despite the historical flag name `--no-non-gate-verifier`, the current verifier set also contains a `gate_valve` verifier.

---

# Outputs

For a drawing named `example.PDF`, inference writes files in `results/` by default.

## `example_verdict.json`

Summary per class, including whether the class is present, number of confident/possible detections and best CNN confidence.

## `example_proof.png`

Annotated drawing showing accepted detections. This is the main visual evidence for review.

## `example_detections.json`

Created with `--dump-detections`.

Each detection contains the predicted class, CNN confidence, confidence tier and original drawing bounding box:

```json
{
  "cls": "check_valve",
  "conf": 0.91,
  "tier": "sikker",
  "bbox_orig": [1234, 567, 1280, 610]
}
```

When a binary verifier was used, verifier confidence and threshold are also included.

## `example_candidates.json`

Created with `--dump-candidates`.

This diagnostic file includes candidates that were later classified as background or rejected.

---

# How the model works

## 1. PDF rendering and masking

For PDF input, `classify_drawing.py` renders the first page at the requested DPI using `pypdfium2`.

The PDF text layer is read separately with `pdfplumber`. Word boxes are painted white in the rendered image before candidate generation. This prevents letters and tag text from becoming valve candidates.

The drawing frame is then estimated from long horizontal and vertical lines. Margins, the title block and revision area are masked unless `--full-sheet` is used.

---

## 2. Candidate generation

The CNN does not scan every possible 64x64 window directly. Candidate regions are proposed first.

### Template matching

Clean candidate prototypes such as:

```text
gate_open.png
gate_closed.png
cand_ball.png
cand_ball_closed.png
cand_globe.png
cand_check.png
cand_check2.png
cand_butterfly.png
cand_reducer.png
```

are swept over multiple scales and 0/90-degree orientations. Optional mirrored templates can be enabled for direction-dependent symbols.

Local maxima are retained and non-maximum suppression removes strongly overlapping proposals.

### Connected-component proposals

Template matching is biased toward symbol styles similar to the stored prototypes. To recover styles that differ from those templates, connected-component proposals are enabled by default.

The code:

1. removes long horizontal and vertical lines;
2. finds the remaining connected ink components;
3. keeps components in a plausible symbol-size range; and
4. proposes a slightly padded square crop around each component.

The CNN and verifier stages decide whether those extra proposals are useful.

---

## 3. Canonicalization

Training and inference use the same `canonicalize()` function from `train_classifier.py`.

Each candidate is transformed to reduce nuisance variation before the CNN sees it:

- threshold to a binary image;
- normalize to white ink on black;
- remove long through-going horizontal and vertical lines;
- isolate central symbol components;
- rotate vertical symbols to a common horizontal orientation;
- crop to the remaining ink;
- scale and center the result in a fixed `64 x 64` image.

This allows the learned model to focus more on symbol geometry and less on absolute position, scale and orientation.

---

## 4. Main CNN

`train_cnn.py` defines a small four-convolution CNN:

```text
1 x 64 x 64
    |
Conv 1 -> 16 channels
BatchNorm + ReLU + MaxPool
    |
Conv 16 -> 32
BatchNorm + ReLU + MaxPool
    |
Conv 32 -> 64
BatchNorm + ReLU + MaxPool
    |
Conv 64 -> 64
BatchNorm + ReLU
    |
Adaptive average pooling
    |
Dropout
    |
Linear layer -> 10 class logits
```

The network is trained with class-weighted cross-entropy to reduce the effect of class imbalance.

Small random image shifts are used as training augmentation.

The best validation state is stored in:

```text
model_cnn.pt
```

together with:

- model weights;
- class names;
- canonical image size; and
- class-specific suggested confidence thresholds.

---

## 5. Confidence tiers

In the default `recall` mode, each accepted CNN prediction is placed in one of two user-facing tiers.

**Confident (`sikker`)**

The CNN confidence is at or above the class-specific threshold learned during training.

**Possible (`mulig`)**

The prediction is below the confident threshold but at least `0.55`.

Lower-confidence candidates are rejected.

The possible tier is intentionally a review checklist rather than an assertion.

---

## 6. Binary second-stage verifiers

The main CNN sometimes assigns high softmax confidence to difficult confusers. For example, a reducer may be classified as a ball valve.

`train_verifiers.py` therefore trains one binary CNN for each of these physical classes:

```text
ball_valve
globe_valve
check_valve
butterfly_valve
reducer
gate_valve
```

Each verifier reuses the same CNN architecture with two outputs:

```text
not this class
this class
```

The main model is not modified. The verifier is only called after the main CNN has proposed the corresponding class.

The trained verifier bundle is stored in:

```text
verifiers.pt
```

---

# Training data

The training strategy is:

```text
generate data
    ->
train main CNN
    ->
mine the main CNN's mistakes
    ->
train class-specific verifiers
    ->
run inference
    ->
evaluate on drawings never used during training
```

Two data sources are combined.

---

## Synthetic data

`make_synthetic.py` creates labelled 64x64 training examples from clean legend-derived symbol templates.

The synthetic generator adds realistic context and confusers, including:

- pipe lines through symbols;
- scale variation;
- 90-degree orientation changes;
- neighbouring strokes;
- arrows;
- circles and instrument-like shapes;
- slash/specification marks;
- nozzle/triangle decoys;
- fittings and non-valve symbols;
- blur;
- line-thickness variation;
- simulated low-DPI rasterization; and
- salt-and-pepper noise.

The label is known exactly because the generator placed the symbol itself.

Generate, for example, 1000 samples per class:

```bat
py make_synthetic.py --templates templates --n 1000 --out synth
```

Output:

```text
synth/
├── background/
├── ball_closed/
├── ball_open/
├── butterfly_valve/
├── check_valve/
├── gate_closed/
├── gate_open/
├── globe_valve/
├── other_valve/
└── reducer/
```

---

## Real DEXPI/XML-labelled data

`make_dataset.py` extracts real image crops using component class and position from the DEXPI/Model Broker XML output.

The XML therefore acts as the label source; individual symbol crops do not need to be manually annotated.

The batch wrapper matches XML files to drawings and processes all available pairs:

```bat
py make_dataset_batch.py ^
    --xml-dir "C:\path\to\xml" ^
    --drawings-dir "C:\path\to\drawings" ^
    --dpi 200 ^
    --out dataset
```

The resulting structure includes class folders and:

```text
dataset/labels.csv
```

`labels.csv` is the ground-truth register used by hard-negative mining and drawing-level evaluation.

Random background crops are also generated as negatives.

### Gate- and ball-valve state labels

The source XML identifies the physical valve class but does not provide the open/closed state used by the CNN.

For real `GateValve` crops, the current training pipeline derives a pseudo-state using symbol fill geometry.

For real `BallValve` crops, `train_cnn.py` uses erosion-based fill behaviour to pseudo-label `ball_open` and `ball_closed`, and writes:

```text
dataset/ball_state_pseudolabels.csv
```

These pseudo-labels should be inspected when the dataset changes.

The current dataset is strongly imbalanced for ball-valve state, so state-specific ball-valve performance should not be treated as fully validated.

---

# Training the main CNN

After generating `synth/` and `dataset/`:

```bat
py train_cnn.py --real dataset --epochs 15
```

Output:

```text
model_cnn.pt
```

The training pipeline:

1. loads synthetic and real crops;
2. canonicalizes every image;
3. reserves synthetic validation data;
4. holds complete real drawings out of training;
5. oversamples under-represented real classes;
6. applies class-weighted cross-entropy;
7. trains the CNN;
8. keeps the best validation state; and
9. derives class-specific confidence thresholds from correct validation predictions.

For an explicit drawing holdout:

```bat
py train_cnn.py --real dataset ^
    --holdout-list "25VHO64PU00101,25VHO71PW00101,25WHO71PW00101" ^
    --epochs 15
```

---

# Hard-negative mining

Random background is not enough: the verifier should learn from the exact structures the main model actually confuses with a target class.

`mine_hard_negatives.py`:

1. runs the newly trained CNN on non-holdout drawings;
2. disables existing verifiers during mining;
3. compares detections with `dataset/labels.csv`;
4. finds detections for which no same-class ground-truth component is nearby; and
5. stores the crop only in the hard-negative bucket for the class that made the mistake.

Example:

```text
main CNN predicts: ball_closed
ground truth: no BallValve nearby
result: negative example for ball_valve verifier
```

It is **not** globally relabelled as background, because it may actually be a reducer, check valve or another valid class.

Run:

```bat
py mine_hard_negatives.py ^
    --drawings-dir "C:\path\to\drawings" ^
    --model model_cnn.pt ^
    --dpi 200
```

Output:

```text
dataset/HardNegativeByClass/
├── ball_valve/
├── butterfly_valve/
├── check_valve/
├── gate_valve/
├── globe_valve/
└── reducer/
```

For cross-validation, holdout drawings must be excluded:

```bat
py mine_hard_negatives.py ^
    --drawings-dir "C:\path\to\drawings" ^
    --model model_cnn.pt ^
    --dpi 200 ^
    --exclude "DRAWING_A,DRAWING_B,DRAWING_C"
```

---

# Training the binary verifiers

Run:

```bat
py train_verifiers.py ^
    --real dataset ^
    --synth synth ^
    --epochs 10 ^
    --max-per-side 4000 ^
    --target-precision 0.95
```

Output:

```text
verifiers.pt
```

For each physical class, the script:

- collects synthetic and real positives;
- treats all other relevant symbol types as negatives;
- upweights known confusers such as `PipeReducer` and `FlangedConnection`;
- adds class-specific hard negatives with high sampling weight;
- splits unique source files before oversampling, preventing the same crop from appearing in both training and validation;
- trains a binary CNN; and
- selects an operating threshold that targets the requested precision while maximizing recall.

The standalone script defaults to `--target-precision 0.98`. The current cross-validation driver deliberately uses `0.95`.

---

# Honest evaluation

Two different evaluation questions are reported.

## Patch classification

This asks:

> If a labelled crop is already provided, can the CNN classify it correctly?

This tests the CNN itself under the shared canonicalization pipeline.

## Full drawing detection

This asks:

> Can the complete system find and classify the symbols on a P&ID that was not used during training?

This is the more relevant application-level test because it includes candidate generation, false candidates, CNN classification, verifiers, thresholds and filtering.

---

## `make_report.py`

`make_report.py` runs `classify_drawing.py` on drawings with DEXPI-derived ground truth and greedily matches detections to component centres.

A detection is a true positive when a same-class ground-truth point falls within the configured radius around the detection centre. Remaining detections become false positives and unmatched ground-truth components become false negatives.

It reports precision and recall for:

- confident detections only; and
- confident + possible detections.

Open/closed gate states are merged against the state-less XML `GateValve` class during drawing-level evaluation. Open/closed ball states are similarly merged against `BallValve`.

`PipeReducer` is also evaluated as the `reducer` detection class.

Run:

```bat
py make_report.py ^
    --drawings-dir "C:\path\to\drawings" ^
    --model model_cnn.pt ^
    --dpi 200
```

Output:

```text
results/evaluation.csv
```

---

# Three-fold drawing-level cross-validation

`run_folds.py` is the reproducible end-to-end evaluation driver.

For every fold it performs:

```text
train main CNN
    ->
mine hard negatives excluding holdout drawings
    ->
train binary verifiers excluding holdout drawings
    ->
evaluate only the holdout drawings
```

The default configuration uses three folds of three drawings each, giving nine unique drawings that are evaluated as unseen.

Run:

```bat
py run_folds.py ^
    --drawings-dir "C:\path\to\drawings"
```

The full CPU run is expensive because the complete training/mining/verifier cycle is repeated three times.

Useful faster diagnostic options:

```text
--skip-mining
--skip-verifiers
```

Fold artefacts are copied to:

```text
results/folds/
```

and the combined per-row evaluation is written to:

```text
results/evaluation_folds.csv
```

---

# Current measured performance

The latest full three-fold run is recorded in `folds_log2.txt`.

## Patch-level accuracy on unseen drawings

| Fold | Real holdout patches | Accuracy |
|---|---:|---:|
| 1 | 213 | 83.1% |
| 2 | 393 | 79.6% |
| 3 | 326 | 81.3% |
| **Aggregate** | **932** | **81.0% (755/932)** |

Synthetic held-out validation accuracy was approximately 81% in all three folds.

## Full drawing-level detection

The table below aggregates the nine holdout drawings. Every drawing contributes only from the fold in which it was excluded from training, hard-negative mining and verifier training.

| Class | Ground truth | Confident P | Confident R | Confident + possible P | Confident + possible R |
|---|---:|---:|---:|---:|---:|
| Ball valve | 46 | 83% | 41% | 75% | 52% |
| Butterfly valve | 18 | 100% | 11% | 100% | 17% |
| Check valve | 36 | 44% | 78% | 42% | 78% |
| Gate valve | 100 | 58% | 37% | 61% | 45% |
| Globe valve | 19 | 53% | 53% | 40% | 74% |
| Other valves | 32 | 21% | 22% | 19% | 44% |
| Reducer | 82 | 68% | 67% | 48% | 72% |

These results show why patch accuracy alone is insufficient.

Examples:

- butterfly-valve detections are highly precise but currently miss most true symbols;
- check-valve recall is comparatively high, but false positives remain common;
- ball-valve confident detections are relatively precise but conservative; and
- gate-valve detection loses substantial recall between crop classification and complete-drawing detection.

The current model is therefore best treated as a review assistant, not an autonomous extractor.

---

# Integration with the wider Sommerprosjekt application

The files in this repository perform raster-based symbol recognition.

The wider Sommerprosjekt application contains additional analysis code for **Reference Symbols**, **Symbol Variants** and Model Broker configuration generation. That code is not part of this repository.

The integration boundary is primarily:

```text
results/<drawing>_detections.json
```

Each accepted detection provides:

```text
symbol class
CNN confidence
bounding box in original rendered-image coordinates
```

The external analysis code can then use the detection bounding box as a **region selector** on the original PDF.

For vector PDFs, the wider application:

1. converts the pixel bounding box back to PDF coordinates;
2. reads line, curve and rectangle primitives from the original PDF;
3. extracts primitives belonging to the detected region;
4. translates them into symbol-centred coordinates;
5. groups repeated primitive compositions across drawings;
6. compares them with saved reference symbols and existing Model Broker patterns; and
7. allows a human to confirm a missing variant before a proposed configuration pattern is generated.

The CNN therefore identifies **what and where**. The PDF vector reader supplies the geometry.

Generated Model Broker variants remain human-review proposals; they are not automatically treated as approved patterns.

---

# Repository structure

A simplified view of the tracked repository:

```text
gatevalve-ai/
|
|-- README.md
|
|-- classify_drawing.py          # current full inference pipeline
|-- train_cnn.py                 # current 10-class main CNN
|-- mine_hard_negatives.py       # class-specific hard-negative mining
|-- train_verifiers.py           # binary second-stage CNNs
|-- make_report.py               # drawing-level TP/FP/FN evaluation
|-- run_folds.py                 # full three-fold evaluation driver
|
|-- make_synthetic.py            # synthetic training data
|-- make_dataset.py              # one XML + drawing -> real dataset
|-- make_dataset_batch.py        # batch dataset builder
|
|-- learn_from_legend.py         # learns clean gate prototypes from legend
|-- make_candidate_templates.py  # builds cleaned candidate prototypes
|-- line_labels.py               # line-label parsing support
|-- labels.json                  # legend/template support metadata
|
|-- train_classifier.py          # historical HOG+SVM model;
|                                # still supplies shared canonicalization
|-- check_drawing.py             # original deterministic gate-only detector
|-- probe_crops.py               # diagnostic utility
|-- make_confusion_matrix.py     # evaluation visualization utility
|-- split_synth_ball.py          # dataset utility
|
|-- gate_open.png
|-- gate_closed.png
|-- cand_ball.png
|-- cand_ball_closed.png
|-- cand_butterfly.png
|-- cand_check.png
|-- cand_check2.png
|-- cand_globe.png
|-- cand_reducer.png
|
|-- templates/
|   |-- VAL*.png
|   |-- FIT*.png
|   |-- LIN*.png
|   |-- library.json
|   `-- _library_overview.png
|
`-- results/
    |-- *_detections.json
    |-- *_lines.json
    |-- evaluation.csv
    |-- evaluation_folds.csv
    `-- folds/
```

Generated but untracked folders/files such as `dataset/`, `synth/`, `model_cnn.pt` and `verifiers.pt` are intentionally omitted from this tree.

---

# Important scripts

| Script | Role |
|---|---|
| `classify_drawing.py` | Current end-to-end symbol inference |
| `train_cnn.py` | Train the 10-class main CNN |
| `mine_hard_negatives.py` | Harvest class-specific false detections |
| `train_verifiers.py` | Train binary second-stage verifiers |
| `run_folds.py` | Retrain and evaluate the complete system across drawing holdouts |
| `make_report.py` | Match detections against DEXPI/XML ground truth |
| `make_synthetic.py` | Generate synthetic labelled symbol crops |
| `make_dataset.py` | Build real labelled crops from one XML/drawing pair |
| `make_dataset_batch.py` | Build a combined dataset from multiple pairs |
| `train_classifier.py` | Previous HOG+SVM approach and current shared preprocessing utilities |
| `check_drawing.py` | Original deterministic gate-valve approach |
| `learn_from_legend.py` | Derive clean gate prototypes from legend sheets |
| `make_candidate_templates.py` | Prepare candidate templates for inference |

---

# Legacy and historical code

The repository documents the path taken during development rather than containing only the final model.

## `check_drawing.py`

The original implementation used deterministic gate-valve geometry rules. It remains useful as project history and for understanding the initial gate-only approach.

## `train_classifier.py`

The first learned classifier used HOG features and an SVM.

The HOG+SVM model is no longer the primary classifier, but **do not remove `train_classifier.py` without refactoring**: the current CNN imports shared functions and mappings from it, including `canonicalize()`.

---

# Known limitations

## Limited real training data

The dataset contains substantially fewer real examples for some classes and states than for others. Synthetic data helps with volume but does not reproduce every drawing convention.

## Ball-valve state imbalance

The current real data contains far more closed than open ball-valve pseudo-labels. Open/closed ball state should therefore be treated cautiously.

## Candidate recall

The CNN can only classify a symbol if candidate generation proposes a region that contains it. Low drawing-level recall can therefore originate in candidate generation, classification, verification or filtering.

A useful future evaluation is to measure **candidate recall before the CNN**.

## Class-dependent operating points

Different symbol classes currently exhibit different precision/recall trade-offs. One global interpretation of "good enough" is therefore inappropriate.

## PDF assumptions

PDF inference uses the first page. Text masking depends on a usable embedded PDF text layer; scanned images do not provide the same text information.

## Human review is still required

The current drawing-level results do not support unreviewed engineering use. Detections and generated variant proposals should be treated as suggestions with visible evidence.

---

# Reproducible workflow

For a new dataset, the complete current workflow is:

```bat
REM 1. Build synthetic data
py make_synthetic.py --templates templates --n 1000 --out synth

REM 2. Build real DEXPI/XML-labelled data
py make_dataset_batch.py ^
    --xml-dir "C:\path\to\xml" ^
    --drawings-dir "C:\path\to\drawings" ^
    --dpi 200 ^
    --out dataset

REM 3. Train main CNN
py train_cnn.py --real dataset --epochs 15

REM 4. Mine its class-specific mistakes
py mine_hard_negatives.py ^
    --drawings-dir "C:\path\to\drawings" ^
    --model model_cnn.pt ^
    --dpi 200

REM 5. Train binary verifiers
py train_verifiers.py ^
    --real dataset ^
    --synth synth ^
    --epochs 10 ^
    --target-precision 0.95 ^
    --max-per-side 4000

REM 6. Run inference
py classify_drawing.py "C:\path\to\drawing.PDF" ^
    --dpi 200 ^
    --model model_cnn.pt ^
    --dump-detections

REM 7. Or reproduce the drawing-level cross-validation
py run_folds.py ^
    --drawings-dir "C:\path\to\drawings"
```

For a proper holdout experiment, do not manually run steps 3--5 on all drawings first and then report the same drawings as unseen. Use `run_folds.py`, which explicitly excludes the holdout drawings from training, hard-negative mining and verifier training in each fold.

---

# Development lessons

Several implementation decisions came directly from observed failure modes:

1. **Training-data quality matters more than volume alone.** Contaminated symbol templates produced poor learned features even when many synthetic examples were generated.

2. **Negative examples must represent real confusers.** Random background did not teach the model to reject reducers, flanges and other symbol-like structures.

3. **Patch accuracy is not drawing accuracy.** A classifier that performs well on isolated crops can still fail when applied to thousands of candidate regions on a dense P&ID.

4. **Keep the holdout boundary around whole drawings.** Random patch splits would leak drawing-specific scale, line style and raster characteristics into both training and evaluation.

5. **Separate proposal, classification and verification.** Candidate generation should favor recall; the CNN proposes a class; class-specific verifiers then reject difficult false positives.

6. **Expose uncertainty.** The confident/possible split is intentionally designed for human review rather than forcing every candidate into a hard yes/no output.

---

# Intended use

`gatevalve-ai` is an experimental engineering-assistance prototype developed as part of Sommerprosjekt.

It should be used to:

- propose symbol inventories;
- highlight likely symbol locations;
- support Model Broker configuration work;
- provide review checklists; and
- study how structured engineering data can improve AI-assisted workflows.

It should **not** be used as the sole basis for:

- approving a DEXPI model;
- modifying an engineering drawing;
- making process-safety decisions; or
- replacing engineering verification.

The design principle is:

> **AI proposes; structured data verifies; humans remain responsible.**
