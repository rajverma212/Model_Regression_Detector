# CLAUDE.md — Model Regression Detection System

> Persistent project context for Claude Code. Read this first in every session before making changes. The authoritative design lives in [docs/architecture.md](docs/architecture.md); the build order lives in [docs/roadmap.md](docs/roadmap.md).

---

## 1. Project Purpose

This is the **Model Regression Detection System (MRDS)** — an **AI Evaluation Platform** and **deployment-safety system**, *not* an email-classification app.

It continuously tests LLM-powered features against **versioned golden datasets** whenever prompts, models, or datasets change; computes metrics; compares each candidate run against a promoted **baseline**; detects **regressions**; generates reports; sends Slack alerts; tracks historical performance; and **blocks deployments (CI merges) when quality degrades**.

The **Customer Support Email Classifier** is only the **first feature under test**. The platform is feature-agnostic and built for additional features (`rag_qa`, `chatbot`, `ticket_router`, …) to plug in without touching the evaluation core.

---

## 2. Architecture Principles

- **Feature-agnostic core.** Only `src/mrds/features/` contains feature-specific code. The engine, regression detector, reporting, alerting, DB, and CLI never reference a specific feature — they work through the **feature registry**.
- **Feature registry / pluggable features.** Each feature implements the `Feature` interface and registers itself. Adding a feature must require **zero** changes to `eval/`, `regression/`, `reporting/`, `alerting/`, `db/`, or `cli/`.
- **Custom evaluation engine.** The engine is custom-built. **DeepEval and RAGAS are optional future integrations**, allowed only behind the `ScorerAdapter` interface in `eval/adapters/`. Never import them in core code.
- **CLI-first.** `src/mrds/cli/` is the single entrypoint (`evaluate`, `compare`, `report`, `promote-baseline`). The **same CLI runs locally and in GitHub Actions**. CI behavior must equal local behavior.
- **Fail-closed.** A critical regression makes `compare` exit non-zero, which blocks the merge. Quality gates default to blocking.
- **SQLite is the system of record.** Tables: `runs`, `test_results`, `regressions`, `baselines`, `prompt_versions`, `dataset_versions`. All writes go through `db/repository.py`. Reports and dashboards are derived views.
- **Deterministic & reproducible.** Every run pins a prompt version, dataset version, and model. Use `temperature=0`. Identity of prompts/datasets is their **content hash**.
- **Baseline promotion is explicit.** Baselines are never silently overwritten by a worse run. Promotion happens via `promote-baseline` (or gated auto-promotion on green `main`).
- **Cost-aware.** LLM-as-judge is configurable and **off by default in CI**. Prefer deterministic scorers for gating; use smoke subsets in PRs and full datasets nightly.

---

## 3. Coding Standards

- **Python 3.11.** Use modern syntax (`X | None`, `match`, `dataclasses`/Pydantic where appropriate).
- **Ruff** is the linter and formatter. Code must be Ruff-clean before completion. Do not hand-format against it.
- **Pydantic v2** for all domain models, I/O schemas, and `Settings`. Use v2 idioms (`model_validate`, `model_dump`, `Field`, `field_validator`) — not v1.
- **Small, single-responsibility modules** matching the architecture layout. Don't put feature logic in core modules.
- **No secrets in code or committed files.** `ANTHROPIC_API_KEY` and `SLACK_WEBHOOK_URL` come from environment/CI secrets; document them in `.env.example`.
- **Explicit errors.** Fail fast with clear messages on invalid config, schema violations, or missing baselines.
- **Pure functions for metrics/thresholds** — no I/O inside `metrics.py` / `thresholds.py` so they're trivially testable.

---

## 4. Type Hint Requirements

- **Full type hints are mandatory** on every function signature (parameters and return types), including private helpers.
- Annotate module-level constants and non-trivial locals where it aids clarity.
- Prefer precise types: Pydantic models over `dict`, `Enum`/`Literal` over bare `str` (e.g. category and severity values), `Protocol` for the `Feature`/`Scorer`/`ScorerAdapter` interfaces.
- No bare `Any` unless genuinely unavoidable, and comment why.

---

## 5. Testing Standards

- **pytest** is the test framework. **The Anthropic API is always mocked** — never make real network/model calls in tests (no cost, deterministic).
- Recorded/stub responses and sample prompts/datasets live in `tests/fixtures/`; shared fixtures (temp SQLite DB, mocked client, seeded baseline) in `tests/conftest.py`.
- **Unit tests** for: metrics math, regression/threshold logic, hashing, registry, config loading, report rendering, Slack message building, repository CRUD.
- **Integration tests** for: full `evaluate → compare → report` flow, baseline promotion, and the critical-regression exit code.
- Tests assert **exact** metrics and **exact CLI exit codes** (the gate must be verifiable).
- **Coverage target:** ~90% on `core/`, `eval/`, `regression/`, `db/`; pragmatic coverage elsewhere.
- Every behavioral change ships with tests. Run Ruff + pytest before considering work done.

---

## 6. Documentation Standards

- **Docstrings** on all public modules, classes, and functions: what it does, key args, return, and side effects (especially DB writes / network calls).
- Keep [docs/architecture.md](docs/architecture.md) authoritative. **If a change alters design (schema, interfaces, data flow, CLI surface), update architecture.md in the same change.**
- Update `README.md` for any user-facing change (CLI flags, setup steps).
- Comment the *why*, not the *what*; match the density of surrounding code.
- When adding a feature, document its prompt/dataset versions and thresholds.

---

## 7. Preferred Libraries (the stack)

Use these; do not introduce alternatives without reason.

| Concern | Library |
|---------|---------|
| Language | Python 3.11 |
| LLM API | Anthropic API (Claude) |
| Models / validation / settings | Pydantic v2 |
| Persistence | SQLite (stdlib `sqlite3`) |
| Prompt versioning | YAML files |
| Datasets | JSON files |
| Templating / reports | Jinja2 |
| Dashboard | Streamlit |
| CI/CD | GitHub Actions |
| Alerts | Slack incoming webhooks |
| Packaging/runtime | Docker + docker-compose |
| Testing | pytest |
| Lint/format | Ruff |
| Optional eval integrations (behind adapters only) | DeepEval, RAGAS |

---

## 8. Folder Conventions

```
src/mrds/
  cli/          CLI entrypoint + commands (evaluate, compare, report, promote-baseline)
  core/         feature-agnostic primitives: interfaces, registry, models, hashing, ids
  features/     the ONLY feature-specific code (email_classifier, future: rag_qa, …)
  prompts/      prompt versioning runtime (loader, registry)
  datasets/     dataset versioning runtime (loader)
  eval/         custom engine, metrics, judge, adapters/ (DeepEval/RAGAS behind interfaces)
  regression/   detector + thresholds
  reporting/    Jinja2 report builder + templates
  alerting/     Slack client + message templates
  db/           SQLite connection, schema.sql, migrations, repository
  config/        Pydantic Settings
  observability/ structured logging
  dashboard/    Streamlit app + pages (original prototype)
  api/          HTTP API (FastAPI) backing the web frontend — feature-agnostic, presentation only
web/            Next.js "Evaluation OS" frontend — the primary product surface (see docs/web-frontend.md)
prompts/        versioned prompt YAML (prompts/<feature>/vN.yaml)
datasets/       versioned golden JSON (datasets/<feature>/vN.json + .meta.json)
config/         settings.yaml, thresholds.yaml (committed, non-secret)
reports/        generated reports (git-ignored)
data/           eval.db (git-ignored)
tests/          unit/, integration/, fixtures/, conftest.py
docs/           architecture.md, roadmap.md
.github/workflows/  ci.yml, eval.yml
```

Conventions:
- New features go under `features/<name>/` with `schema.py`, `feature.py`, `scorers.py`, and are registered in `features/__init__.py`.
- Prompts and datasets are **versioned, immutable per version**; create `vN+1` rather than editing a released version.
- Derived artifacts (`reports/`, `data/eval.db`) are git-ignored; never commit secrets or `.env`.

---

## 9. Working Agreement for Claude Code

- **Follow the roadmap.** Build in sprint order ([docs/roadmap.md](docs/roadmap.md)); each sprint must leave the system working and tested. Do not jump ahead unless asked.
- **Respect the boundaries.** Never leak feature-specific logic into core modules; never import optional eval libs outside their adapters.
- **No real API calls in tests.** Always mock Anthropic.
- **Keep the gate honest.** `compare`'s exit code is the merge gate — guard it with tests.
- Before finishing any task: full type hints, Ruff clean, pytest green, docstrings present, and architecture.md/README updated if design or usage changed.

---

## 10. Roadmap Reference

The implementation plan (Sprint 0 → Sprint 12) is in [docs/roadmap.md](docs/roadmap.md). The first runnable vertical slice (evaluate one feature end-to-end and persist a run) lands at **Sprint 5**; the quality gate at **Sprint 6**; deployment safety (CI + Docker) at **Sprints 10–11**.
