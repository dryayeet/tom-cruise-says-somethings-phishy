# An Agentic Multi-Model System for Phishing Email Detection with Evidence-Backed Explanations

**lemon**
Department of Computer Science and Engineering, Manipal Academy of Higher Education, Manipal, India

---

**Abstract** — Traditional phishing email classifiers identify suspicious patterns but provide limited explanations for their predictions, while LLM-only solutions can produce unsupported conclusions and lack access to current threat intelligence. This paper presents an agentic system that combines a supervised TF-IDF + logistic regression classifier, an independent structured decision model (Jev), and a tool-using Gemini investigation agent within a LangGraph-orchestrated workflow. The agent autonomously queries live web search (Tavily) and threat intelligence (AlienVault OTX); deterministic IOC prefetching runs indicator lookups in parallel before the agent, and a per-project rate-limit router with model fallback keeps the system operational under free-tier quotas. Three independent scores are fused into a unified risk score with a verdict, a consensus-based confidence indicator, an evidence breakdown, and a hierarchical evidence graph. On instrumented end-to-end runs the system correctly classified both a typosquatting credential-phishing email (combined score 0.991) and a benign notification email (0.120), while respecting a hard budget of at most four Gemini calls per email and degrading gracefully under live quota exhaustion.

**Index Terms** — phishing detection, agentic AI, large language models, LangGraph, threat intelligence, explainability, score fusion.

---

## I. INTRODUCTION

Phishing remains one of the most effective initial access vectors for cybercrime, and the emergence of LLM-generated phishing content has lowered the barrier to convincing, error-free social engineering [7], [8]. Defensive tooling faces a tension: classical machine learning (ML) classifiers are fast and cheap but opaque, while large language model (LLM) judges are interpretable but can hallucinate and have no intrinsic access to current threat data.

This project addresses that gap with a hybrid, agentic approach. The contributions are:

1. **A multi-signal fusion architecture** that combines a supervised classifier (M), an independent decision model (Jev, J), and an evidence-based LLM investigation score (G) into a single calibrated-by-design risk score with explicit provenance for every contributing signal.
2. **A budget-bounded agentic investigation layer**: a Gemini agent with web search and threat-intelligence tools, hard-capped at two model turns per email, with deterministic prefetching of indicator lookups so the agent's scarce turns are spent only on evidence that requires judgment.
3. **Operational resilience under free-tier constraints**: a rate-limit router that detects 429 quota exhaustion on the primary brain model and falls back to a high-quota model, verified end-to-end against a real quota exhaustion event.
4. **Evidence-backed explanations**: every verdict ships with a reasons breakdown, an agent tool trace, and an interactive hierarchical evidence graph linking the verdict to each upstream signal.

The remainder of this paper is organized as follows. Section II situates the work in prior research. Section III details the system design and justifies the technology choices. Section IV describes the experimental setup. Section V presents results and discussion. Section VI concludes and proposes future work.

## II. RELATED WORK

**ML-based phishing detection** is well established. Surveys of malicious URL and phishing detection catalog decades of feature engineering and classical learning approaches, from blacklists to supervised models over lexical and content features [6]. These systems are fast and cheap but produce point predictions with little evidence. Our system retains such a classifier deliberately, as a deterministic anchor that any downstream stage can treat as factual input.

**LLM judges for phishing.** Recent work evaluates LLMs directly as phishing detectors: Patel et al. benchmark fifteen LLMs on scam emails and find that modern models detect phishing reliably [4]; Lee reports high accuracy with the important additional property of interpretable evidence for decisions [3]; Lin et al. improve small-model detection with prompt engineering, fine-tuning, and ensembling on the SpamAssassin and CEAS'08 corpora [5]. Multi-agent approaches go further: PhishDebate coordinates specialized agents (URL structure, HTML, semantics, brand impersonation) in a structured debate, reporting 98.2% recall and better interpretability than single-agent baselines [2]. Our system shares the multi-view philosophy but differs in two ways: it fuses an ML classifier and an independent decision model rather than relying on LLM self-consistency alone, and it grounds the LLM in external, retrievable evidence rather than only its parametric knowledge.

**Agentic tool use.** The investigation loop follows the ReAct pattern of interleaved reasoning and action, where an LLM decides which external tools to call and interprements their results to reduce hallucination [1]. LangGraph was chosen as the orchestration substrate precisely because it makes this loop, its state, and its hard bounds (round limits, conditional routing, tool nodes) explicit and auditable rather than implicit in prompt scaffolding.

**Threat context.** LLMs are also changing the offensive side: Hazell demonstrated LLM-assisted spear phishing at scale [7], and Bethany et al. found LLM-generated lateral phishing as effective as human-written messages in a 9,000-person university study [8]. This justifies our design bet: as generated phishing becomes cleaner and more personalized, static text-only classifiers will age poorly, while systems that check live, external ground truth (domain reputation, threat intelligence, brand-impersonation reports) and reason over it can adapt without retraining.

## III. METHODOLOGY

### A. Pipeline Overview

The system is a stateful LangGraph workflow. Each email passes through:

```
parse_email -> extract_iocs -> url_analysis -> ml_predict -> header_analysis
    -> jev (optional) -> ioc_prefetch -> investigator (agent loop, max 2 turns)
    -> tools (Tavily / OTX) -> collect_tool_results
    -> investigation_score -> build_evidence_graph -> combine_scores
    -> final_explanation -> END
```

Deterministic stages run before any LLM is invoked, so expensive calls always receive maximally pre-processed evidence.

**Why this split of labor.** Deterministic parsing and header analysis are exact and free; the ML classifier is cheap and general; Jev contributes an independent structured judgment; the agent contributes only what needs judgment: formulating good external queries and reading their results. This mirrors the classical recommendation to spend scarce model capacity on decisions, not mechanics.

### B. Deterministic Analysis

- **Email parsing** (stdlib `email`): From/Reply-To/Return-Path addresses, Authentication-Results, body extraction. Header analysis scores SPF/DKIM/DMARC failures and From-vs-Reply-To / Return-Path domain mismatches per the corresponding RFCs [9][10][11], which remain the strongest sender-authentication ground truth available client-side.
- **IOC extraction**: regex extraction of URLs, domains, and IPs; heuristic URL scoring (IP-literal hosts, punycode, userinfo `@`, length, label depth, hyphen count, credential-bait keywords, suspicious TLDs).

### C. Supervised Classifier

A TF-IDF + logistic regression pipeline (`phishing_detector.joblib`), trained offline in a separate notebook on raw email text. Logistic regression over TF-IDF was chosen for the anchor role because its scores are stable, its inference is milliseconds, and it degrades predictably, unlike deep alternatives that need more data and tuning for marginal gain in this prototype's scope [6][10].

### D. Jev Decision Model

Jev (via OpenRouter's decisions API, model `~typesafe/jev-latest`) receives the parsed email, extracted indicators, and header findings, and returns a 0-4 phishing score (normalized to [0,1]) plus four structured signals: urgency, credential_request, impersonation, suspicious_action. Jev is used because it is an *independent* decision model: a different vendor, a different prompting regime, and structured output rather than free text. At roughly $0.00004 per email it costs nothing to keep in the ensemble, and its signals give the final report concrete, checkable vocabulary.

### E. Deterministic IOC Prefetch

A prefetch node runs OTX lookups for every extracted domain, URL, and IP in parallel (thread pool, deduplicated, capped at 8 indicators, ~1.5s) *before* the agent. OTX 400/404 responses are mapped to a clean "no threat intel available" record rather than an error. The rationale: the agent's tool selection for already-known IOCs is mechanical, and measured runs confirmed the agent simply looked up the IOC list it was handed. Prefetching removes that round-trip entirely and leaves the agent's two-turn budget for genuinely discretionary evidence gathering. In the final run, the agent made zero redundant OTX calls and instead formulated targeted web searches.

### F. Agentic Investigation

The brain is `gemini-3.8-flash` with `tavily_search` and `otx_lookup` bound as tools, `thinking_level="low"` to bound reasoning latency. The system prompt instructs it to batch parallel tool calls in a single turn, to treat prefetched OTX results as given, and to stop when evidence is sufficient. Routing is hard-capped at `MAX_AGENT_ROUNDS = 2` model turns: tool calls requested on the final turn are not executed. A rate-limit router wraps every brain call: on 429/RESOURCE_EXHAUSTED the brain switches to `gemini-3.1-flash-lite` (with `thinking_level="minimal"`, verified supported); if that also exhausts, investigation is skipped and scoring proceeds on deterministic plus prefetched evidence. This exists because Google's free-tier quotas are per project per model: the 20 RPD of the primary brain model is the scarcest resource in the system, and key rotation does not reset it.

**Why two Gemini models.** Agentic tool selection is the one place where high-capability calls pay for themselves; the evidence-scoring and report stages are essentially structured inference over a fixed packet, for which a Flash-Lite tier model with ~25x the daily quota is sufficient. The split keeps average cost at 3-4 Gemini calls per email.

### G. Evidence Scoring and Score Fusion

A flash-lite model with structured output (`InvestigationAssessment`) reads the full evidence packet (email, header findings, URL findings, ML score, Jev output, Tavily and OTX results) and returns a [0,1] phishing score plus evidence-backed reasons. Fusion then combines available scores M, J, G as:

```
S = (0.45*M + 0.25*J + 0.30*G) / sum(available weights)
verdict = PHISHING if S >= 0.70 else LIKELY LEGITIMATE
```

Weights renormalize if a subsystem is unavailable; ML carries the largest weight as the only component trained on labeled data. Confidence is `0.5*agreement + 0.5*margin`, where agreement is derived from the population standard deviation of the subsystem scores and margin from the distance of S from 0.5. It is a consensus-plus-decisiveness heuristic, explicitly not a calibrated probability.

### H. Reporting and Evidence Graph

The final report renders deterministically in Python (verdict, score breakdown, confidence, reasons); an optional Gemini call adds a natural-language narrative, with a Python fallback if it fails. The evidence graph is emitted as node/edge lists and rendered with PyVis in a hierarchical left-to-right layout, physics disabled, node colors by evidence type (deterministic findings, external intel, web search, model judgments, verdict), one node per Tavily query, and OTX nodes labeled with indicator and pulse count. The intent is an audit artifact that reads as a pipeline with branches rather than an unstructured force-directed graph.

## IV. EXPERIMENTAL SETUP

Experiments ran the notebook's code headlessly from the project root on a local Windows machine (Python 3.13, venv), with keys loaded from `.env` via `python-dotenv`. Two test emails were used:

1. **Phishing**: a Microsoft-impersonation credential phish (typosquatted `micros0ft-support.example`, failing SPF/DKIM/DMARC, mismatched Reply-To/Return-Path, urgent suspension threat).
2. **Legitimate**: a benign GitHub digest notification (aligned `github.com` domains, passing authentication, no credential requests).

Each run executed the complete graph end to end. The runner instrumented: per-stage model calls (from message metadata), tool calls and results, token usage, subsystem scores, wall time, and the full evidence graph. The 3.8-flash brain quota (20 RPD) was exhausted during parameter verification, so the reported run exercised the fallback path live: every brain call hit a real 429 and switched to flash-lite.

## V. RESULTS AND DISCUSSION

### A. Classification Results

| Email | ML (M) | Jev (J) | Gemini (G) | Combined (S) | Confidence | Verdict |
|---|---:|---:|---:|---:|---:|---|
| Phishing | 0.9803 | 1.00 | 1.00 | **0.9911** | 0.9818 | PHISHING |
| Legitimate | 0.1603 | 0.1325 | 0.05 | **0.1203** | 0.8329 | LIKELY LEGITIMATE |

Both verdicts are correct and far from the 0.70 decision threshold. All subsystems individually pointed the right way on both emails, which the confidence metric reflects: near-total agreement plus a decisive margin for the phish; slightly lower agreement (ML's 0.16 above G's 0.05) on the legitimate email.

### B. Call Budget and Latency

| Run configuration | Brain model | Phishing wall time | Gemini calls/email |
|---|---|---:|---:|
| Pre-optimization, default thinking | gemini-3.8-flash | 771 s | 4 |
| Pre-optimization, no tools needed | gemini-3.8-flash | 61 s | 3 |
| Post-optimization (prefetch + capped thinking), fallback active | gemini-3.1-flash-lite | **136 s** | 4 |

The dominant latency factor is the brain model and its thinking budget, not tool I/O. After the prefetch + thinking changes (and with quota forcing the brain onto flash-lite), the phishing path fell from ~13 minutes to ~2.3 minutes. Two observations qualify this: the 3.8-flash + `thinking_level="low"` pairing remains to be measured after quota reset, and the flash-lite brain was more tool-happy on the benign email (it ran one discretionary web search that the 3.8 brain skipped), though the verdict was unaffected.

### C. Agent Behavior

In the final phishing run the brain made zero OTX calls (respecting the prefetch instruction) and spent its turns formulating two parallel, well-targeted Tavily queries (quoted-phrase lookups of the typosquatted domains), whose results (Microsoft's own anti-phishing guidance) fed directly into the final report's claims. This is the intended division of labor: deterministic lookups precomputed, agent turns spent on judgment. Across runs the agent exhibited path-level non-determinism at temperature 0 (different tool choices each run, same verdicts), which we consider acceptable for an evidence-gathering role but worth noting for reproducibility.

### D. Resilience

Live quota exhaustion converted the fallback router from a code path into a validated behavior: all brain calls 429'd, logged the model switch, and completed on flash-lite without pipeline failure. Additional graceful-degradation paths verified by construction or during incident testing: scorer failure (fusion reweights M+J), explainer failure (deterministic Python report), Jev unavailability (fusion reweights), and OTX 400s (clean "no intel" records).

### E. Limitations

The evaluation is a sanity check on two emails, not a benchmark; threshold, weights, and the confidence formula are design choices awaiting validation on a labeled batch. The three fused scores are not fully independent, since the Gemini scorer sees M and J in its evidence packet. Header score does not itself enter fusion (it conditions Jev and the agent). Finally, external intel was uninformative for the novel fake-TLD phish (zero OTX pulses), confirming that for fresh infrastructure the deterministic and LLM layers do the heavy lifting.

## VI. CONCLUSION AND FUTURE WORK

This project demonstrates that a phishing detector can be simultaneously budget-bounded, quota-resilient, and evidence-accountable: correct verdicts with large margins on both test cases, at most four Gemini calls and roughly two minutes per suspicious email, every claim traceable to a header check, a model score, or a fetched web result. The architecture's core lesson generalizes: in agentic security pipelines, give deterministic work to deterministic code, cap and prefeed the agent, and treat model quotas as first-class system constraints.

Future work: (1) a labeled batch evaluation (20-50 emails) to tune the fusion weights and decision threshold and to quantify brain-model substitution effects; (2) calibration of the confidence indicator against observed accuracy; (3) ML-score-gated investigation routing, skipping external search for clearly benign mail once the false-negative impact is measured; (4) adversarial robustness testing of the report layer (e.g., prompt injection embedded in email body, an attack class documented for LLM email detectors [12]); and (5) evaluating the full pipeline on public corpora such as SpamAssassin and CEAS'08 for comparability with prior work [5].

## REFERENCES

[1] S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, and Y. Cao, "ReAct: Synergizing Reasoning and Acting in Language Models," in *Proc. Int. Conf. on Learning Representations (ICLR)*, 2023. arXiv:2210.03629.

[2] W. Li, S. Manickam, Y.-W. Chong, and S. Karuppayah, "PhishDebate: An LLM-Based Multi-Agent Framework for Phishing Website Detection," in *Proc. IEEE Int. Conf. on Big Data (BigData)*, Macau, China, 2025, pp. 6606-6615, doi: 10.1109/BigData66926.2025.11401440.

[3] C. Lee, "Enhancing Phishing Email Identification with Large Language Models," arXiv:2502.04759, 2025.

[4] H. Patel, U. Rehman, and F. Iqbal, "Evaluating the Efficacy of Large Language Models in Identifying Phishing Attempts," arXiv:2404.15485, 2024.

[5] Z. Lin, Z. Liu, and H. Fan, "Improving Phishing Email Detection Performance of Small Large Language Models," arXiv:2505.00034, 2025.

[6] D. Sahoo, C. Liu, and S. C. H. Hoi, "Malicious URL Detection using Machine Learning: A Survey," arXiv:1701.07179, 2017.

[7] J. Hazell, "Spear Phishing With Large Language Models," arXiv:2305.06972, 2023.

[8] M. Bethany, A. Galiopoulos, E. Bethany, M. B. Karkevandi, N. Beebe, N. Vishwamitra, and P. Najafirad, "Lateral Phishing With Large Language Models: A Large Organization Comparative Study," *IEEE Access*, vol. 13, pp. 60684-60701, 2025, doi: 10.1109/ACCESS.2025.3555500.

[9] S. Kitterman, "Sender Policy Framework (SPF) for Authorizing Use of Domains in Email," RFC 7208, Apr. 2014.

[10] M. Kucherawy, Ed., "DomainKeys Identified Mail (DKIM) Signatures," RFC 6376, Sep. 2011.

[11] M. Kucherawy, Ed., "Domain-based Message Authentication, Reporting, and Conformance (DMARC)," RFC 7489, Mar. 2015.

[12] N. Hasan, P. BusiReddyGari, H. Zhao, Y. Ren, J. Xu, and S. Zhang, "Phishing Email Detection Using Large Language Models," arXiv:2512.10104, 2025.

[13] F. Pedregosa et al., "Scikit-learn: Machine Learning in Python," *Journal of Machine Learning Research*, vol. 12, pp. 2825-2830, 2011.

[14] LangChain, "LangGraph: Build Stateful, Multi-Actor Applications," 2024. [Online]. Available: https://langchain-ai.github.io/langgraph/

[15] Google, "Gemini API Documentation: Rate Limits and Thinking Models." [Online]. Available: https://ai.google.dev/gemini-api/docs/rate-limits

[16] AlienVault, "Open Threat Exchange (OTX) API." [Online]. Available: https://otx.alienvault.com/api

[17] Tavily, "Tavily Search API for LLMs." [Online]. Available: https://tavily.com

[18] OpenRouter, "Decisions API (alpha)." [Online]. Available: https://openrouter.ai
