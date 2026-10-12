# Dataset Candidates for the Phishing ML Model

Reference of current and alternative datasets for `phishing_ml.ipynb`. Selection criteria: raw (unnormalized) text, size, phishing-tactic diversity, CPU/RAM-feasibility, availability, licensing.

## Currently used

| Version | Dataset | Rows | Text state | Notes |
|---|---|---|---|---|
| v1 | `phishing_email.csv` (Alam Kaggle) | ~82k | Normalized (lowercased, punctuation stripped) | What exps 0-2 were trained on; no case/punctuation signal |
| v2 | HF `zefang-liu/phishing-email-dataset` (Email4S) | ~18.6k | Raw, mixed case/punctuation | Current dataset version; smaller, mostly same corpora families |

## Strong candidates (not yet used)

### 1. Per-source CSVs of the Alam Kaggle dataset (local, already cached)
- Files: `CEAS_08.csv`, `Nazario.csv`, `Nigerian_Fraud.csv`, `SpamAssasin.csv` (sender, receiver, date, subject, body, urls, label), `Enron.csv`, `Ling.csv` (subject, body, label).
- ~82k rows total; raw unnormalized bodies with headers/subject/URL metadata preserved.
- Highest ROI upgrade: no download, richer features (subject, sender, URLs), largest of the realistic options.
- Caveat: Enron/Ling bodies partially normalized; corpora are 2000s era.

### 2. MeAJOR Corpus (arXiv 2507.17978, WI-IAT 2025)
- 135,894 emails merged from Nazario, Nigerian Fraud, TREC-05/06/07 with engineered features: url_count, url lengths, subdomain counts, attachment flags, sender domain, language.
- Best documented feature set; URL features gave the largest reported gains in the paper (XGB 98.34% F1).
- Caveat: raw URLs/emails are masked with placeholder tags (structure preserved, exact links lost); repo location requires confirmation (paper CC BY 4.0).

### 3. Nazario Phishing Corpus (monkey.org/~jose/phishing)
- Canonical phishing-only corpus (~11.5k), raw messages with full headers. Needs benign counterpart (e.g., Enron).
- Good for header-based feature research; dated (2004-2007).

### 4. SpamAssassin public corpus
- ~6k raw spam/ham with full headers, the classic benchmark. Small but raw.

### 5. TREC 2007 public spam corpus
- 75,419 labelled raw emails, one of the largest public labelled collections. Age (2007) is the main drawback.

## Weak / niche candidates

- **IEEE DataPort Phishing Attack Dataset**: URL/link-based features, not email-body text.
- **PhishTank**: URL feed (not emails), useful only for URL n-gram experiments.
- **UTwente phishing validation emails dataset**: small validation set (real + artificial), useful as external test set for the deployed artifact.
- **HF drorrabin/phishing_emails-data**: check row count/schema; likely same corpora as Email4S.

## Decision guidance

- If v2 (Email4S) metrics hold up: keep, but the 18.6k size limits headroom.
- Best next upgrade: rebuild from local per-source CSVs (raw text + subject + sender + URLs, ~82k).
- Best research-grade upgrade: MeAJOR (engineered URL/attachment features), pending repo availability.
- Any switch must keep the artifact contract: `phishing_detector.joblib` with `predict_proba([email_text])[0, 1]`.
