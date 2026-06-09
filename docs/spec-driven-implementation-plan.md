# Spec-Driven Features — Smallest Validation Plan

> **Status:** Plan only. Nothing implemented, no code modified.
> **Builds on:** [spec-driven-feature-design.md](spec-driven-feature-design.md) (feasible
> with zero core changes).
> **Goal:** the smallest path that *proves* spec-driven features work end-to-end and
> reach parity with a hand-coded feature.
> **Date:** 2026-06-07.

## Guardrails (restated)
- **Do not** migrate Email Classifier or Ticket Router.
- **Do not** modify the evaluation engine, regression detection, the database schema, or
  dashboard architecture.
- All new code lives in a **single new package** — `src/mrds/features/spec/` — that only
  *produces* `Feature`/`Scorer` objects. The core consumes them unchanged.

## Isolation principle (how the guardrails are kept)
Two deliberate choices keep this additive and low-risk:
1. **No global registry wiring.** The proof-of-concept registers its generated feature in
   an **explicit, local `FeatureRegistry`** passed to the engine (exactly as
   `tests/unit/test_ticket_router.py` does) — so `features/__init__.py` and global state
   are untouched.
2. **No real-LLM dependency for validation.** All runs use an **injected deterministic
   client**; OpenAI structured-output compatibility with dynamic models is called out as a
   separate pre-production check, not part of the smallest path.

---

## Phase 1 — Building blocks (pure, unit-testable; no feature yet)

Implement the generation layer in isolation: spec parsing, dynamic models, the scorer
library, and the generic feature.

### Files required (all new, under `src/mrds/features/spec/`)
- `__init__.py` — package exports.
- `spec.py` — `FeatureSpec` Pydantic model (`feature_name`, `input_fields`,
  `output_fields` incl. enum `values`, `scoring`, optional `segment_field`,
  `prompt_feature`/refs) + YAML parsing/validation. (No engine/DB coupling.)
- `models.py` — dynamic model generation: `build_input_model(spec)`,
  `build_output_model(spec)` via `pydantic.create_model` + dynamically-created `StrEnum`s;
  `extra="forbid"`.
- `scorers.py` — the **minimal** library needed for parity: `exact_match(field)` and
  `text_bounds(field, **params)`. **Field-name/`getattr`-based**, implementing the
  `Scorer` protocol (no concrete-class `isinstance`).
- `feature.py` — `GenericStructuredFeature(spec, *, client=None, prompt_registry=None)`
  implementing `Feature`: `name`/`dataset_ref` from spec; `input_model`/`output_model` =
  generated; `scorers()` = library instances; `run_with_usage()` = resolve prompt (by a
  configurable `prompt_feature`, defaulting to `feature_name`), build messages from
  `input_fields`, `client.parse_structured(schema=output_model)`. A `build_from_spec(...)`
  factory.

### Dependencies
- Inward only: `core/interfaces.py` (`Feature`, `Scorer`, `ScoreResult`,
  `FeatureRunResult`), `pydantic`, and the existing `prompts` loader/registry for the run
  path. **Nothing** from `eval/`, `regression/`, `db/`, `dashboard/`.

### Risks
- **Dynamic enum / `create_model` mechanics** (naming, `extra="forbid"`, JSON
  round-trip). *Mitigation:* unit tests over valid/invalid payloads.
- **`text_bounds` parity** with the email `summary_quality` heuristic (word/sentence
  bounds) — must match exactly to be useful later. *Mitigation:* port the exact bounds and
  test against the same inputs.
- **Field-name scorers losing type-safety.** *Mitigation:* score only **after** the LLM
  client validates output against the generated model.

### Test strategy
- `tests/unit/test_spec_models.py` — generation: correct fields/enums, enum coercion,
  `extra="forbid"` rejects unknown keys, invalid spec raises.
- `tests/unit/test_spec_scorers.py` — `exact_match` (match/mismatch/`detail` string),
  `text_bounds` (bounds + params), operating via field name.
- `tests/unit/test_spec_feature.py` — `GenericStructuredFeature.run_with_usage()` with a
  **stub client**: returns a validated output + token usage; `scorers()` wired correctly.

**Exit criterion:** the generation layer is fully unit-tested with no feature artifacts.

---

## Phase 2 — One minimal proof-of-concept feature + end-to-end run

Prove the generated feature flows through the **unchanged** engine → metrics → store →
regression → `DashboardData`. Use a brand-new tiny feature (not email/ticket).

### Files required
- `features/sentiment_poc/feature.yaml` — the spec: input `{text: string}`, output
  `{sentiment: enum[positive, negative, neutral]}`, scoring `[{field: sentiment, scorer:
  exact_match}]`, `segment_field: sentiment`.
- `prompts/sentiment_poc/v1.yaml` — a minimal prompt (the stub client ignores it, but the
  loader requires one to exist).
- `datasets/sentiment_poc/v1.json` — ~6–8 labeled cases across the three labels.
- `tests/unit/test_spec_poc.py` — the end-to-end test (below).

### Dependencies
- Phase 1. Plus, **for isolation**, the test loads the PoC dataset with a resolver scoped
  to the generated models (or registers the PoC feature in a **local** registry the
  `DatasetRegistry` resolves against) — avoiding the shared-directory resolver pitfall and
  any global wiring.

### Risks
- **Spec ↔ prompt ↔ dataset drift** — dataset `expected_output` values must validate
  against the generated output model. *Mitigation:* `DatasetRegistry` already validates at
  load; keep dataset labels within the declared enum.
- **Dataset model resolution for a non-globally-registered feature.** *Mitigation:* per
  the isolation principle — local registry / scoped resolver in the test (mirrors the
  existing `tmp_path` engine tests). Do **not** pass a hardcoded resolver over the shared
  `datasets/` dir.
- **Real-LLM compatibility is *not* covered** here (deliberate). Flag a separate
  pre-production check: confirm OpenAI structured outputs accept a dynamically-created
  Pydantic model.

### Test strategy
- Build `GenericStructuredFeature` from `feature.yaml`; register in a **local**
  `FeatureRegistry`; run `EvaluationEngine.run(EvaluationConfig(feature="sentiment_poc",
  segment_field="sentiment"))` with a **deterministic stub client**.
- Assert: `total_cases`, `pass_rate`, `scorers` discovered (`exact_match`), segments by
  `sentiment`.
- Persist to an **in-memory** `EvaluationStore`; promote a baseline; run a degraded
  candidate; `RegressionDetector().compare(...)`; assert a regression.
- Assert visibility through `DashboardData` (`features()`, `runs()`, `run_detail()`,
  `regressions_for_run()`).

**Exit criterion:** a feature defined *only* by `feature.yaml` evaluates end-to-end and
surfaces through the dashboard's data seam — with no core or global-registry changes.

---

## Phase 3 — Parity with an existing feature (without migrating it)

Demonstrate the generic path reproduces a hand-coded feature **byte-for-byte**, while
leaving the real feature untouched. **Use Ticket Router** (exact-match only — the cleanest
parity target; Email's `text_bounds` parity is a noted stretch goal).

### Files required
- `tests/unit/test_spec_parity.py` — the parity test (below). The spec is defined
  **inline** (or as a fixture) to mirror Ticket Router's fields/scorers and is pointed at
  Ticket Router's **existing** prompt + dataset via `prompt_feature="ticket_router"` and
  the ticket dataset. **No new content files; the real `ticket_router` package is not
  modified or migrated.**

### Dependencies
- Phase 1. Reuses the existing `datasets/ticket_router/v1.json` and
  `prompts/ticket_router/v1.yaml` read-only. Uses the same deterministic stub client for
  both runs so outputs depend only on the oracle, not the prompt.

### Risks
- **Parity mismatch** — if metrics differ, it exposes a real behavioral gap in the
  generic path (which is the point; better found here than in production).
- **Prompt-key coupling** — the shadow must resolve Ticket Router's prompt; handled by the
  `prompt_feature` override designed in Phase 1.
- **Scope creep toward Email** — Email parity additionally requires `text_bounds` to match
  `summary_quality` exactly; keep that **out** of the smallest path (note it as follow-on).

### Test strategy
- Over the same ticket dataset and the same stub client, run **(A)** the hand-coded
  `TicketRouterFeature` and **(B)** the spec-driven `GenericStructuredFeature` shadow
  through the engine.
- Assert **byte-identical** `AggregateMetrics` (pass_rate, per-scorer means/pass-rates,
  segments, latency/token structure) **and** identical per-case `CaseResult` outputs/scores.

**Exit criterion:** generated Ticket Router == hand-coded Ticket Router on identical
inputs — proving the spec path is a faithful substitute, with the real feature untouched.

---

## Smallest-path summary

| Phase | New files | Touches core? | Proves |
|------:|-----------|:-------------:|--------|
| 1 | `features/spec/{__init__,spec,models,scorers,feature}.py` + 3 unit tests | No | The generation layer works in isolation. |
| 2 | `features/sentiment_poc/feature.yaml`, `prompts/sentiment_poc/v1.yaml`, `datasets/sentiment_poc/v1.json` + 1 test | No | A YAML-only feature runs end-to-end through the unchanged engine and dashboard data. |
| 3 | `tests/unit/test_spec_parity.py` (reuses ticket artifacts) | No | The generic path matches a hand-coded feature exactly. |

**Total surface:** one new package + one tiny PoC feature + tests. **Zero** edits to
`eval/`, `regression/`, `db/`, `dashboard/`, or the two existing features.

## Explicitly deferred (not in the smallest path)
- Global auto-discovery/registration of specs (`features/__init__.py` wiring).
- Migrating Email Classifier / Ticket Router to specs (and deleting their packages).
- `numeric_tolerance`, `set_overlap`/`f1` scorers; the **judge/semantic adapter** for RAG.
- **Real OpenAI structured-output verification** with dynamic models (run once before any
  production use).
- Spec **content-hashing/versioning** on the run record (reproducibility design decision).
- Multi-field input display polish in the dashboard.

> **Bottom line:** three additive phases — build the generation layer, prove one YAML-only
> feature end-to-end, then show byte-parity with Ticket Router — validate spec-driven
> features with no changes to any core subsystem and no migration of the existing features.
