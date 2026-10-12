# Full Run Results — Agentic Phishing Detection System

**Latest update:** 2026-10-13 (v4 run with the new ML model)
**Environment:** Windows, Python 3.13.7 in `.venv`, keys from `.env` via `python-dotenv`
**Method:** headless execution of all `agentic_phishing.ipynb` cell code with instrumented calls through `analyze_email`
**Test inputs:** the notebook's phishing fixture (`micros0ft-support.example` credential phish) and a benign GitHub digest email
**Artifacts:** `run_metrics.json` (latest run, incl. full evidence-graph JSON), `run_metrics_initial.json` (first discovery run), `evidence_graph_phishing.html`, `evidence_graph_legit.html`

---

## 1. What changed between runs

1. **ML model replaced (v4).** `phishing_detector.joblib` is no longer TF-IDF + Logistic Regression. It is now a 3-branch soft-voting ensemble — word TF-IDF + LogReg, hashed char-n-gram (3-4) + MultinomialNB, hashed char-n-gram + calibrated LinearSVC, each branch augmented with a URL-count feature — trained on ~82k **raw** per-source emails (`subject + body`, original case/punctuation) instead of the normalized single-file corpus. Offline test metrics: ROC-AUC 0.9997 / PR-AUC 0.9997 / F1 0.9940 (vs 0.9989 / 0.9989 / 0.9876 for the old baseline). Full experiment history in `ml_experiments.md`; dataset options in `dataset_candidates.md`. The artifact contract (`predict_proba([email_text])[0, 1]`) is unchanged, so the agent pipeline code is untouched.
2. **Deterministic IOC prefetch.** (v3) A new `ioc_prefetch` node runs OTX lookups for all extracted domains/URLs/IPs (parallel, capped at 8) *before* the agent brain runs. The brain receives the results in its first turn and is instructed not to re-query them. In the v4 phishing run the brain again made **zero** OTX calls and spent its turns on self-formulated Tavily searches.
3. **Thinking levels.** (v3) `thinking_level="low"` on the 3.8-flash brain, `"minimal"` on flash-lite (fallback brain, scorer, explainer). In v4 the phishing run's first brain call executed on 3.8-flash with `low` without issue, then 429'd mid-run and switched to flash-lite; the legit run 429'd on both brain calls and ran flash-lite throughout.
4. **OTX 400/404 semantics.** (v3) Mapped to clean `pulse_count: 0, note: "no threat intel available"` responses. Zero OTX errors in v4.
5. **Hierarchical evidence graph.** (v3) Physics-off vis.js hierarchical layout, node colors by type with legend, per-query collapsed Tavily nodes, OTX nodes labeled indicator + pulse count.

## 2. Latest run (v4, new ML model) — headline numbers

| | Phishing email | Legitimate email |
|---|---|---|
| Wall time | **158.1 s** | **227.5 s** |
| Verdict | **PHISHING** | **LIKELY LEGITIMATE** |
| Combined score | 0.9258 | 0.1590 |
| Confidence | 0.8481 | 0.8215 |
| Both correct | yes | yes |

### Latency history (phishing email)

| Run | Brain model | Wall time | Notes |
|---|---|---:|---|
| v1 discovery | 3.8-flash, default thinking | 427.2 s | OTX via brain, header-parse bug present |
| v2 clean | 3.8-flash, default thinking | 771.3 s | headers fixed, 3 OTX + 0 Tavily via brain |
| v3 optimized | flash-lite via 429 fallback | 136.0 s | prefetch + Tavily via brain + thinking minimal |
| **v4 new ML model** | **3.8-flash turn 1, flash-lite turn 2 (429)** | **158.1 s** | same pipeline, ensemble artifact |

### Call accounting (v4)

| Stage | Phishing run | Legit run |
|---|---:|---:|
| Brain calls (3.8-flash) | 1 | 0 (429 on both) |
| Brain calls (flash-lite via fallback) | 1 | 2 |
| Scorer + explainer (flash-lite) | 2 | 2 |
| **Total Gemini** | **4** | **4** |
| Jev (OpenRouter) | 1 (~$0.00004) | 1 (~$0.00004) |
| Tavily searches (brain-formulated) | 1 | 1 |
| OTX lookups (deterministic prefetch) | 3 | 2 |
| Brain tokens (in/out) | 3,903 / 308 | 7,078 / 289 |

**The 429 fallback router worked live again:** the phishing run's first brain call succeeded on 3.8-flash (with `thinking_level="low"`), the second 429'd and switched to flash-lite mid-run; the legit run 429'd on both brain calls and ran flash-lite throughout. No pipeline failures on any path.

## 3. Interim scores (v4, pre-fusion)

### Phishing email

| Subsystem | Score | Detail |
|---|---:|---|
| ML classifier | 0.8351 | new 3-branch ensemble artifact (was 0.9803 with the old TF-IDF + LogReg) |
| Header analysis | 1.00 | SPF/DKIM/DMARC failed, Reply-To and Return-Path domain mismatches |
| URL analysis | 0.10 | "verify, account" keywords only; fake `.example` TLD trips few heuristics |
| Jev | 1.00 (raw 4/4) | urgency 0.99, credential_request 0.93, impersonation 0.99, suspicious_action 0.99 |
| Gemini investigation (G) | 1.00 | 5 evidence-backed reasons |

Fusion: `0.45(0.8351) + 0.25(1.0) + 0.30(1.0) = 0.9258` (threshold 0.70 → PHISHING).

### Legitimate email

| Subsystem | Score | Detail |
|---|---:|---|
| ML classifier | 0.1797 | new 3-branch ensemble artifact (was 0.1603) |
| Header analysis | 0.00 | github.com aligned everywhere, spf/dkim/dmarc pass |
| URL analysis | 0.00 | |
| Jev | 0.1325 (raw 0.53/4) | urgency 0.02, credential_request 0.02, impersonation 0.15, suspicious_action 0.22 |
| Gemini investigation (G) | 0.15 | |

Fusion: `0.45(0.1797) + 0.25(0.1325) + 0.30(0.15) = 0.1590` → LIKELY LEGITIMATE.

**Effect of the model swap on fixtures:** the ensemble is more conservative on both test emails (phish 0.8351 vs 0.9803, legit 0.1797 vs 0.1603). Trained on raw mixed-case per-source text with hashed char n-grams and a URL-count feature, it distributes probability differently from the word-TF-IDF LogReg trained on normalized text. Offline it is strictly stronger (test ROC-AUC 0.9997 vs 0.9989, F1 0.9940 vs 0.9876); on the two fixtures the verdicts and margins are unaffected (0.93 vs 0.16 combined, threshold 0.70).

## 4. Incident log (all runs, cumulative)

1. **`pandas` missing from requirements** (v1): Colab preinstalled it; local venv did not. Fixed.
2. **`load_dotenv()` discovery failure** (v1): silent empty load under headless exec. Fixed with explicit `Path.cwd()/".env"`.
3. **Silent header-parsing bug** (v1): fixture's leading newline made the entire email parse as body; header subsystem contributed nothing with no warning. Fixed via `parsestr(raw_email.lstrip())`.
4. **Fixture `Subject` after the header/body separator** (v1): parsed as body text. Fixed in the phishing fixture; the runner's legit email had the same quirk in v3 (subject parsed empty; no effect on verdict) and is now fixed for future runs.
5. **OTX 400s on fake TLDs** (v2): raw errors in the evidence packet. Mapped to clean "no intel" responses in v3; zero OTX errors since.
6. **3.8-flash quota exhaustion + anomaly** (v3 verification): hit the real 429 (limit 20/day) while A/B-ing thinking levels; also observed one anomalous 110.9s response on a trivial prompt at `thinking_level="low"`, and `minimal` rejected outright. The `low` setting is valid but its latency benefit on 3.8-flash is still unproven; measure after reset.
7. **Behavior variance at temperature 0** (all runs): each run the brain chose different tools (3 OTX + 1 Tavily → 3 OTX → 2 Tavily → 1 combined-phrase Tavily). Verdicts stable; paths differ.
8. **ML artifact pickle referenced `__main__`** (v4 verification): the first ensemble export pickled `url_count_feature` from the notebook kernel's `__main__`, so `joblib.load` failed in any fresh process (including the agent notebook). Fixed by moving the function to `phishing_model_utils.py` (importable module) and retraining; the artifact now loads from any process with the project root importable.

## 5. Remaining risks

- **Flash-lite as brain is more trigger-happy.** In v3/v4 it ran a Tavily search even on the benign digest (the 3.8 brain skipped investigation entirely in v2). Correct verdict either way, but flash-lite burns one extra call and ~80s when it chooses to search. Watch false-positive-investigation behavior in a batch.
- **Score independence remains partial** (scorer sees M and J), threshold/weights still unvalidated, confidence still not a probability.
- **No labeled batch yet.** Four clean runs on two emails is a sanity check, not an evaluation.
- **ML fixture scores drifted with the model swap** (0.98 → 0.84 phish, 0.16 → 0.18 legit). Offline metrics are strictly better, but the fusion weights were chosen under the old score distribution; re-tune if a labeled batch shows the 0.45/0.25/0.30 split is no longer right.

## 6. Analysis: how good is the system?

**Latency.** The phishing path is now ~2.6 min worst case (v4, 3.8-flash turn 1 then flash-lite), ~2.3 min with flash-lite brain throughout (v3), down from 7-13 min originally. Usable for interactive analysis of a suspicious email, not just batch.

**Robustness.** The quota exhaustion during v3 verification turned into a live end-to-end test of the degradation path, and v4 exercised it again differently (one 3.8-flash call, then mid-run 429 → flash-lite; both calls 429 → flash-lite): brain fell back mid-run, both verdicts correct, no pipeline failure. Combined with the OTX 400 mapping and the scorer/explainer fallbacks, every documented degradation path has now been exercised live.

**ML layer.** The deployed artifact is now the strongest model from the experiment series (test ROC-AUC 0.9997 / PR-AUC 0.9997 / F1 0.9940 on ~82k raw per-source emails; full history in `ml_experiments.md`). The model swap needed zero agent-pipeline changes beyond the pickle-module fix, validating the `predict_proba([text])[0,1]` contract.

**Investigation quality.** The prefetch restructure worked as intended again: mechanical lookups happen deterministically before the agent, and the agent's rounds go to the one thing only it can do. In v4 the brain formulated a single combined quoted-phrase query (`'"micros0ft-support" OR "secure-account-login" phishing Microsoft'`), tighter than v3's two separate searches.

**Evidence graphs.** 17 nodes / 18 edges (phishing) and 11 / 12 (legit) in a left-to-right pipeline layout: email → indicators → evidence → three model scores → verdict, colored by type with a legend, Tavily collapsed to one node per query. The full node/edge JSON is persisted in `run_metrics.json` so graph styling can be iterated offline without API calls.

**Next steps.** (1) Run a labeled batch (20-50 emails) to tune threshold/weights and quantify flash-lite-vs-3.8 brain behavior. (2) Consider routing investigation by ML score (skip external search for clearly benign mail; see `project_report.md`, Section VI) once false-negative impact can be measured.

## 7. Appendix: complete final output for the phishing email (v4 run)

Everything the system produced for the `micros0ft-support.example` credential phish, exactly as emitted by the pipeline (new ML artifact).

### Final scores and metrics

| Metric | Value |
|---|---:|
| ML detector (M) | 0.8351 |
| Jev (J) | 1.0000 (raw 4/4) |
| Gemini investigation (G) | 1.0000 |
| **Combined score (S)** | **0.9258** |
| Threshold | 0.70 |
| **Verdict** | **PHISHING** |
| Confidence | 0.8481 |
| Explanation source | gemini |
| Wall time | 158.1 s |
| Gemini calls | 4 (1 brain on 3.8-flash + 1 brain on flash-lite via 429 fallback + 1 scorer + 1 explainer) |
| Jev calls | 1 (950 in / 92 out tokens, cost ~$0.00004) |
| Brain tokens (in/out) | 3,903 / 308 |
| Tavily searches | 1 (brain-formulated) |
| OTX lookups | 3 (deterministic prefetch, 0 errors) |
| Evidence graph | 17 nodes / 18 edges |

**Jev signals:** urgency 0.99, credential_request 0.93, impersonation 0.99, suspicious_action 0.99.

**Agent tool calls (brain):** `tavily_search('"micros0ft-support" OR "secure-account-login" phishing Microsoft')` — a single combined quoted-phrase query, zero redundant OTX calls.

**Header findings:** SPF failed; DKIM failed; DMARC failed; From domain differs from Reply-To domain; From domain differs from Return-Path domain (header score 1.00).

**URL findings:** `https://micros0ft-support.example/account/verify` — score 0.10, feature: security/account keywords (verify, account).

### Gemini investigation reasons (evidence scorer)

1. The sender domain 'micros0ft-support.example' uses a common typosquatting technique (replacing 'o' with '0') to impersonate Microsoft.
2. Authentication checks (SPF, DKIM, DMARC) all failed, indicating the email is not authorized by the purported sender.
3. The email uses high-pressure, urgent language threatening account suspension to coerce the user into clicking a malicious link.
4. The Reply-To and Return-Path domains differ from the From domain, a classic indicator of email spoofing.
5. External research confirms that Microsoft does not use domains like 'micros0ft-support' and that such patterns are characteristic of credential harvesting scams.

### Final report (Gemini narrative + reasons + recommendation)

> **Summary:** "The analyzed email is a confirmed phishing attempt designed to harvest user credentials by impersonating Microsoft."

**Reasons:**

1. The sender domain 'micros0ft-support.example' utilizes typosquatting (replacing 'o' with '0') to deceive recipients.
2. Email authentication protocols (SPF, DKIM, and DMARC) all failed, confirming the message is not authorized by the legitimate Microsoft domain.
3. The email employs high-pressure, urgent language regarding account status to coerce the user into clicking a malicious link.
4. The Reply-To and Return-Path domains do not match the From domain, which is a common indicator of email spoofing.
5. External research confirms that Microsoft does not use the identified domain and that such patterns are characteristic of credential harvesting scams.

**Recommendation:** Do not click any links or provide credentials. Delete the email immediately. If you have already interacted with the link, change your account password immediately and enable multi-factor authentication (MFA) on your account. Report the email using your email provider's built-in phishing reporting tool.

**Evidence graph:** `evidence_graph_phishing.html` — hierarchical left-to-right layout: EMAIL → sender/URL/domain → 5 header findings + 3 OTX nodes + 1 collapsed Tavily node → ML/Jev/Gemini model scores → PHISHING verdict (red). Full node/edge JSON in `run_metrics.json` → `phishing_run.evidence_graph_nodes/edges`.

**Static snapshot** (`evidence_graph_phishing.png`, captured headlessly with Playwright driving Edge at 2x scale; the interactive original is the HTML):

![Phishing evidence graph: pipeline from EMAIL through sender, URL, domain, header findings, OTX and Tavily evidence nodes, three model scores, to the PHISHING verdict](evidence_graph_phishing.png)
