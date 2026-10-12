# Agentic Phishing Email Detection and Explanation System

An agentic AI system that detects phishing emails, investigates suspicious indicators with live web search and threat intelligence, and produces evidence-backed, explainable verdicts. Built as a local Jupyter notebook pipeline: a supervised ML classifier, an independent decision model (Jev), and a Gemini-driven investigation agent are fused into a single risk score with a full audit trail.

Final results - section 7 in @results.md. 

```
EMAIL -> parse + IOC extraction -> ML score -> header analysis -> Jev score
     -> deterministic OTX prefetch -> Gemini agent brain (Tavily/OTX tools, max 2 turns)
     -> Gemini evidence scorer -> weighted fusion (0.45 ML + 0.25 Jev + 0.30 G)
     -> verdict (threshold 0.70) + confidence + hierarchical evidence graph + report
```

## Results at a glance

| Test email                           |    ML |   Jev | Gemini |        Combined | Verdict           | Wall time |
| ------------------------------------ | ----: | ----: | -----: | --------------: | ----------------- | --------: |
| Microsoft typosquat credential phish | 0.980 |  1.00 |   0.99 | **0.991** | PHISHING          |  ~2.3 min |
| Benign GitHub digest                 | 0.160 | 0.133 |   0.05 | **0.120** | LIKELY LEGITIMATE |  ~2.3 min |

Budget-bounded: at most 4 Gemini calls per email (20 RPD free tier friendly), with a live-verified 429 fallback from `gemini-3.8-flash` to `gemini-3.1-flash-lite`. Full numbers, incident log, and analysis in `results.md`; the research write-up in `project_report.md`.

## Repository layout

```
agentic_phishing.ipynb     the pipeline notebook (local Jupyter, no Colab)
phishing_detector.joblib   pre-trained ML artifact (TF-IDF + Logistic Regression)
requirements.txt           venv dependencies
.env                       API keys (NOT for version control; see .gitignore)
architecture.md            system architecture (developer reference)
results.md                 instrumented run results, metrics, incident log
project_report.md         IEEE-format research report
run_metrics.json           machine-readable metrics of the latest run
evidence_graph_*.html     rendered evidence graphs (hierarchical, interactive)
```

## Setup

Requirements: Python 3.10+ and a `.env` file in the project root with:

```
GEMINI_API_KEY=...     # Google AI Studio
TAVILY_API_KEY=...     # tavily.com
OTX_API_KEY=...        # otx.alienvault.com
OPENROUTER_API_KEY=... # optional, enables the Jev decision model
```

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m ipykernel install --user --name agentic-phishing --display-name "Python (agentic-phishing)"
jupyter lab
```

Open `agentic_phishing.ipynb`, select the **Python (agentic-phishing)** kernel, and run all cells top to bottom. The notebook must run from the project root (`.env` and the model artifact resolve via the working directory).

## Key configuration (inside the notebook)

| Knob                                           | Default                                  | Effect                                                                             |
| ---------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------- |
| `MAX_AGENT_ROUNDS`                           | 2                                        | Brain call budget per email                                                        |
| `USE_JEV`                                    | True                                     | OpenRouter decision model on/off                                                   |
| `GEMINI_EXPLANATION`                         | True                                     | Final narrative via Gemini;`False` = deterministic Python report (3-call budget) |
| `ML_WEIGHT / JEV_WEIGHT / GEMINI_WEIGHT`     | 0.45 / 0.25 / 0.30                       | Fusion weights (renormalized when a subsystem is unavailable)                      |
| `PHISHING_THRESHOLD`                         | 0.70                                     | Decision threshold                                                                 |
| `PRIMARY_BRAIN_MODEL / FALLBACK_BRAIN_MODEL` | gemini-3.8-flash / gemini-3.1-flash-lite | 429 fallback pair                                                                  |

## Operational notes

- Free-tier quotas are per Google project per model; RPD resets at midnight Pacific Time. When `gemini-3.8-flash` (20 RPD) exhausts, the brain automatically falls back to flash-lite and logs the switch.
- A suspicious email costs at most 4 Gemini calls and roughly 2-3 minutes; Jev costs about $0.00004 per email.
- The evidence graph JSON for each run is persisted in `run_metrics.json`, so graph styling can be iterated offline without API calls.
