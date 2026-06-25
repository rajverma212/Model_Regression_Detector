# Architecture — Model Regression Detection System

> **Status:** Blueprint (pre-implementation). This document is the source of truth for system design. No implementation code exists yet.

---

## 1. Overview & Goals

The **Model Regression Detection System (MRDS)** is an **AI Evaluation Platform** and **deployment-safety system**. It is *not* an email-classification application — it is the infrastructure that continuously verifies the quality of LLM-powered features and **blocks deployments when quality degrades**.

It is designed to resemble internal tooling built by **AI Platform / Evaluation / ML Infrastructure** teams.

### What it does

- Runs LLM-powered features against **versioned golden datasets** whenever prompts, models, or datasets change.
- Computes objective **metrics** (accuracy, precision/recall/F1, latency, cost) per run.
- Compares each **candidate run** against a known-good **baseline** and detects **regressions**.
- Generates **HTML/Markdown reports** and persists everything to a **SQLite system of record**.
- Sends **Slack alerts** on regressions and baseline promotions.
- **Gates CI/CD**: a critical regression fails the build and **blocks the merge**.
- Surfaces **historical trends** and **baseline management** through a **Streamlit dashboard**.

### The first feature under test

**Customer Support Email Classification**

```
Input:  raw customer email text
Output: { "category": "billing | technical | account | general",
          "summary": "one sentence summary" }
```

The email classifier is **only the first feature**. The platform is built feature-agnostic so additional features (`rag_qa`, `chatbot`, `ticket_router`, …) plug in without touching the evaluation core.

### Design goals

| Goal | Meaning |
|------|---------|
| **Feature-agnostic** | The evaluation engine knows nothing about any specific feature. Features register themselves. |
| **CLI-first** | One CLI drives everything, identical locally and in CI. |
| **Fail-closed** | When quality drops past a critical threshold, the system blocks deployment by default. |
| **Deterministic & reproducible** | Runs are pinned to prompt versions, dataset versions, and model identifiers. |
| **Cost-aware** | Expensive LLM-as-judge scoring is optional and off by default in CI. |
| **System of record** | SQLite stores every run, result, regression, and baseline for auditability. |
| **Extensible integrations** | DeepEval / RAGAS are optional, hidden behind adapters. |

---

## 2. Repository Structure

```
model-regression-detector/
│
├── README.md
├── CLAUDE.md                       # Persistent project context for Claude Code
├── pyproject.toml                  # Project metadata, deps, Ruff + pytest config
├── ruff.toml                       # (or Ruff config inside pyproject.toml)
├── .env.example                    # Documents required environment variables
├── .gitignore
├── Dockerfile
├── docker-compose.yml
│
├── docs/
│   ├── architecture.md             # THIS FILE — source of truth
│   └── roadmap.md                  # Sprint-by-sprint implementation plan
│
├── config/
│   ├── settings.yaml               # Layered defaults (non-secret)
│   └── thresholds.yaml             # Regression thresholds per feature/metric
│
├── prompts/                        # Versioned prompt store (YAML, content-hashed)
│   └── email_classifier/
│       ├── v1.yaml
│       └── v2.yaml
│
├── datasets/                       # Versioned golden datasets (JSON)
│   └── email_classifier/
│       ├── v1.json
│       └── v1.meta.json            # schema + content hash + provenance
│
├── reports/                        # Generated run reports (git-ignored output)
│   └── .gitkeep
│
├── data/
│   └── eval.db                     # SQLite system of record (git-ignored)
│
├── web/                            # Next.js frontend — the "Evaluation OS" product UI
│   ├── app/                        # App Router (Mission Control, feature workspace, create)
│   ├── components/                 # Design-system primitives + views
│   └── lib/api.ts                  # Typed client mirroring src/mrds/api/serializers.py
│
├── src/
│   └── mrds/                       # Top-level package
│       │
│       ├── __init__.py
│       │
│       ├── cli/                    # CLI-FIRST entrypoint (local == CI)
│       │   ├── __init__.py
│       │   ├── main.py             # CLI app / command dispatch
│       │   └── commands/
│       │       ├── evaluate.py        # `evaluate`
│       │       ├── compare.py         # `compare`
│       │       ├── report.py          # `report`
│       │       └── promote_baseline.py# `promote-baseline`
│       │
│       ├── api/                    # HTTP API (FastAPI) — backs the web frontend
│       │   ├── app.py             # Feature-agnostic routes (per-request DB session)
│       │   ├── runtime.py         # ApiSession: one SQLite connection per request
│       │   └── serializers.py     # JSON wire contract (verdicts, deltas, explained cases)
│       │
│       ├── core/                   # Shared primitives, feature-agnostic
│       │   ├── __init__.py
│       │   ├── interfaces.py       # Feature, Scorer, Adapter protocols
│       │   ├── registry.py         # Feature registry
│       │   ├── models.py           # Pydantic v2 domain models (Run, TestResult, …)
│       │   ├── hashing.py          # Content-hash helpers (prompt/dataset identity)
│       │   └── ids.py              # Run / correlation ID generation
│       │
│       ├── features/               # Pluggable features (the only feature-specific code)
│       │   ├── __init__.py         # Imports + registers all features
│       │   ├── email_classifier/
│       │   │   ├── __init__.py
│       │   │   ├── feature.py       # Implements Feature interface
│       │   │   ├── schema.py        # Input/Output Pydantic models
│       │   │   └── scorers.py       # Feature-specific scoring
│       │   ├── rag_qa/             # FUTURE (placeholder)
│       │   ├── chatbot/            # FUTURE (placeholder)
│       │   └── ticket_router/      # FUTURE (placeholder)
│       │
│       ├── prompts/                # Prompt versioning runtime
│       │   ├── __init__.py
│       │   ├── loader.py           # Load + hash YAML prompt versions
│       │   └── registry.py         # Resolve feature -> prompt version
│       │
│       ├── datasets/               # Dataset versioning runtime
│       │   ├── __init__.py
│       │   └── loader.py           # Load + validate + hash JSON golden sets
│       │
│       ├── eval/                   # CUSTOM evaluation engine
│       │   ├── __init__.py
│       │   ├── engine.py           # Feature-agnostic run loop
│       │   ├── metrics.py          # Accuracy, P/R/F1, latency, cost aggregation
│       │   ├── judge.py            # Optional LLM-as-judge (configurable, off in CI)
│       │   └── adapters/           # Optional 3rd-party integrations behind interfaces
│       │       ├── __init__.py
│       │       ├── base.py         # ScorerAdapter protocol
│       │       ├── deepeval.py     # FUTURE adapter (optional dependency)
│       │       └── ragas.py        # FUTURE adapter (optional dependency)
│       │
│       ├── regression/             # Regression detection
│       │   ├── __init__.py
│       │   ├── detector.py         # Candidate vs baseline comparison
│       │   └── thresholds.py       # Threshold model + critical vs warning
│       │
│       ├── reporting/              # Report generation
│       │   ├── __init__.py
│       │   ├── builder.py          # Assemble report context from a run
│       │   └── templates/          # Jinja2 templates
│       │       ├── report.html.j2
│       │       └── report.md.j2
│       │
│       ├── alerting/               # Slack alerting
│       │   ├── __init__.py
│       │   ├── slack.py            # Webhook client
│       │   └── messages.py         # Message/Block Kit templates
│       │
│       ├── db/                     # SQLite system of record
│       │   ├── __init__.py
│       │   ├── connection.py       # Connection + pragmas
│       │   ├── schema.sql          # DDL (tables, indexes)
│       │   ├── migrations/         # Versioned schema migrations
│       │   └── repository.py       # Typed CRUD over tables
│       │
│       ├── config/                 # Configuration management
│       │   ├── __init__.py
│       │   └── settings.py         # Pydantic Settings (env + YAML)
│       │
│       ├── observability/
│       │   ├── __init__.py
│       │   └── logging.py          # Structured logging setup
│       │
│       └── dashboard/              # Streamlit app
│           ├── __init__.py
│           ├── app.py              # Entry page
│           └── pages/
│               ├── 1_runs.py
│               ├── 2_trends.py
│               ├── 3_regressions.py
│               └── 4_baselines.py
│
├── tests/
│   ├── conftest.py                 # Fixtures, mocked Anthropic client
│   ├── unit/
│   ├── integration/
│   └── fixtures/                   # Sample prompts, datasets, recorded responses
│
└── .github/
    └── workflows/
        ├── eval.yml                # Regression gate on PRs
        └── ci.yml                  # Lint + unit tests
```

---

## 3. Module Responsibilities

| Module | Responsibility | Feature-aware? |
|--------|----------------|----------------|
| `cli/` | Single entrypoint exposing `evaluate`, `compare`, `report`, `promote-baseline`. Used identically locally and in CI. Translates outcomes into exit codes for gating. | No |
| `core/interfaces.py` | Defines the `Feature`, `Scorer`, and `ScorerAdapter` protocols every feature/integration must satisfy. | No |
| `core/registry.py` | Holds the mapping of feature name → `Feature` instance. The engine iterates this. | No |
| `core/models.py` | Pydantic v2 domain models shared across the system (`Run`, `TestResult`, `Regression`, `Baseline`, `PromptVersion`, `DatasetVersion`, metric models). | No |
| `features/<name>/` | The **only** feature-specific code: input/output schemas, the call to the model, and feature-specific scorers. | **Yes** |
| `prompts/` (runtime) | Loads YAML prompt versions, computes content hashes, resolves the active version for a feature. | No |
| `datasets/` (runtime) | Loads + validates JSON golden datasets, computes content hashes, exposes test cases. | No |
| `eval/engine.py` | The **custom evaluation engine**: feature-agnostic loop that runs each test case through a feature, collects outputs, invokes scorers, aggregates metrics, and persists a `Run`. | No |
| `eval/metrics.py` | Pure metric computation (accuracy, per-class precision/recall/F1, latency percentiles, token/cost totals). | No |
| `eval/judge.py` | Optional LLM-as-judge scoring. Configurable; disabled by default in CI for cost control. | No |
| `eval/adapters/` | Optional integrations (DeepEval, RAGAS) behind the `ScorerAdapter` interface so the core never imports them directly. | No |
| `regression/detector.py` | Compares a candidate run's metrics to a baseline's, applies thresholds, emits `Regression` records classified critical/warning. | No |
| `reporting/` | Renders run + comparison data into HTML/Markdown via Jinja2; writes artifacts to `reports/`. | No |
| `alerting/` | Posts Slack messages on regressions and baseline promotions via webhook. | No |
| `db/` | Owns the SQLite schema and typed repository access. The single system of record. | No |
| `config/settings.py` | Loads layered config (YAML defaults + env vars/secrets) into a validated Pydantic `Settings` object. | No |
| `observability/logging.py` | Structured logging with run correlation IDs. | No |
| `dashboard/` | Streamlit app reading SQLite for historical runs, trends, regression inspection, and baseline management. | No |

**Key invariant:** only `features/` contains feature-specific knowledge. Everything else is generic platform machinery.

---

## 4. Feature Registry Architecture

Features are pluggable. Each feature is a self-contained package under `features/<name>/` that implements the `Feature` interface defined in `core/interfaces.py`.

### The `Feature` contract (conceptual)

A `Feature` exposes:

- `name` — unique identifier (e.g. `"email_classifier"`).
- `input_model` / `output_model` — Pydantic v2 models describing the I/O schema.
- `prompt_ref` — which prompt family/version the feature uses.
- `dataset_ref` — which golden dataset family the feature evaluates against.
- `run(input)` — produce a structured output by calling the model (the only place that talks to the Anthropic API).
- `scorers()` — the list of `Scorer`s that grade an output against the expected value.

### Registration

```
features/__init__.py  ──imports──►  email_classifier, rag_qa, chatbot, ticket_router
        │
        └── each module calls registry.register(Feature(...))
                                   │
                              core/registry.py  (name -> Feature)
                                   │
                              eval/engine.py iterates registry
```

### Why the engine stays feature-agnostic

The engine never references `email_classifier`. It asks the registry for a feature by name, pulls the feature's dataset and scorers, runs each case through `feature.run()`, and grades with `feature.scorers()`. **Adding a new feature requires zero changes to `eval/`, `regression/`, `reporting/`, `alerting/`, `db/`, or `cli/`.**

### Adding a new feature (checklist)

1. Create `features/<name>/` with `schema.py`, `feature.py`, `scorers.py`.
2. Add a prompt version under `prompts/<name>/v1.yaml`.
3. Add a golden dataset under `datasets/<name>/v1.json` (+ `.meta.json`).
4. Register the feature in `features/__init__.py`.
5. Add regression thresholds in `config/thresholds.yaml`.

No core code changes.

---

## 5. Custom Evaluation Engine

The platform is built around a **custom evaluation engine** (`eval/engine.py`). DeepEval and RAGAS are **optional future integrations**, included only behind adapter interfaces.

### Engine flow (single feature)

```
engine.run(feature_name)
   │
   ├─ resolve Feature from registry
   ├─ resolve active PromptVersion  (prompts/registry.py)  → content hash
   ├─ load DatasetVersion           (datasets/loader.py)   → content hash
   ├─ open Run record               (db/repository.py)     → run_id, correlation_id
   │
   ├─ for each test_case in dataset:
   │      output      = feature.run(test_case.input)        # Anthropic call, timed
   │      for scorer in feature.scorers():
   │          score   = scorer.score(output, test_case.expected)
   │      persist TestResult(run_id, case_id, scores, latency, tokens, cost)
   │
   ├─ metrics = eval/metrics.aggregate(test_results)
   ├─ persist metrics onto Run, close Run (status=completed)
   └─ return Run
```

### Scorer model & adapter boundary

```
core/interfaces.py
   Scorer        (score(output, expected) -> ScoreResult)
   ScorerAdapter (wraps an external lib, exposes the Scorer interface)

eval/adapters/base.py     ── ScorerAdapter protocol
eval/adapters/deepeval.py ── wraps DeepEval metrics  (optional dep, FUTURE)
eval/adapters/ragas.py    ── wraps RAGAS metrics      (optional dep, FUTURE)
```

The core engine depends only on the `Scorer` interface. Optional libraries are imported **inside** their adapter modules, so the platform runs with zero third-party eval dependencies installed. Enabling an adapter is a config + optional-dependency concern, never a core change.

### Built-in scorers (no external deps)

- **Exact/categorical match** — for the `category` field.
- **Classification metrics** — accuracy, per-class precision/recall/F1 (aggregated in `metrics.py`).
- **Heuristic summary checks** — non-empty, length bounds, single-sentence shape.
- **Optional LLM-as-judge** (`judge.py`) — semantic summary quality; configurable, off by default in CI.

---

## 6. Data Flow Diagrams

### (a) End-to-end evaluation run (`evaluate`)

```
 prompts/ (YAML)     datasets/ (JSON)        config (YAML + env)
      │                    │                       │
      ▼                    ▼                       ▼
 PromptVersion        DatasetVersion           Settings
   (hash)               (hash)                    │
      └──────────┬─────────┘                      │
                 ▼                                 ▼
            ┌───────────────────────────────────────────┐
            │            eval/engine.py                  │
            │  per case: feature.run() ─► scorers ─►     │
            │            metrics.aggregate()             │
            └───────────────────────────────────────────┘
                 │                         │
                 ▼                         ▼
        db: runs, test_results     reports/ (Jinja2)
```

### (b) CI-triggered regression gate

```
 PR changes prompts/ | datasets/ | model config
                 │
                 ▼
   GitHub Actions (eval.yml)  ── runs the SAME CLI ──┐
                 │                                    │
                 ▼                                    ▼
        cli: evaluate  ─────────────►  cli: compare (candidate vs baseline)
                                              │
                          ┌───────────────────┼────────────────────┐
                          ▼                   ▼                     ▼
                  no regression       warning regression     CRITICAL regression
                          │                   │                     │
                   exit 0 (pass)      exit 0 + Slack warn      exit 1 (BLOCK MERGE)
                          │                   │                     │
                          └─────────► upload report artifact ◄──────┘
                                              │
                                              ▼
                                        Slack notify
```

### (c) Baseline promotion workflow

```
        ┌──────────────┐
        │ Candidate Run│   (cli: evaluate)
        └──────┬───────┘
               ▼
        ┌──────────────────────────┐
        │ Compare Against Baseline │  (cli: compare → regression/detector.py)
        └──────┬───────────────────┘
               ▼
        ┌──────────────────────────┐
        │   Pass / Fail Decision   │  (thresholds: critical vs warning)
        └──────┬───────────────────┘
        pass   │            fail
   ┌───────────┘             └─────────────► block / alert, do NOT promote
   ▼
┌───────────────────────────┐
│ Optional Baseline Promotion│ (cli: promote-baseline → baselines table)
│  - manual command, or      │
│  - auto on green main      │
└───────────────────────────┘
```

### (d) Alerting & reporting fan-out

```
            completed Run + comparison
                       │
        ┌──────────────┼───────────────┐
        ▼              ▼                ▼
  reporting/builder  alerting/slack   db/repository
   (HTML + MD)        (webhook)        (persist regressions,
        │                │              update baseline)
        ▼                ▼
   reports/*.html   Slack channel
   reports/*.md     (CI artifact link)
```

---

## 7. SQLite Schema (System of Record)

A single SQLite database (`data/eval.db`) is the **system of record**. WAL mode and foreign-key enforcement are enabled via connection pragmas. All writes go through `db/repository.py`.

### Tables

**`runs`** — one row per evaluation run.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | autoincrement |
| `run_uuid` | TEXT UNIQUE | correlation ID used in logs/reports |
| `feature_name` | TEXT | e.g. `email_classifier` |
| `prompt_version_id` | INTEGER FK → prompt_versions.id | |
| `dataset_version_id` | INTEGER FK → dataset_versions.id | |
| `model` | TEXT | model identifier used |
| `judge_enabled` | INTEGER (bool) | whether LLM-as-judge ran |
| `status` | TEXT | `running` / `completed` / `failed` |
| `git_sha` | TEXT | commit under test (CI) |
| `triggered_by` | TEXT | `local` / `ci` / `manual` |
| `started_at` | TEXT (ISO8601) | |
| `finished_at` | TEXT (ISO8601) | |
| `metrics_json` | TEXT (JSON) | aggregated metrics snapshot |
| `total_tokens` | INTEGER | cost tracking |
| `total_cost_usd` | REAL | cost tracking |

**`test_results`** — one row per (run, test case).

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `run_id` | INTEGER FK → runs.id | ON DELETE CASCADE |
| `case_id` | TEXT | dataset case identifier |
| `input_ref` | TEXT | reference/hash of input |
| `expected_json` | TEXT (JSON) | expected output |
| `actual_json` | TEXT (JSON) | model output |
| `passed` | INTEGER (bool) | per-case pass/fail |
| `scores_json` | TEXT (JSON) | per-scorer scores |
| `latency_ms` | INTEGER | |
| `tokens` | INTEGER | |
| `cost_usd` | REAL | |
| `error` | TEXT NULL | populated if the case errored |

**`baselines`** — the promoted known-good run per feature.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `feature_name` | TEXT | |
| `run_id` | INTEGER FK → runs.id | the promoted run |
| `is_active` | INTEGER (bool) | one active baseline per feature |
| `promoted_by` | TEXT | user / CI actor |
| `promoted_at` | TEXT (ISO8601) | |
| `note` | TEXT | promotion reason |

**`regressions`** — detected regressions linking a candidate to a baseline.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `run_id` | INTEGER FK → runs.id | candidate run |
| `baseline_run_id` | INTEGER FK → runs.id | baseline compared against |
| `metric` | TEXT | e.g. `accuracy`, `f1.billing` |
| `baseline_value` | REAL | |
| `candidate_value` | REAL | |
| `delta` | REAL | candidate − baseline |
| `severity` | TEXT | `warning` / `critical` |
| `detected_at` | TEXT (ISO8601) | |

**`prompt_versions`** — registry of prompt versions.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `feature_name` | TEXT | |
| `version` | TEXT | e.g. `v2` |
| `content_hash` | TEXT UNIQUE | identity = hash of prompt content |
| `path` | TEXT | source YAML path |
| `created_at` | TEXT (ISO8601) | |

**`dataset_versions`** — registry of dataset versions.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `feature_name` | TEXT | |
| `version` | TEXT | e.g. `v1` |
| `content_hash` | TEXT UNIQUE | identity = hash of dataset content |
| `path` | TEXT | source JSON path |
| `case_count` | INTEGER | number of golden cases |
| `created_at` | TEXT (ISO8601) | |

### Relationships

```
prompt_versions ─┐
                 ├──< runs >──┬──< test_results
dataset_versions─┘            │
                              ├──< regressions >── baselines
baselines >── runs (promoted run_id)
regressions >── runs (candidate run_id) and runs (baseline_run_id)
```

- A **run** references exactly one `prompt_versions` row and one `dataset_versions` row → full reproducibility.
- A **run** has many **test_results** (1:N, cascade delete).
- A **baseline** points at one promoted **run**; at most one `is_active` baseline per feature.
- A **regression** links a candidate **run** to a baseline **run** and records the offending **metric** and severity.
- `prompt_versions` and `dataset_versions` are append-only registries keyed by `content_hash`, so identical content is never duplicated.

---

## 8. Prompt Versioning Design

Prompts live as **YAML files** under `prompts/<feature>/<version>.yaml`. Identity is the **content hash**, not the filename — renaming a file does not change its identity, but editing content does.

### YAML shape (illustrative, not code)

```yaml
feature: email_classifier
version: v2
model_defaults:
  model: claude-haiku-4-5
  temperature: 0
metadata:
  author: rajverma
  created: 2026-05-29
  changelog: "Tightened category definitions; added few-shot examples."
system: |
  You are a support email classifier...
user_template: |
  Classify the following email:
  {{ email_text }}
output_contract:
  category: ["billing", "technical", "account", "general"]
  summary: "one sentence"
```

### Versioning rules

- One file per version; never edit a released version in place — add `vN+1`.
- On load, `prompts/loader.py` computes a `content_hash` over the canonicalized content and upserts a `prompt_versions` row.
- `prompts/registry.py` resolves the **active** version for a feature (latest, or pinned via config).
- Every `runs` row stores the `prompt_version_id` so a run is always traceable to exact prompt content.
- A prompt change in a PR is what **triggers** the CI evaluation gate.

---

## 9. Dataset Versioning Design

Golden datasets are **JSON files** under `datasets/<feature>/<version>.json`, paired with a `<version>.meta.json` describing schema, hash, and provenance.

### Dataset shape (illustrative)

```json
{
  "feature": "email_classifier",
  "version": "v1",
  "cases": [
    {
      "id": "case-001",
      "input": { "email_text": "I was charged twice this month..." },
      "expected": { "category": "billing", "summary": "Customer was double-charged." }
    }
  ]
}
```

### Versioning rules

- Datasets are immutable per version; corrections create a new version.
- `datasets/loader.py` validates every case against the feature's `input_model`/`output_model`, computes a `content_hash`, and upserts a `dataset_versions` row (with `case_count`).
- Runs store `dataset_version_id`, so metrics are always tied to a known dataset.
- A **smoke subset** (small, fast) and a **full set** are supported for cost control (§16): CI smoke-tests on PRs and runs the full set on a schedule or on `main`.
- Dataset changes also trigger the CI evaluation gate.

---

## 10. Regression Detection Architecture

`regression/detector.py` compares a **candidate run** to the **active baseline** for the same feature.

### Algorithm

```
detect(candidate_run):
    baseline = repository.active_baseline(candidate_run.feature_name)
    if baseline is None:
        return NO_BASELINE            # first run for a feature; nothing to gate
    for metric, cand_value in candidate_run.metrics:
        base_value = baseline.metrics[metric]
        delta      = cand_value - base_value
        rule       = thresholds.for(feature, metric)
        if violates(delta, base_value, rule):
            record Regression(metric, base_value, cand_value, delta, severity)
    return regressions
```

### Thresholds (`config/thresholds.yaml`)

- Per feature and per metric.
- Support **absolute** drop (e.g. accuracy may not fall by more than 0.02) and **relative** drop (e.g. F1 may not fall by more than 3%).
- Each rule carries a **severity**: `warning` (alert only) or `critical` (block merge).
- Latency and cost can also have ceilings (e.g. p95 latency regression).

### Decision

- **No regression** → pass (exit 0).
- **Warning regression** → pass (exit 0) but Slack-notify and flag in report.
- **Critical regression** → **fail (exit 1)** → CI blocks the merge.

Baselines are **never** auto-overwritten by a worse run; promotion is explicit (§ workflow in 6c) via `promote-baseline`.

---

## 11. CLI Architecture (CLI-First)

`src/mrds/cli/` is the single entrypoint. The **same CLI runs locally and inside GitHub Actions** — CI simply invokes these commands so behavior is identical everywhere.

| Command | Purpose | Key inputs | Exit semantics |
|---------|---------|-----------|----------------|
| `evaluate` | Run a feature's dataset through the engine, persist a run. | `--feature`, `--dataset-version`, `--prompt-version`, `--judge/--no-judge`, `--smoke/--full` | 0 on completion; 1 on execution error |
| `compare` | Compare a run (default: latest) against the active baseline; detect regressions. | `--feature`, `--run`, `--baseline` | **0 if no critical regression; 1 if critical** (this is the gate) |
| `report` | Render HTML + Markdown report for a run/comparison into `reports/`. | `--run`, `--format` | 0 |
| `promote-baseline` | Promote a run to the active baseline for its feature. | `--feature`, `--run`, `--note` | 0 on success |

Common conventions: machine-readable output (JSON) available for CI parsing, structured logging with the run's correlation ID, and a global `--config` to point at a settings file. A typical CI sequence is `evaluate → compare → report`, with `compare`'s exit code driving the merge gate.

---

## 12. Reporting Architecture

`reporting/builder.py` assembles a report context from a run (and its baseline comparison) and renders it with **Jinja2** templates in `reporting/templates/`.

- **HTML report** (`report.html.j2`): summary metrics, per-class P/R/F1 table, regression table (with deltas, severity-colored), latency/cost, and per-case drilldown of failures.
- **Markdown report** (`report.md.j2`): same content, suitable for PR comments / artifact previews.
- Output written to `reports/<feature>/<run_uuid>.{html,md}`.
- In CI the report is uploaded as a build artifact; the Slack message links to it.
- Reports are **derived artifacts** (git-ignored); SQLite remains the source of truth.

---

## 13. Slack Alerting Architecture

`alerting/slack.py` posts to an incoming webhook (`SLACK_WEBHOOK_URL`); `alerting/messages.py` builds the payloads (Block Kit).

### Triggers

| Event | Message contents |
|-------|------------------|
| **Critical regression** | 🔴 feature, metric(s), baseline→candidate deltas, git SHA, link to report/CI run. Marked as merge-blocking. |
| **Warning regression** | 🟡 same shape, informational. |
| **Baseline promoted** | 🟢 feature, promoted run, who promoted, note. |

- Alerting is **best-effort**: a webhook failure logs an error but never changes the gate decision (the exit code from `compare` is authoritative).
- The webhook URL is a secret, injected via env/CI secrets — never committed.

---

## 14. Streamlit Dashboard Architecture

`dashboard/app.py` (multipage) reads directly from `data/eval.db` (read-only) — it never calls the model. Pages:

| Page | Purpose |
|------|---------|
| **Runs** | Browse historical runs with filters (feature, status, date, prompt/dataset version); open a run to see metrics and per-case results. |
| **Trends** | Time-series of accuracy/F1/latency/cost per feature across runs; baseline overlay. |
| **Regressions** | Inspect detected regressions, severity, deltas, and the candidate-vs-baseline diff. |
| **Baselines** | View current active baseline per feature and promotion history. |

The dashboard is a **read/inspection surface**; mutations (promotion, evaluation) happen through the CLI to keep one authoritative write path. (Baseline promotion *from* the dashboard, if added later, would call the same CLI/repository code path.)

> The Streamlit dashboard is now the **original prototype**. The primary product surface is
> the **Evaluation OS** web app (`web/`), backed by a thin FastAPI layer (`src/mrds/api/`).
> Both are feature-agnostic presentation layers over the same read-only data seam; the API
> additionally exposes guarded baseline promotion (via `BaselinePromoter`, same write path)
> and **end-to-end feature activation** (`POST /api/onboarding/activate`), which orchestrates
> the existing onboarding/activation/evaluation cores — `write_feature_bundle` →
> `activate_bundle` (install + register) → `run_first_evaluation` (unchanged engine → store)
> → `promote_baseline` — adding no new evaluation or persistence logic. It installs bundles
> under the writable `settings.platform_root` (which must equal the working directory) and
> needs `ANTHROPIC_API_KEY`; durable locally, demo-grade on the read-only serverless deployment.
> See **[web-frontend.md](web-frontend.md)** for the API contract, information architecture,
> and design system.

---

## 15. GitHub Actions Architecture

This is a **deployment-safety system**, so CI is central. Two workflows under `.github/workflows/`:

**`ci.yml`** — fast checks on every push/PR: Ruff lint + format check, pytest unit tests. No model calls.

**`eval.yml`** — the regression gate:

```
on:
  pull_request:
    paths: [ "prompts/**", "datasets/**", "config/**", "src/mrds/features/**" ]
  workflow_dispatch:
  schedule: [ nightly full run ]

jobs:
  regression-gate:
    steps:
      1. checkout + setup Python 3.11 + install deps
      2. restore eval.db / baselines (artifact or committed baseline metrics)
      3. detect changed prompts/datasets (path filter already scoped the trigger)
      4. mrds evaluate --feature ... --smoke      (PR) | --full (schedule/main)
      5. mrds compare  --feature ...              → exit code is the GATE
      6. mrds report   --run <id>                 → reports/*.html|md
      7. upload-artifact: reports/, run JSON
      8. notify Slack (regression or promotion)
      9. if compare exited non-zero (critical) → job fails → MERGE BLOCKED
```

- Secrets `ANTHROPIC_API_KEY` and `SLACK_WEBHOOK_URL` come from GitHub Actions secrets.
- PRs run the **smoke subset** for speed/cost; the **full dataset** runs nightly and on `main`.
- Optional auto-promotion: on a green run on `main`, run `promote-baseline` so the baseline tracks shipped quality.

---

## 16. Docker Architecture

A single image builds the platform; two entrypoints select behavior.

- **`Dockerfile`** — Python 3.11 slim base; install deps from `pyproject.toml`; copy `src/`, `config/`, `prompts/`, `datasets/`; non-root user. Default entrypoint = the `mrds` CLI.
- **`docker-compose.yml`** — two services:
  - `cli` — runs evaluations (`mrds evaluate/compare/report`), mounts `data/` for `eval.db` and `reports/`.
  - `dashboard` — runs Streamlit (`streamlit run dashboard/app.py`), exposes the web port, mounts the same `data/` read-only.
- The same image is used in CI and locally; only the command differs.
- Secrets are passed as environment variables, never baked into the image.

---

## 17. Configuration Management Strategy

Layered configuration, validated by a Pydantic v2 `Settings` model (`config/settings.py`):

```
precedence (low → high):
  1. built-in defaults (in Settings model)
  2. config/settings.yaml          (non-secret, committed)
  3. config/thresholds.yaml        (regression rules, committed)
  4. environment variables / .env  (secrets + per-env overrides)
  5. CLI flags                     (highest, per-invocation)
```

- **Secrets** (`ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`) only ever come from env/CI secrets; `.env.example` documents them; `.env` is git-ignored.
- **Per-environment** knobs (model name, judge on/off, smoke vs full) are overridable so CI can run cheap while local/nightly runs can be thorough.
- Invalid/missing required config fails fast at startup with a clear validation error.

---

## 18. Cost-Awareness Strategy

LLM calls cost money; CI runs frequently. Controls:

- **LLM-as-judge is configurable and OFF by default in CI.** Deterministic scorers (categorical match, P/R/F1, heuristics) gate PRs; the judge is reserved for nightly/full or local deep runs.
- **Smoke vs full datasets**: PRs evaluate a small representative subset; the full golden set runs nightly/on `main`.
- **Model selection per environment**: a cheaper model (e.g. `claude-haiku-4-5`) for routine CI, larger models only where justified.
- **Token caps & `temperature=0`**: bounded `max_tokens`, deterministic decoding for reproducibility and predictable cost.
- **Path-filtered triggers**: `eval.yml` only runs when prompts/datasets/feature/config change — not on unrelated commits.
- **Cost is tracked per run** (`total_tokens`, `total_cost_usd`) and surfaced in reports and the dashboard, so cost regressions are visible too.

---

## 19. Logging Strategy

- **Structured logging** (`observability/logging.py`): JSON-ish key/value log lines, configurable level via config/env.
- Every run generates a **correlation ID** (`run_uuid`) attached to all log lines for that run, so local, CI, and DB records can be cross-referenced.
- Levels: `DEBUG` (per-case detail, local), `INFO` (run lifecycle, metrics summary), `WARNING` (warning regressions, retries), `ERROR` (failed cases, webhook failures, run failures).
- No secrets or full prompt/PII payloads logged at `INFO`; sensitive detail only at `DEBUG` locally.

---

## 20. Testing Strategy

- **Framework:** pytest. **Lint/format:** Ruff (enforced in `ci.yml`).
- **Anthropic is always mocked in tests** — recorded/stubbed responses in `tests/fixtures/`; no network calls, no cost, deterministic.
- **Unit tests** (`tests/unit/`): metrics math, threshold/regression logic, prompt/dataset hashing, registry behavior, config loading, report rendering, Slack message building, repository CRUD against a temp SQLite DB.
- **Integration tests** (`tests/integration/`): full `evaluate → compare → report` flow against a temp DB and the mocked client, including the baseline-promotion path and the critical-regression exit code.
- **Fixtures** (`tests/conftest.py`): temp SQLite DB, sample prompt + dataset versions, mocked model client, a seeded baseline.
- **Coverage target:** ~90% on `core/`, `eval/`, `regression/`, `db/`; pragmatic coverage on `cli/`, `reporting/`, `dashboard/`.
- **Determinism:** `temperature=0` and mocked responses keep tests reproducible; tests assert exact metrics and exit codes.

---

## 21. Summary

MRDS is a feature-agnostic, CLI-first AI evaluation platform with SQLite as the system of record. Features plug in via a registry; a custom engine evaluates them against versioned prompts and datasets; a regression detector compares candidates to promoted baselines; and GitHub Actions turns a critical regression into a blocked merge. Reporting, Slack alerting, a Streamlit dashboard, Docker packaging, layered config, and explicit cost controls round out a production-style deployment-safety system. See [roadmap.md](roadmap.md) for the build order.
