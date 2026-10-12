# ML Experiments Log

Tracks all phishing-classifier experiments in `phishing_ml.ipynb`. Every experiment must keep the deployment contract unchanged: the exported artifact is always `phishing_detector.joblib` (project root) exposing `predict_proba([email_text])[0, 1]`.

Constraints: CPU only, single process, peak RAM kept modest (hashing vectorizers, capped feature spaces, no `n_jobs` process duplication).

## Experiment summary

| # | Name | Status | Val ROC-AUC | Test ROC-AUC | Test F1 | Size (MB) | Deployed |
|---|------|--------|-------------|--------------|---------|-----------|----------|
| 0 | Baseline: word TF-IDF + LogReg | DONE | 0.9991 | 0.9989 | 0.9876 | 2.32 | superseded |
| 1 | Soft-voting ensemble (3 branches) | DONE | 0.9993 | **0.9993** | 0.9905 | 18.33 | **YES (current)** |
| 2 | Chi2 feature selection (k=30k) + LogReg | DONE | 0.9988 | 0.9986 | 0.9848 | 2.93 | NO |
| 3 | Dataset v2 (Email4S) re-run of pipeline | DONE | 0.9993 | 0.9985 | - | - | NO (below incumbent) |
| 4 | Dataset v3 (per-source raw CSVs) + ensemble | DONE | 0.9995 | **0.9997** | 0.9940 | ~20 | **YES (current)** |
| 5 | Stacking (StackingClassifier, LogReg meta) | PLANNED | - | - | - | - | - |
| 6 | Hybrid text + structural (HistGradientBoosting branch) | PLANNED | - | - | - | - | - |

## Experiment 0: Baseline (word TF-IDF + Logistic Regression) - DONE

- Architecture: TfidfVectorizer (1-2 grams, min_df=2, 50k features, sublinear tf) -> LogisticRegression (liblinear, C=1.0).
- Validation: acc 0.9895, precision 0.9864, recall 0.9936, F1 0.9900, ROC-AUC 0.9991, PR-AUC 0.9991.
- Test: acc 0.9870, precision 0.9838, recall 0.9914, F1 0.9876, ROC-AUC 0.9989, PR-AUC 0.9989.
- FP 105 / FN 55 on test. Reproduced identically on local run (SEED 42) after Colab conversion.
- Notes: strong, fast, well-calibrated for a linear model. Ceiling limited by near-duplicate leakage between splits and genuinely ambiguous emails.

## Experiment 1: Soft-voting ensemble (3 branches) - DONE, DEPLOYED

Design (RAM-bounded):

1. `word_lr` - word TF-IDF (1-2 grams, 50k) -> LogReg liblinear (identical to baseline).
2. `char_nb` - HashingVectorizer (char_wb 3-4 grams, 2^18 buckets, float32) -> TfidfTransformer -> MultinomialNB.
3. `char_svc` - same hashed features -> CalibratedClassifierCV(LinearSVC, cv=3, sigmoid).

- HashingVectorizer avoids the vocabulary-dictionary RAM spike of char n-gram TfidfVectorizer; float32 CSR keeps matrices compact. Voting is soft; weights tuned on validation (weights apply at predict time, zero extra training cost).
- Weight search on validation: best (2, 1, 2) val ROC-AUC 0.9994; (3,1,2) and (1,1,2) tie at 0.9994 on validation.
- Validation: acc 0.9907, F1 0.9911, ROC-AUC 0.9993, PR-AUC 0.9993.
- Test: acc 0.9901, precision 0.9888, recall 0.9922, F1 0.9905, ROC-AUC 0.9993, PR-AUC 0.9994.
- Deployed (improves baseline test ROC-AUC 0.9989 -> 0.9993). Artifact 18.33 MB (vs 2.32 MB baseline; mostly char-branch estimators). Contract `predict_proba([text])[0,1]` unchanged; `model_metadata.json` updated.

## Experiment 2: Chi-squared feature selection - DONE, NOT DEPLOYED

- Pipeline: baseline TF-IDF (50k) -> SelectKBest(chi2, k=30000) -> LogReg.
- Validation: ROC-AUC 0.9988, PR-AUC 0.9988. Test: ROC-AUC 0.9986, PR-AUC 0.9986, F1 0.9848.
- Verdict: slightly worse than the plain baseline (0.9986 vs 0.9989 test ROC-AUC), so chi2 pruning removes useful signal here. Kept as analysis-only; no artifact change.
- Top chi2 features overlap heavily with LogReg coefficient leaders ('enron', 'wrote', 'replica', 'watches', 'cnncom', 'money').

## EDA findings (structural features)

- The dataset text is pre-normalized (lowercased, punctuation stripped): `upper_ratio` and `exclam_count` are all-zero (NaN correlation). Capitalization/punctuation-based phishing heuristics cannot be learned from this corpus.
- Weak correlations with target: digit_ratio +0.048, url_count +0.034, avg_word_length +0.075 (phishing slightly shorter, more URL/digit-heavy), word_count -0.075. Structural signals exist but are weak for this corpus; text n-grams remain the dominant signal.

## Experiment 3: Dataset v2 (HF Email4S) re-run - DONE, NOT DEPLOYED

- Switched dataset version to v2_email4s (HF `zefang-liu/phishing-email-dataset`, ~18.6k raw-text emails, mixed case/punctuation; literal `null`/`empty` rows and duplicates dropped).
- Same pipeline as exp 0-2 re-run on v2: baseline val/test ROC-AUC 0.9981/0.9976; ensemble (now with URL-count feature via FeatureUnion) 0.9993/0.9985.
- Chi2 FS on v2: test ROC-AUC 0.9974 (below baseline, consistent with exp 2's conclusion).
- Deployment guard worked as designed: incumbent v1 ensemble artifact (test ROC-AUC 0.9993) retained since 0.9985 < 0.9993.
- Interpretation: the gap is dataset-driven (18.6k vs 82k rows, and the v1 dataset mixes more corpora), not model-driven. The architecture transfer (ensemble gain: +0.0009 test ROC-AUC over baseline on same data) confirms the ensemble design generalizes across datasets.
- RAM note: the v2 corpus contains a ~195k-char outlier email; the URL-count transformer was fixed to stream strings with object dtype after `astype(str)` briefly attempted a ~9GB fixed-width unicode allocation.

## Experiment 4: Dataset v3 (per-source raw CSVs) - DONE, DEPLOYED

- Rebuilt the training data from the locally cached per-source CSVs (CEAS_08, Enron, Ling, Nazario, Nigerian_Fraud, SpamAssasin; ~82k emails), using `subject + "\n" + body` raw text (original case/punctuation) instead of the normalized `phishing_email.csv`.
- Same pipeline as exp 1 (3-branch soft-voting ensemble + URL-count feature), weight search again picked (2, 1, 2).
- Baseline (word TF-IDF + LogReg) on v3: val ROC-AUC 0.9993, test 0.9994.
- Ensemble on v3: val ROC-AUC 0.9995, test ROC-AUC 0.9997, PR-AUC 0.9997, accuracy 0.9938, F1 0.9940.
- Deployment guard passed (0.9997 >= incumbent 0.9993) so the v3 ensemble is now the deployed `phishing_detector.joblib`; `model_metadata.json` updated with dataset version and metrics.
- Gain drivers vs v1: raw casing/punctuation signal, subject-line signal, larger effective information content per email.
- **Artifact fix (post-deploy):** the first v3 export pickled `url_count_feature` from the notebook kernel's `__main__`, which made `joblib.load` fail in any fresh process (the agent notebook would crash at model load). The function moved to the importable repo module `phishing_model_utils.py` and the model was retrained; identical deterministic pipeline, identical metrics (test ROC-AUC 0.9997), redeployed. `phishing_model_utils.py` must remain importable wherever the artifact is loaded (run from the project root).
- Post-swap fixture sanity: the ensemble is more conservative on the agent fixtures than the old model (phish 0.8351 vs 0.9803, legit 0.1797 vs 0.1603) but offline metrics are strictly better; verdicts/margins unaffected. Agent v4 run recorded in `results.md`.

## Experiment 5: Stacking - PLANNED

StackingClassifier over the exp-1 branches with LogisticRegression meta-learner, cv=5, stack_method='predict_proba'. Triggers only if further gains are needed. Cost ~5x single fit; watch near-duplicate leakage across folds. Ensemble 18 MB is acceptable, but stacking adds CV cost.

## Experiment 6: Hybrid text + structural - PLANNED

Engineered structural features (link count, digit/uppercase ratios, length stats) feeding HistGradientBoostingClassifier, stacked with text branches. Caveat from EDA: this corpus has no capitalization/punctuation signal, so gains would come mostly from length/URL/digit features, which are only weakly correlated with the label. Low expected ROI on this dataset; revisit with a raw (non-normalized) corpus.

## Decision policy

- Replace deployed artifact only when the challenger improves test ROC-AUC and PR-AUC without degrading validation metrics.
- Calibration quality (Brier score) must be checked before deployment since the agentic pipeline weights the ML score at 0.45 in a 0.70-threshold fused verdict.
- Current deployment: Experiment 4 ensemble on dataset v3 (test ROC-AUC 0.9997, PR-AUC 0.9997). Remaining headroom to "perfect" is mostly label noise / genuinely ambiguous emails, not model capacity.
