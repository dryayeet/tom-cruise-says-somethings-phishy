# System Architecture — Agentic Phishing Email Detection & Explanation

## 1. Overview

A LangGraph-orchestrated pipeline that classifies an email, prefetches threat intelligence deterministically, investigates further with an agentic LLM loop, fuses three scores, and emits an evidence-linked report and hierarchical evidence graph. Runs as a local Jupyter notebook (`agentic_phishing.ipynb`) with a virtualenv, `.env` secrets, and a pre-trained joblib model. No Colab dependencies.

```
                    +---------------+
                    |    EMAIL      |
                    +-------+-------+
                            |
                  deterministic preprocessing
                            |
           +----------------+----------------+
           v                v                v
          ML            Headers            URLs
           |                |                |
           +----------------+----------------+
                            v
                     Jev (optional)   OpenRouter ~typesafe/jev-latest
                            |
                            v
                  +-----------------------+
                  | IOC PREFETCH (OTX)   |   deterministic, parallel
                  +-----------------------+
                            |
                            v
                  +---------------------+
                  | GEMINI 3.8 FLASH    |
                  | AGENT BRAIN         |
                  | (max 2 turns)      |
                  +----------+----------+
                             |
                     parallel tool calls
                    +---------+----------+
                    v                     v
                 Tavily              OTX (only new
                    |                indicators)
                    +----------+----------+
                               v
                 +-----------------------+
                 | GEMINI 3.1 FLASH-LITE |
                 | EVIDENCE SCORER -> G |
                 +-----------+-----------+
                             |
             +---------------+----------------+
             v               v                v
            ML score      Jev score       G score
             +---------------+----------------+
                             v
                       PYTHON FUSION
                  0.45M + 0.25J + 0.30G
                             v
                       COMBINED SCORE
                             v
                    threshold 0.70 verdict
                             v
                Evidence graph (hierarchical PyVis)
                             v
              Python report + optional Gemini narrative
```

## 2. LangGraph nodes

| Node | Type | Role |
|---|---|---|
| `parse_email` | deterministic | Parses headers (From/Reply-To/Return-Path/Authentication-Results), extracts body. Strips leading whitespace so malformed raw emails still parse. |
| `extract_iocs` | deterministic | Regex extraction of URLs, domains, IPs from subject + body + headers. |
| `url_analysis` | deterministic | Heuristic URL scoring (IP host, punycode, `@`, length, depth, hyphens, keywords, suspicious TLDs). |
| `ml_predict` | deterministic | `phishing_detector.joblib` (TF-IDF + Logistic Regression pipeline) on raw email text, phishing probability. |
| `header_analysis` | deterministic | SPF/DKIM/DMARC failure detection, Reply-To and Return-Path domain mismatch vs From. |
| `jev` | external | OpenRouter alpha `decisions` API, model `~typesafe/jev-latest`. Returns 0-4 phishing score (normalized to 0-1) plus signals: urgency, credential_request, impersonation, suspicious_action. Optional; skipped without `OPENROUTER_API_KEY`. |
| `ioc_prefetch` | deterministic | Runs OTX lookups for all extracted domains/URLs/IPs (deduplicated, capped at 8, parallel `ThreadPoolExecutor`, ~1-2s) *before* the agent runs, so the brain never spends its 2-round budget on mechanical lookups. |
| `investigator` | agentic | `gemini-3.8-flash` with `tavily_search` + `otx_lookup` bound, `thinking_level="low"`. Receives prefetched OTX results in turn 1 and is instructed not to re-query them. Instructed to batch parallel tool calls. Max 2 model turns (`MAX_AGENT_ROUNDS = 2`). |
| `tools` | LangGraph `ToolNode` | Executes tavily/otx calls, appends `ToolMessage`s. |
| `collect_tool_results` | deterministic | Harvests parsed JSON from ToolMessages into `tavily_results` / `otx_results` (additive with prefetch results). |
| `investigation_score` | LLM | `gemini-3.1-flash-lite` with structured output (`InvestigationAssessment`): phishing_score 0-1, evidence quality, evidence-backed reasons. Graceful failure: score becomes `None`, fusion reweights. |
| `build_evidence_graph` | deterministic | Builds node/edge lists: email, sender, URLs, domains, header findings, one node per OTX indicator (label with pulse count), one node per Tavily query (results in tooltip), three model nodes, verdict node. |
| `combine_scores` | deterministic | Weighted fusion, confidence, verdict (see §4). |
| `final_explanation` | LLM (optional) | `gemini-3.1-flash-lite` writes the narrative report from the full evidence packet. Falls back to a deterministic Python report (`fallback_explanation`). |

Graph flow: `parse_email -> extract_iocs -> url_analysis -> ml_predict -> header_analysis -> jev -> ioc_prefetch -> investigator -> (tools -> collect_tool_results -> investigator)* -> investigation_score -> build_evidence_graph -> combine_scores -> final_explanation -> END`.

## 3. Model roles, call budget, rate-limit router

| Stage | Model | Thinking | Max calls/email |
|---|---|---|---:|
| Agent brain | `gemini-3.8-flash` (20 RPD free tier) | `thinking_level="low"` | 2 |
| Brain fallback | `gemini-3.1-flash-lite` | `thinking_level="minimal"` | (on 429) |
| Evidence scorer | `gemini-3.1-flash-lite` | `thinking_level="minimal"` | 1 |
| Final explainer | `gemini-3.1-flash-lite` | `thinking_level="minimal"` | 0-1 (`GEMINI_EXPLANATION` toggle) |
| Fusion + report rendering | Python | n/a | 0 |
| Jev | OpenRouter | n/a | 1 (separate budget, ~$0.00004) |
| IOC prefetch | Python + OTX API | n/a | 0 Gemini calls |

Worst case: 4 Gemini calls/email. Typical: 3 (fewer when the brain finds no investigation necessary).

Notes verified live: 3.8-flash rejects `thinking_level="minimal"` (400) and accepts `"low"`; flash-lite accepts `"minimal"`. Default 3.8-flash thinking is the dominant latency source (953 output tokens on a small probe).

**Rate-limit router (`invoke_brain`):** on a 429/`RESOURCE_EXHAUSTED` from `gemini-3.8-flash`, the brain switches to `gemini-3.1-flash-lite` for the rest of the call. If that also rate-limits, investigation is skipped: the investigator returns a synthetic AIMessage with no tool calls, the graph proceeds to scoring on deterministic + prefetched evidence. Verified end-to-end in a live run after real quota exhaustion. Quotas are per Google project per model, so model switch, not key rotation, is the correct recovery.

## 4. Score fusion, confidence, verdict

With M = ML, J = Jev, G = Gemini investigation scores:

```
combined = (0.45*M + 0.25*J + 0.30*G) / sum_of_available_weights
```

Weights renormalize if a subsystem is unavailable (Jev disabled, scorer failed). `ValueError` only if all three are missing.

```
agreement = 1 - min(pstdev(scores) / 0.5, 1)    # consensus across subsystems
margin    = min(abs(combined - 0.5) * 2, 1)     # distance from neutral
confidence = 0.5*agreement + 0.5*margin
verdict = PHISHING if combined >= 0.70 else LIKELY LEGITIMATE
```

Confidence is an agreement-plus-margin heuristic, not a calibrated probability.

## 5. Degradation semantics

| Failure | Behavior |
|---|---|
| 3.8-flash 429 | Brain falls back to flash-lite (logged) — verified live |
| Both brain models 429 | Investigation skipped, scoring on deterministic + prefetch evidence (logged) |
| Scorer error | `investigation_score = None`, fusion reweights M + J, reason recorded |
| Jev disabled / error | `jev.available = False`, fusion reweights |
| OTX 400/404 | Mapped to `pulse_count: 0, note: "no threat intel available"` — no longer an error |
| Tavily error | Tool returns JSON error payload, investigation continues |
| Explainer error / disabled | `fallback_explanation` renders the deterministic Python report (`explanation_source: python`) |

## 6. Evidence graph

Rendered by `render_evidence_graph(result, filename=None)`:

- **Hierarchical vis.js layout**, left-to-right, physics off: `EMAIL -> indicators/evidence -> models -> VERDICT` reads as a pipeline with branches instead of a force-directed hairball.
- **Type encoding with legend:** email dark slate, sender gray, URL/domain purple, header findings red, OTX threat intel orange, Tavily web results green, model scores blue, verdict red (PHISHING) or green (LIKELY LEGITIMATE). Legend overlaid on the page.
- **De-cluttered:** one node per Tavily query (result list + answer in tooltip) instead of one node per search result; OTX nodes labeled `OTX: <indicator> (N pulses)`; labels truncated at 44 chars with full data in tooltips; node size scaled by role (verdict largest).
- Full node/edge JSON is persisted per run in `run_metrics.json`, so visualization styling can be iterated offline without API calls.

## 7. Outputs

- **Final report:** verdict, combined score, confidence, score breakdown, header/URL findings, Jev signals, investigation reasons, summary, recommendation, explanation source.
- **Evidence graph:** standalone HTML (`evidence_graph_*.html`).
- **Agent tool trace:** full message history with tool calls, arguments, and results.

## 8. Repository layout

```
agentic-phishing/
  agentic_phishing.ipynb     # the agentic pipeline notebook (local Jupyter)
  phishing_detector.joblib   # pre-trained ML artifact (Notebook 1, TF-IDF + LogReg)
  requirements.txt           # venv dependencies
  .env                       # GEMINI / TAVILY / OTX / OPENROUTER keys (not for version control)
  .venv/                     # Python 3.13 virtualenv, registered as "Python (agentic-phishing)" kernel
  results.md                 # run results, metrics, incident log, analysis
  run_metrics.json           # machine-readable metrics of the latest instrumented run
  run_metrics_initial.json   # metrics of the first discovery run
  evidence_graph_phishing.html / evidence_graph_legit.html
  abstract.md                # original project spec
  do_this.md                 # the architecture revision brief
```

## 9. How to run

```powershell
# from the project root
.venv\Scripts\python.exe -m pip install -r requirements.txt   # first time only
jupyter lab                                                    # or: jupyter notebook
```

Open `agentic_phishing.ipynb`, select the **Python (agentic-phishing)** kernel, run top to bottom. Keys are loaded from `.env` (required: `GEMINI_API_KEY`, `TAVILY_API_KEY`, `OTX_API_KEY`; optional: `OPENROUTER_API_KEY` for Jev). The model artifact loads from the notebook directory.

Operational notes: run from the project directory (`Path.cwd()` resolves `.env` and the model); free-tier rate limits apply per Google project per model, RPD resets midnight Pacific; a suspicious email costs at most 4 Gemini calls and roughly 2 minutes (flash-lite brain) to 13 minutes (3.8-flash brain with default thinking); a clean email about 1-2 minutes.
