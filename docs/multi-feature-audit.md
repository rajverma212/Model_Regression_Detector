# Multi-Feature Onboarding Audit

> **Status:** Analysis only — **no code modified, nothing implemented.** This audit
> assesses how much work it takes to evaluate a *new* AI feature on MRDS, and where
> email-classifier assumptions are baked in.
> **Sources of truth:** code under `src/mrds/`, [architecture.md](architecture.md),
> [current-system-analysis.md](current-system-analysis.md). **Date:** 2026-06-06.

---

## Executive summary

**The platform is genuinely feature-agnostic at its core.** The engine, metrics,
regression detector, thresholds, DB, reporting, alerting, CLI, and (after the recent
dashboard work) the dashboard contain **no email-specific logic** — only docstring
*examples*. Features plug in through three contracts: the `Feature`/`Scorer`
interfaces, a one-line entry in a factory registry, and versioned prompt/dataset files.

**Onboarding a classification-style feature is low effort** — roughly **4 code files +
2 content files + 1 registry line**, no changes to any core module. **Ticket Router**
and **Resume Screener** fit this mold.

**The one real generalization gap is the scoring paradigm.** Today all scorers are
**deterministic exact-match** (string equality, heuristics). The architecture
envisioned LLM-as-judge / semantic scoring behind a `ScorerAdapter`, but **that code
does not exist yet** (no `eval/adapters/`, no `judge.py`; the `--judge` flag only
records a boolean). A **RAG Evaluator**, whose correctness/faithfulness can't be
graded by string equality, is therefore the genuine stress test and the only one of
the three that needs **new evaluation infrastructure**.

| Target feature | Shape | Onboarding effort | Risk | New infra needed? |
|----------------|-------|:-----------------:|:----:|-------------------|
| **Ticket Router** | text → category | **Low** (mirror email classifier) | Low | No |
| **Resume Screener** | text(s) → decision + score | **Low–Medium** | Low–Med | No (maybe numeric scorer) |
| **RAG Evaluator** | question(+context) → free-text answer | **High** | Med–High | **Yes — judge/semantic scoring** |

---

## Part 1 — What is email-classifier-specific?

Three tiers, by how coupled they actually are.

### Tier A — Required per feature (by design; this is the extension surface)
These exist *because* a feature exists; every new feature gets its own equivalents.

| Path | Role |
|------|------|
| [features/email_classifier/schema.py](../src/mrds/features/email_classifier/schema.py) | Pydantic input/output models (`EmailClassificationInput/Output`, `EmailCategory`). |
| [features/email_classifier/feature.py](../src/mrds/features/email_classifier/feature.py) | `Feature` impl: builds messages, calls the LLM, returns structured output. |
| [features/email_classifier/scorers.py](../src/mrds/features/email_classifier/scorers.py) | `CategoryMatchScorer`, `SummaryQualityScorer` (deterministic). |
| [features/email_classifier/__init__.py](../src/mrds/features/email_classifier/__init__.py) | `build_feature()` factory + exports. |
| `prompts/email_classifier/v1.yaml` | Versioned prompt (system + few-shot). |
| `datasets/email_classifier/v1.json` | Versioned golden dataset (54 cases). |

**This tier is correct and expected** — it's the per-feature work, not coupling.

### Tier B — Real coupling outside the feature dir (must change to onboard / would block reuse)

| Path | Coupling | Notes |
|------|----------|-------|
| [features/__init__.py](../src/mrds/features/__init__.py) | `_FEATURE_FACTORIES = {"email_classifier": ...}` | **The intended seam** — adding a feature = one line here. Low effort, but it *is* a required edit. |
| [demo/client.py](../src/mrds/demo/client.py) | `DeterministicEmailClient` hardwires `category`/`summary`/`email_text`. | Email-only offline oracle. |
| [demo/generator.py](../src/mrds/demo/generator.py) | Assumes `email_text` keys, `category` segment, a `summary`. | Email-only narrative. |
| [demo/seed.py](../src/mrds/demo/seed.py) | Imports `EmailClassification*`, hardcodes `feature="email_classifier"`, `segment_field="category"`. | Email-only demo seeding. |
| [dashboard/help_text.py](../src/mrds/dashboard/help_text.py) | `FEATURE_INFO["email_classifier"]` business copy. | **Soft** coupling — keyed by feature, **falls back to the humanized slug** if absent. Optional. |

### Tier C — Docstring/example mentions only (no functional coupling)
[core/interfaces.py](../src/mrds/core/interfaces.py), [datasets/models.py](../src/mrds/datasets/models.py),
[prompts/models.py](../src/mrds/prompts/models.py) mention `email_classifier` purely as
examples in comments. **No change needed** to onboard a feature; optionally refresh
the prose.

> **Takeaway:** outside the feature's own directory, the only *mandatory* edit is one
> line in `features/__init__.py`. Everything else in Tier B is the **demo** (only
> relevant if you want seeded demo data for the new feature) and **optional** dashboard
> copy.

---

## Part 2 — System-wide assumptions

Implicit assumptions that hold today because the only feature is a deterministic
classifier. Each is a place a sufficiently different feature could strain.

1. **Scoring is deterministic and local.** Every scorer is pure string/heuristic
   comparison ([scoring.py](../src/mrds/evaluation/scoring.py), the email scorers). No
   LLM-as-judge or semantic similarity exists. **Binary `passed`** per scorer rolls up
   to a binary case pass. *Strained by:* free-text / open-ended outputs (RAG).
2. **A case "passes" iff all scorers pass.** Good for classification; awkward for
   graded/partial-credit tasks where "0.7 faithfulness" isn't pass/fail.
3. **Outputs are small structured records.** `output_model` is a Pydantic model with a
   few fields; `expected_output` is a full labeled record. *Strained by:* long free-text
   answers where the "expected" is a reference, not an exact target.
4. **Segmentation is one categorical field.** `segment_field` names a single
   expected-output key (e.g. `category`). Fully configurable per run
   ([config.py](../src/mrds/evaluation/config.py)), but assumes one categorical axis.
5. **Prompt shape = system prompt + few-shot chat examples**
   ([prompts/models.py](../src/mrds/prompts/models.py)). The *feature* controls message
   assembly, so this is flexible, but the YAML schema is fixed to that structure —
   no first-class slot for, say, retrieved context.
6. **One text input field is "the input."** The dashboard's `_primary_input_text`
   ([dashboard/data.py](../src/mrds/dashboard/data.py)) shows the input nicely only when
   there's exactly one string field; multi-field inputs (resume + JD; question +
   context) degrade to a raw dict dump (functional, less readable).
7. **Cost is token-count only.** `total_cost_usd` is always 0.0; latency/tokens are the
   cost proxies. Feature-neutral, but no per-feature pricing.
8. **The demo narrative is email-shaped.** Offline seeding only knows how to fabricate
   email classifications.

None of 1–8 are violated by another *classification* feature; #1–#3 and #6 are what a
**RAG** feature pushes on.

---

## Part 3 — Area-by-area analysis

For each architectural area: current implementation · generalization effort · risk ·
refactor recommendation. "Effort/Risk" describe *generalizing the area further* (most
need nothing).

### 3.1 Feature registry & registration — [features/__init__.py](../src/mrds/features/__init__.py)
- **Current:** static `_FEATURE_FACTORIES` dict; `register_all()` populates the global
  registry on import.
- **Generalization effort:** **None** to use; **trivial** per feature (one line).
- **Risk:** **Low.**
- **Recommendation:** Keep. (Optional, later: entry-point/auto-discovery so features
  self-register without editing this file — nice-to-have, not needed for 3 features.)

### 3.2 Feature interface & schemas — [core/interfaces.py](../src/mrds/core/interfaces.py), feature dirs
- **Current:** `Feature` ABC (`input_model`, `output_model`, `run`, `run_with_usage`,
  `scorers`) + `Scorer` protocol + `ScoreResult`. Fully generic.
- **Generalization effort:** **None** — the contract already supports arbitrary
  models/scorers.
- **Risk:** **Low.**
- **Recommendation:** Keep as-is. It is the clean seam the whole design rests on.

### 3.3 Scorers — [evaluation/scoring.py](../src/mrds/evaluation/scoring.py) + feature scorers
- **Current:** deterministic, pure, per-feature scorers; `score_case` ANDs `passed`.
  **No judge/semantic/adapter layer exists** (architecture's `eval/adapters/` and
  `judge.py` are unbuilt; `--judge` only sets a boolean).
- **Generalization effort:** **Low** for new deterministic scorers; **High** to add
  judge/semantic scoring (new infra).
- **Risk:** **Medium–High** — this is the platform's main generalization gap and the
  blocker for graded/free-text features.
- **Recommendation:** Build the envisioned **`ScorerAdapter`** seam (LLM-as-judge
  and/or embedding similarity) **before/with the RAG feature**. Keep it off by default
  in CI (cost), per the existing cost-aware principle. Consider a non-binary
  `passed` derivation (threshold on score) for graded tasks.

### 3.4 Prompts — [prompts/](../src/mrds/prompts/) + `prompts/<feature>/vN.yaml`
- **Current:** YAML → `LoadedPrompt` (system prompt + few-shot). Feature builds messages.
- **Generalization effort:** **Low** — works for any chat feature.
- **Risk:** **Low** (Medium *only* for RAG if you want a first-class "context" slot;
  otherwise the feature can inline context into messages).
- **Recommendation:** Keep. If RAG benefits, add an **optional** template field rather
  than changing the schema's required shape.

### 3.5 Datasets — [datasets/](../src/mrds/datasets/) + `datasets/<feature>/vN.json`
- **Current:** generic `DatasetDefinition[Input, Output]`; **`model_resolver`** maps a
  feature name → its `(input_model, output_model)` via the registry
  ([datasets/registry.py](../src/mrds/datasets/registry.py)). Onboarding a feature
  auto-resolves its dataset models with **zero** dataset-layer changes.
- **Generalization effort:** **None** to the layer; **per feature** you author a JSON file.
- **Risk:** **Low.**
- **Recommendation:** Keep. Excellent design.

### 3.6 Engine & metrics — [evaluation/engine.py](../src/mrds/evaluation/engine.py), [metrics.py](../src/mrds/evaluation/metrics.py)
- **Current:** iterates cases, applies feature scorers, aggregates pass/fail, per-scorer,
  per-segment, latency, tokens. `segment_field` is config-driven.
- **Generalization effort:** **None** for classification; **Low** to support graded
  metrics (mean-score-centric rollups already exist via `ScorerStats.mean_score`).
- **Risk:** **Low** (Medium if "pass/fail" must become "graded" for RAG).
- **Recommendation:** Keep. When judge scoring lands, ensure mean-score metrics are
  first-class in rollups (they already are) and consider a configurable pass threshold.

### 3.7 Regression detector & thresholds — [regression/](../src/mrds/regression/)
- **Current:** flattens *any* metrics (`pass_rate`, `scorer.*`, `segment.*`, latency,
  tokens) and compares dynamically; thresholds per metric *kind* with per-metric
  overrides.
- **Generalization effort:** **None** — metric names are discovered, not hardcoded.
- **Risk:** **Low.**
- **Recommendation:** Keep. Per-feature threshold overrides already supported via
  `ThresholdConfig.per_metric`.

### 3.8 DB / persistence — [db/](../src/mrds/db/)
- **Current:** feature identified by name; structured payloads stored as JSON; one
  schema for all features.
- **Generalization effort:** **None.**
- **Risk:** **Low.**
- **Recommendation:** Keep. No per-feature schema; nothing to change.

### 3.9 Reporting & alerting — [reporting/](../src/mrds/reporting/), [alerting/](../src/mrds/alerting/)
- **Current:** iterate scorers/segments/metrics dynamically; template guards on
  `segment_field` presence.
- **Generalization effort:** **None.**
- **Risk:** **Low.**
- **Recommendation:** Keep.

### 3.10 Dashboard — [dashboard/](../src/mrds/dashboard/)
- **Current:** feature-agnostic after recent work — `segment_field` derived per run,
  metric names humanized generically, `FEATURE_INFO` falls back to the slug. Two soft
  spots: (a) the single-text-input heuristic (`_primary_input_text`); (b) `FEATURE_INFO`
  copy only exists for email.
- **Generalization effort:** **None** to function; **Low** to improve multi-field
  input display and to add per-feature copy.
- **Risk:** **Low.**
- **Recommendation:** Keep. Optionally extend `_primary_input_text` to render
  multi-field inputs as a small key/value block, and add `FEATURE_INFO` entries per
  feature (copy only).

### 3.11 Demo seeding — [demo/](../src/mrds/demo/)
- **Current:** email-only offline oracle + narrative.
- **Generalization effort:** **Medium** per feature (a deterministic client + run specs),
  **or** skip and run the real feature against a small dataset.
- **Risk:** **Low** (isolated; nothing depends on demo except the hosted demo dashboard).
- **Recommendation:** Don't generalize preemptively. Either author a per-feature demo
  client when a hosted demo is wanted, or extract a tiny `DeterministicClient`
  protocol later if 2+ features need offline demos.

### 3.12 CLI — [cli/](../src/mrds/cli/)
- **Current:** `--feature`, `--prompt-version`, `--dataset-version`, `--segment-field`,
  `--judge`, `--max-cases` — all generic.
- **Generalization effort:** **None.**
- **Risk:** **Low.**
- **Recommendation:** Keep. A new feature is usable from the CLI the moment it's
  registered.

---

## Part 4 — Onboarding the three target features

### 4.1 Ticket Router  (text → routing category, e.g. team/queue + priority)
- **Shape:** identical to email classifier (single text input, categorical output).
- **What changes:** new `features/ticket_router/` (`schema.py` with input
  `{ticket_text}` and output `{team, priority?}`; `feature.py` mirroring the email one;
  `scorers.py` with a team-match scorer, optional priority-match); one line in
  `features/__init__.py`; `prompts/ticket_router/v1.yaml`; `datasets/ticket_router/v1.json`;
  optional `FEATURE_INFO` copy. Evaluate with `--segment-field team`.
- **Generalization effort:** **Low** (a near-copy of the email feature).
- **Risk:** **Low.**
- **Refactor recommendation:** None required. This feature proves the
  classification path generalizes with zero core changes.

### 4.2 Resume Screener  (resume [+ job description] → decision + fit score)
- **Shape:** classification-plus — a categorical decision (advance/reject) and likely a
  **numeric fit score**; possibly **two input fields** (resume + JD).
- **What changes:** new `features/resume_screener/`; scorers = decision exact-match +
  (new) a **numeric-proximity scorer** for the fit score (still deterministic — compare
  to expected within tolerance); registry line; prompt + dataset; optional copy.
  Evaluate with `--segment-field decision` (or role).
- **Generalization effort:** **Low–Medium.** The numeric-proximity scorer is new but
  deterministic and small. Two input fields mean the dashboard's input preview falls
  back to a dict dump (functional).
- **Risk:** **Low–Medium.** Watch: (a) binary pass/fail vs a graded fit score —
  decide whether "passed" keys off the decision only or also a score threshold;
  (b) PII in resumes (handling/retention) — a policy concern, not a code blocker.
- **Refactor recommendation:** Add a reusable **numeric-tolerance scorer** (could live
  in a shared scorers util if a second feature needs it). Optionally improve the
  dashboard multi-field input rendering (3.10). No core changes.

### 4.3 RAG Evaluator  (question [+ retrieved context] → free-text answer)
- **Shape:** fundamentally different — **open-ended free-text output** graded on
  faithfulness / answer-relevance / correctness against a reference, not exact match.
- **What changes:** new `features/rag_qa/` (input `{question, context?}`, output
  `{answer}`); **new scoring** — this is the crux: deterministic string equality won't
  work, so you need **judge/semantic scorers** (the unbuilt `ScorerAdapter` /
  LLM-as-judge path, or embedding similarity, optionally DeepEval/RAGAS *behind the
  adapter* per the architecture). Likely a **non-binary pass** (threshold on a graded
  score). Prompt may want a context slot; dataset cases carry question + reference
  answer (+ context). Registry line; prompt + dataset; optional copy.
- **Generalization effort:** **High** — not because of feature wiring (that's the same
  pattern) but because the **scoring infrastructure doesn't exist yet** and must be
  built generically (3.3).
- **Risk:** **Medium–High.** Judge scoring is **non-deterministic and costs money/network**
  — it stresses the "tests always mock OpenAI," "deterministic & reproducible," and
  "cost-aware / off-by-default-in-CI" principles. Graded (non-binary) outcomes also
  touch how `passed`, pass-rate, and the gate behave.
- **Refactor recommendation:** **Build the `ScorerAdapter`/judge seam first** (off by
  default in CI; deterministic stub in tests; cache/seed for reproducibility), and
  introduce a **configurable pass threshold** so graded scores roll into the existing
  pass/fail + regression machinery without changing the detector. Treat RAG as the
  driver for that one piece of infrastructure — everything else reuses the existing
  generic stack.

---

## Part 5 — Prioritized recommendations

1. **Adopt the "feature = 4 files + 2 content files + 1 registry line" recipe** and
   document it (a short `docs/adding-a-feature.md` / README section). Ticket Router and
   Resume Screener need nothing more.
2. **Build the `ScorerAdapter` / judge-scoring seam** (the architecture's intended,
   currently-missing piece) — the single unlock for RAG and any graded feature. Keep it
   off by default in CI, deterministic-stubbed in tests, and cache results for
   reproducibility. Add a **configurable pass threshold** so graded scores feed the
   existing pass/fail + regression gate unchanged.
3. **Small dashboard polish (optional, Low):** render multi-field inputs as a key/value
   block in `_primary_input_text`'s fallback; add `FEATURE_INFO` copy per feature.
4. **Don't pre-generalize the demo.** Author a per-feature deterministic client only
   when a hosted offline demo is wanted; extract a `DeterministicClient` protocol if
   2+ features need it.
5. **Leave the core alone.** Engine, metrics, regression, thresholds, DB, reporting,
   alerting, CLI, and prompt/dataset layers require **no changes** to onboard any of
   the three features — verified above. Resist adding feature-specific branches there.

### Bottom line
MRDS's feature-agnostic design holds up: two of the three target features are
near-mechanical to onboard with **zero core changes**. The only architectural
investment any of them requires is the **judge/semantic scoring adapter** for RAG —
which the original architecture already anticipated but hasn't built yet.
