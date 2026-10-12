# ML Experiments Log

Tracks all phishing-classifier experiments in `phishing_ml.ipynb`. Every experiment must keep the deployment contract unchanged: the exported artifact is always `phishing_detector.joblib` (project root) exposing `predict_proba([email_text])[0, 1]`.

Constraints: CPU only, single process, peak RAM kept modest (hashing vectorizers, capped feature spaces, no `n_jobs` process duplication).

## Experiment summary

| # | Name | Status | Val ROC-AUC | Test ROC-AUC | Test F1 | Deployed |
|---|------|--------|-------------|--------------|---------|----------|
| 0 | Baseline: word TF-IDF + LogReg | DONE | 0.9991 | 0.9989 | 0.9876 | YES (as of exp 0) |
| 1 | Soft-voting ensemble (word/char, 3 branches) | RUNNING | - | - | - | pending |
| 2 | Stacking (StackingClassifier, LogReg meta) | PLANNED | - | - | - | - |
| 3 | Hybrid text + structural (HistGradientBoosting branch) | PLANNED | - | - | - | - |

## Experiment 0: Baseline (word TF-IDF + Logistic Regression) - DONE

- Architecture: TfidfVectorizer (1-2 grams, min_df=2, 50k features, sublinear tf) -> LogisticRegression (liblinear, C=1.0).
- Validation: acc 0.9895, precision 0.9864, recall 0.9936, F1 0.9900, ROC-AUC 0.9991, PR-AUC 0.9991.
- Test: acc 0.9870, precision 0.9838, recall 0.9914, F1 0.9876, ROC-AUC 0.9989, PR-AUC 0.9989.
- FP 105 / FN 55 on test. Reproduced identically on local run (SEED 42) after Colab conversion.
- Notes: strong, fast, well-calibrated for a linear model. Ceiling limited by near-duplicate leakage between splits (Enron/Nazario style corpora) and genuinely ambiguous emails.

## Experiment 1: Soft-voting ensemble (3 branches) - RUNNING

Design (RAM-bounded):

1. `word_lr` - word TF-IDF (1-2 grams, 50k) -> LogReg liblinear (identical to baseline).
2. `char_nb` - HashingVectorizer (char_wb 3-4 grams, 2^18 buckets, float32) -> TfidfTransformer -> MultinomialNB.
3. `char_svc` - same hashed features -> CalibratedClassifierCV(LinearSVC, cv=3, sigmoid).

- HashingVectorizer is used specifically to avoid the vocabulary-dictionary RAM spike of char n-gram TfidfVectorizer; float32 CSR keeps matrices compact. Voting is soft; weights tuned on validation over a small preset grid; no extra training cost for the weight search.
- Deployment policy: replaces the baseline artifact only if ROC-AUC improves on BOTH validation and test.

Results: (pending run)

## Experiment 2: Stacking - PLANNED

StackingClassifier over the same three branches with LogisticRegression meta-learner, cv=5, stack_method='predict_proba'. Triggers only if exp 1 gain is insufficient. Cost ~5x single fit; watch near-duplicate leakage across folds.

## Experiment 3: Hybrid text + structural - PLANNED

Add engineered structural features (link count, digit/uppercase ratios, length stats) feeding HistGradientBoostingClassifier; stack with text branches. Addresses the error analysis (FPs from legitimate newsletters with link-heavy layouts, FNs from newsletters/list mail).

## Decision policy

- Replace deployed artifact only when the challenger improves test ROC-AUC and PR-AUC without degrading validation metrics.
- Calibration quality (Brier score) must be checked before deployment since the agentic pipeline weights the ML score at 0.45 in a 0.70-threshold fused verdict.
