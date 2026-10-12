# An Ensemble Text-Classifier for Phishing Email Detection with a Deployment Guard and a Fixed Inference Contract

Department of Computer Science and Engineering, Manipal Academy of Higher Education, Bengaluru, India

---

**Abstract** — A single text classifier is a fragile anchor for a downstream agentic detection system: it must be cheap, stable, improvable offline, and swappable without touching its consumer. This paper presents the supervised machine-learning layer of an agentic phishing detection system: a three-branch soft-voting ensemble combining word-level TF-IDF with logistic regression, hashed character n-grams with multinomial Naive Bayes, and hashed character n-grams with a probability-calibrated linear SVM, each branch augmented with a URL-count feature. Branches were chosen to diversify the feature space under a strict CPU-only, single-process, RAM-bounded training budget; hashing bounds the character branch's memory, and a deployment guard gates every export on beating the incumbent artifact's held-out ROC-AUC. Trained on approximately 82,000 raw, unnormalized emails aggregated from six public corpora, the ensemble reaches a held-out ROC-AUC of 0.9997 and F1 of 0.9940, improving on a 0.9989 single-model baseline while preserving a one-line inference contract (`predict_proba` on a raw email string) that let the downstream fusion pipeline absorb the model swap without code changes. A logged experiment series covering dataset ablations, chi-square feature selection, weight tuning, and an artifact-serialization incident documents the engineering process.

**Index Terms** — phishing detection, text classification, ensemble learning, TF-IDF, character n-grams, soft voting, probability calibration, MLOps.

---

## I. INTRODUCTION

Phishing email detection is a well-studied classification problem where strong supervised baselines exist, but in a larger detection system the classifier plays a specific role: it is the deterministic, labeled-data-trained anchor whose score one downstream fusion weights at 0.45. That role imposes engineering constraints beyond raw accuracy: the model must train on commodity CPU hardware, infer in milliseconds, expose calibrated probabilities, and be replaceable by a better challenger without a coordinated code change.

This paper documents the ML layer of such a system. The contributions are:

1. **A feature-diverse soft-voting ensemble** (word TF-IDF + LogReg, hashed char n-grams + Naive Bayes, hashed char n-grams + calibrated LinearSVC, plus a URL-count feature on every branch) designed explicitly under CPU/RAM budget constraints, with hashing chosen to bound character-branch memory.
2. **A dataset-upgrade methodology**: rebuilding the training corpus from raw per-source CSVs (original casing and punctuation, subject included) instead of a pre-normalized single file, with a version switch and a benchmark against the incumbent before deployment.
3. **A deployment guard and fixed inference contract**: exports replace the shipped artifact only when the challenger beats the incumbent's held-out ROC-AUC, behind an unchanged `predict_proba([text])[0,1]` interface, so model iteration never touches the downstream agentic pipeline.
4. **A reproducible experiment log**: every model, dataset, and metric decision recorded with status and deployment outcome, including a serialization incident where a notebook-defined transformer prevented the artifact from loading in fresh processes.

The remainder is organized as follows. Section II situates the work. Section III details the architecture and training design. Section IV describes the experimental setup. Section V presents results and discussion. Section VI concludes.

## II. BACKGROUND AND RELATED WORK

**Text-based phishing detection.** Classical pipelines vectorize email text with TF-IDF or bag-of-words and train linear models; surveys of malicious-URL and phishing detection catalog this lineage [1]. Character n-grams complement word features because phishing text is adversarial at the sub-word level (obfuscations like `c1ick`, `fr ee`, and throwaway URL tokens), and hybrid word+char featurization is a common recommendation in spam-filtering practice [2].

**Ensembles for phishing detection.** Recent comparative work on email phishing corpora consistently identifies gradient-boosted trees and random forests as top performers on structured email features; a 2025 multi-source corpus study reports 98.34% F1 with XGBoost over text + URL features and finds URL features the largest structural gain, attachment features neutral-to-negative [3]. Stacked ensembles over heterogeneous base classifiers (SVM, LogReg, RF, XGB) with vectorization diversity report up to 99.41% F1 on a small phishing corpus [4]. Our system follows the same heterogeneity principle (linear word model + generative char model + margin-based char model, soft-voted) while remaining in the CPU-cheap scikit-learn regime.

**Corpora.** The public ecosystem spans raw corporate archives (Enron), curated phishing corpora (Nazario, Nigerian Fraud), and academic spam collections (Ling-Spam, SpamAssassin, CEAS'08, TREC) [3]. Studies repeatedly flag that pre-normalized corpora lose signal (casing, punctuation) and that near-duplicate leakage across sources inflates naive split metrics [5].

## III. METHODOLOGY

### A. Design Constraints

The classifier trains on a commodity CPU, single process, without GPU memory relief, and must not spike RAM on an 82k-row corpus containing outlier emails up to ~195k characters. It must expose calibrated probabilities (soft voting requires them; the downstream fusion consumes the probability, not the label), and it must export through a fixed contract: a single joblib artifact loaded as `predict_proba([email_text])[0, 1]`.

### B. Feature Branches

1. **word_lr**: word TF-IDF (lowercase, unicode accent stripping, 1-2 grams, `min_df=2`, 50,000 features, sublinear tf) → LogisticRegression (liblinear, C=1.0, `max_iter=1000`). The historical baseline branch.
2. **char_nb**: `HashingVectorizer` (`char_wb` analyzer, 3-4 grams, 2^18 buckets, `alternate_sign=False`, float32, norms deferred) → `TfidfTransformer` (sublinear) → MultinomialNB. Generative model over character evidence.
3. **char_svc**: the same hashed char features → `CalibratedClassifierCV(LinearSVC, cv=3, method="sigmoid")`, converting SVM margins into per-class probabilities.

Every branch appends a **URL-count feature** (`https?://|www.` regex hits per email, MaxAbs-scaled) via `FeatureUnion`, since URL presence patterns are among the strongest structural phishing indicators [3].

**Memory engineering.** Character n-gram `TfidfVectorizer` would materialize a multi-million-entry vocabulary; `HashingVectorizer` is stateless with a fixed 2^18-column budget and float32 storage, keeping the CSR matrices small. The URL-count transformer streams input with object dtype after an incident where `astype(str)` on a Series containing one ~195k-character email attempted a ~9 GB fixed-width allocation.

### C. Combination and Tuning

The three branches soft-vote (`VotingClassifier`, `voting="soft"`). Vote weights are searched on the validation split over a small preset grid; because voting weights apply at predict time, one fit covers the entire search at zero additional training cost. The deployed weights are (2, 1, 2).

### D. Data

The training corpus is rebuilt from per-source CSVs of the Kaggle "Phishing Email Dataset" (CEAS'08, Enron, Ling-Spam, Nazario, Nigerian Fraud, SpamAssassin; ~82k emails), using `subject + "\n" + body` with **original casing and punctuation**. A `DATASET_VERSION` switch in the training notebook alternates between this corpus (`v3_per_source`), a raw-text HF Email4S corpus (`v2_email4s`, ~18.6k), and the original normalized single-file CSV (`v1_alam`). Splits are 70/15/15 stratified at `SEED=42`, with a final refit on train+validation before export.

### E. Evaluation and Deployment Guard

Metrics: accuracy, precision, recall, F1, ROC-AUC, PR-AUC, on validation (selection) and test (deployment). Because the downstream fusion consumes probabilities, PR-AUC and calibration behavior are tracked alongside ROC-AUC. The **deployment guard** exports the challenger only if it (1) beats the same run's baseline on validation and test ROC-AUC and (2) meets or beats the incumbent deployed artifact's test ROC-AUC; otherwise the shipped artifact is retained.

## IV. EXPERIMENTAL SETUP

All experiments ran in the project venv (Python 3.13, scikit-learn 1.9, Windows) via headless notebook execution from the project root. The experiment series, logged in `ml_results.md`, comprised: (0) the normalized-corpus TF-IDF + LogReg baseline; (1) the ensemble on the same corpus; (2) chi-square feature selection (k=30,000); (3) the full pipeline re-run on the Email4S corpus; (4) the corpus rebuild from raw per-source CSVs with the ensemble; plus post-deployment verification of artifact loadability in a fresh process, fixture sanity scores, and a serialization fix.

## V. RESULTS AND DISCUSSION

### A. Headline Results (held-out test split)

| Exp         | Dataset                     | Model                          |     Test ROC-AUC |      Test PR-AUC |          Test F1 | Deployed                |
| ----------- | --------------------------- | ------------------------------ | ---------------: | ---------------: | ---------------: | ----------------------- |
| 0           | v1 normalized               | TF-IDF + LogReg                |           0.9989 |           0.9989 |           0.9876 | superseded              |
| 1           | v1 normalized               | 3-branch ensemble              |           0.9993 |           0.9994 |           0.9905 | later superseded        |
| 2           | v1 normalized               | chi2 k=30k + LogReg            |           0.9986 |           0.9986 |           0.9848 | no                      |
| 3           | v2 Email4S                  | ensemble                       |           0.9985 |           0.9985 |                - | no (guard)              |
| **4** | **v3 raw per-source** | **ensemble + URL count** | **0.9997** | **0.9997** | **0.9940** | **yes (current)** |

### B. Findings

**Feature diversity beats feature selection.** Chi-square pruning to 30k features was strictly worse than the unpruned baseline (0.9986 vs 0.9989 test ROC-AUC): aggressive vocabulary pruning removes useful low-frequency signal. The winning axis was *adding* heterogeneous feature views (char n-grams, URL counts), not removing weak features.

**Raw data beats a bigger normalized model.** The single largest gain came from the corpus rebuild: restoring casing, punctuation, and subject lines (v3) lifted the ensemble from 0.9993 to 0.9997 test ROC-AUC. EDA on the normalized corpus had shown capitalization and punctuation features to be all-zero (uninformative), confirming the normalized corpus was discarding discriminative structure.

**The guard earns its keep twice.** It blocked the Email4S run (0.9985 < incumbent 0.9993) despite that model being internally consistent, correctly attributing the regression to the smaller corpus rather than the architecture: the ensemble-vs-baseline gain transferred across datasets (+0.0009 test ROC-AUC in both v2 and v3). It then admitted the v3 challenger (0.9997 ≥ 0.9993).

**Small-data honesty.** The Email4S experiment was kept despite losing: it demonstrated the architecture is not corpus-specific, and its recorded failure is part of the evidence trail for the dataset choice.

### C. The Serialization Incident

The first v3 export pickled `url_count_feature` from the notebook kernel's `__main__`, so `joblib.load` failed in every fresh process, including the downstream agent notebook's model-load cell. The fix moved the transformer into an importable repo module (`phishing_model_utils.py`) and retrained. Lesson: any custom transformer pickled from a notebook must live in an importable module; artifact loadability must be verified in a fresh process, not the training kernel.

### D. Operational Behavior in the Host System

On the downstream fixtures the ensemble is more conservative than the old baseline (phishing 0.8351 vs 0.9803; benign 0.1797 vs 0.1603), while offline metrics are strictly better. Combined scores stayed far from the fusion threshold (0.93 phishing, 0.16 benign vs threshold 0.70) and verdicts were unchanged, but the observation stands: fusion weights tuned under one score distribution should be re-validated after any model swap.

### E. Limitations

Metrics near 0.9997 on this corpus family are partly corpus-easy: the constituent corpora are 2000s-era, near-duplicate leakage across sources inflates naive split estimates, and a genuinely fresh adversarial phish (novel infrastructure) is underrepresented. The evaluation fixtures are two emails, not a benchmark. Calibration is assessed indirectly (PR-AUC, threshold sweep) rather than with a dedicated calibration set. The remaining metric headroom is dominated by label noise and genuinely ambiguous mail rather than model capacity.

## VI. CONCLUSION AND FUTURE WORK

The ML layer demonstrates that a phishing classifier can be simultaneously strong (0.9997 held-out ROC-AUC), cheap (minutes of CPU training, milliseconds of inference), and operationally swappable (fixed contract + deployment guard): the host agentic system absorbed a full model replacement with zero pipeline code changes. The two transferable lessons are procedural: (1) diversify features and data views before pruning them, and (2) treat artifact serialization and loadability as first-class deployment concerns.

Future work: (1) a labeled batch evaluation to validate calibration and downstream fusion weights under the new score distribution; (2) adversarial and obfuscation-robustness testing against the character branch; (3) a stronger corpus (e.g., the MeAJOR multi-source corpus [3]) behind the same guard; (4) monitoring for dataset drift, since the current corpora are dated.

## REFERENCES

[1] D. Sahoo, C. Liu, and S. C. H. Hoi, "Malicious URL Detection using Machine Learning: A Survey," arXiv:1701.07179, 2017.

[2] F. Pedregosa et al., "Scikit-learn: Machine Learning in Python," *Journal of Machine Learning Research*, vol. 12, pp. 2825-2830, 2011.

[3] P. Mendes, E. Maia, and I. Praça, "MeAJOR Corpus: A Multi-Source Dataset for Phishing Email Detection," in *Proc. IEEE/WIC/ACM Int. Joint Conf. on Web Intelligence and Intelligent Agent Technology (WI-IAT)*, 2025. arXiv:2507.17978.

[4] A. Khalid et al., "LogiTriBlend: A Novel Hybrid Stacking Approach for Enhanced Phishing Email Detection Using ML Models and Vectorization Approach," *IEEE Access*, vol. 12, pp. 193807-193821, 2024, doi: 10.1109/access.2024.3518923.

[5] A. Alhuzali, A. Alloqmani, M. Aljabri, and F. Alharbi, "In-Depth Analysis of Phishing Email Detection: Evaluating the Performance of Machine Learning and Deep Learning Models Across Multiple Datasets," *Applied Sciences*, vol. 15, no. 6, p. 3396, 2025, doi: 10.3390/app15063396.

[6] B. W. Matthews, "Comparison of the Predicted and Observed Secondary Structure of T4 Phage Lysozyme," *Biochimica et Biophysica Acta*, vol. 405, no. 2, pp. 442-451, 1975. (Confusion-matrix lineage for TP/FN/FP/TN analysis.)
