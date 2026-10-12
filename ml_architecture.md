# ML Architecture — Phishing Email Classifier

## 1. Overview

The ML layer is a supervised text classifier trained offline in `phishing_ml.ipynb` and consumed by the agentic pipeline (`agentic_phishing.ipynb`) as one of three fused scores (weight 0.45). It is deliberately CPU-only, single-process, and RAM-bounded, and it hides behind a fixed deployment contract so the agent pipeline never changes when the model does.

```
                     raw email text (subject + body)
                                   |
                    +--------------+--------------+
                    |              |              |
              word TF-IDF    hashed char     hashed char
              (1-2 grams,    n-grams 3-4     n-grams 3-4
               50k feats)    (2^18 buckets)  (2^18 buckets)
                    |              |              |
              URL-count       URL-count       URL-count
               feature          feature          feature
                    |              |              |
               LogReg          MultinomialNB   CalibratedCV
              (liblinear)                      (LinearSVC,
                                               sigmoid, cv=3)
                    |              |              |
                    +-------- soft vote (2/1/2) --------+
                                   |
                    P(phishing) in [0, 1]  ->  phishing_detector.joblib
```

## 2. Deployment contract

| Item | Value |
|---|---|
| Artifact | `phishing_detector.joblib` (project root, ~20 MB, gitignored) |
| Interface | `model.predict_proba([email_text])[0, 1] -> float in [0, 1]` |
| Metadata | `model_metadata.json` (model name, dataset version, weights, test metrics) |
| Shared module | `phishing_model_utils.py` — the artifact pickles `url_count_feature` by reference, so this file must stay importable wherever the artifact is loaded (run from the project root) |
| Consumer | `agentic_phishing.ipynb` node `ml_predict`, fusion weight 0.45, threshold 0.70 |

The contract is the invariant: every experiment (baseline, ensembles, feature selection, dataset swaps) ships behind the same one-line interface. Swapping the model required zero agent-pipeline changes.

## 3. Feature branches

1. **word_lr** — word TF-IDF (lowercase, unicode accent strip, 1-2 grams, `min_df=2`, 50k features, sublinear tf) → LogisticRegression (liblinear, C=1.0). The original baseline; word-statistical signal.
2. **char_nb** — HashingVectorizer (`char_wb` analyzer, 3-4 grams, 2^18 buckets, float32, no norm) → TfidfTransformer (sublinear) → MultinomialNB. Character-level signal catches obfuscation (`c1ick`, split tokens, URL junk) that word tokens miss.
3. **char_svc** — same hashed char features → CalibratedClassifierCV(LinearSVC, cv=3, sigmoid). Margin-based separation, calibrated to probabilities so soft voting is valid.

Each branch additionally receives a **URL-count feature** (`https?://|www.` regex count, MaxAbs-scaled) through a `FeatureUnion`, matching the literature finding that URL features are the largest structural gain for phishing detection.

**Why hashing for the char branches:** char n-gram `TfidfVectorizer` would build a vocabulary dictionary in the millions of entries (RAM spike); `HashingVectorizer` is stateless with a fixed 2^18 bucket budget, and float32 keeps the CSR matrices compact. This is the main RAM guard of the architecture. The URL-count transformer additionally streams strings with object dtype (a ~195k-char outlier email once caused `astype(str)` to attempt a ~9 GB fixed-width allocation before the fix).

## 4. Data pipeline

- **Source:** Kaggle "Phishing Email Dataset" (Naser Abdullah Alam), fetched via `kagglehub`, cached under the user home directory.
- **`DATASET_VERSION` switch** in the notebook:
  - `v3_per_source` (**deployed**) — per-source CSVs (CEAS_08, Enron, Ling, Nazario, Nigerian_Fraud, SpamAssasin; ~82k rows), `subject + "\n" + body`, **raw** casing/punctuation, labels as int, deduplicated.
  - `v2_email4s` — HF Email4S (~18.6k raw-text rows); benchmarked, not deployed.
  - `v1_alam` — the original normalized `phishing_email.csv` (lowercased, punctuation-stripped); the exp 0-2 corpus.
- **Split:** 70/15/15 stratified, `SEED=42`; final refit on train+val before export.
- **EDA hooks:** structural-feature correlation heatmap (lengths, ratios, URL counts) per corpus; per-label text-length distribution plot.

## 5. Evaluation

Accuracy, precision, recall, F1, ROC-AUC, PR-AUC on validation (model/weight selection) and test (deployment decision); confusion matrices; threshold sweep; calibration-sensitive choice of PR-AUC alongside ROC-AUC because the agentic fusion consumes probabilities, not labels.

## 6. Deployment guard

Exports only when the challenger:
1. beats the same run's baseline on validation AND test ROC-AUC, and
2. meets or beats the **incumbent deployed artifact's** test ROC-AUC (hardcoded at export time).

This is what stopped the weaker v2 dataset run (0.9985) from replacing the v1 ensemble (0.9993), and allowed the v3 ensemble (0.9997) through.

## 7. Current deployment

3-branch soft-voting ensemble on v3 raw per-source data, weights (2, 1, 2):
test ROC-AUC **0.9997**, PR-AUC 0.9997, accuracy 0.9938, F1 0.9940 (vs baseline 0.9989/0.9989/0.9876 on the same data).

Full experiment history: `ml_results.md`. Dataset options and survey: `dataset_candidates.md`. ML research write-up: `ml_project_report.md`.