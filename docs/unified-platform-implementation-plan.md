# Unified Platform — Implementation Plan

> **Status:** Plan only (Task 2). Implements the design in
> [unified-platform-flow.md](unified-platform-flow.md).
> **Principle:** smallest change set; all new *logic* in a pure, testable helper; the UI
> is a thin caller. **Do not modify** the evaluation engine, regression detector, DB
> schema, reporting, or alerting (they are only *used*).
> **Date:** 2026-06-10.

## Change set overview

| # | Change | Kind |
|---|--------|------|
| 1 | **`src/mrds/activation/lifecycle.py`** (new) — `activate_bundle()` and `run_first_evaluation()` orchestration helpers. | New, pure, testable |
| 2 | **`src/mrds/onboarding/app.py`** — extend the wizard with Step 6 (Activate) and Step 7 (Run first evaluation + inline results + dashboard link). | UI (thin) |
| 3 | **`src/mrds/dashboard/app.py`** — add a small "➕ Onboard a feature" pointer (cross-link back). | UI (1 line) |
| 4 | **`tests/unit/test_lifecycle.py`** (new) — test the helpers + full create→activate→evaluate→DashboardData. | Tests |

No other files change. `lifecycle.py` is **not** re-exported from `activation/__init__.py`
(it imports the engine; keeping it out of `__init__` keeps the lightweight
`features/__init__` → `activation.discovery` global-hook import path engine-free).

---

## Step 1 — `activation/lifecycle.py`

**Files changing:** new file only.

- `activate_bundle(bundle_dir, *, root, registry=feature_registry) -> InstalledPaths`
  = `install_bundle` + `register_installed_features` (the "Activate" click).
- `run_first_evaluation(installed, *, root, store, client=None, triggered_by="onboarding",
  max_cases=None) -> EvaluationResult` — loads the installed spec, builds the feature via
  `build_from_spec` (**`client` injectable**; `None` → real OpenAI at run time), builds a
  scoped `DatasetRegistry`, runs the **unchanged** `EvaluationEngine`, and persists via
  `EvaluationStore.save_evaluation`.

**Risks:** import surface (pulls in the engine) → mitigated by *not* importing lifecycle in
`activation/__init__`. The helper only *uses* the engine/store — no modification.
**Test strategy:** unit tests with a deterministic stub client (no OpenAI); assert metrics,
persistence, and `DashboardData` visibility.
**Backward compatibility:** purely additive; nothing imports it at platform-import time.

---

## Step 2 — `onboarding/app.py` (wizard extension)

**Files changing:** `src/mrds/onboarding/app.py`.

- Bump `_TOTAL_STEPS` to 7; keep Steps 1–5 unchanged (Step 5 still writes the bundle and
  stores `state["bundle_dir"]`).
- **Step 6 — Activate:** a deliberate button → `activate_bundle(bundle_dir, root=".")`;
  store `InstalledPaths`; plain-language success. (Default platform root is the working
  dir, so artifacts land in the discoverable `specs/`, `prompts/`, `datasets/`.)
- **Step 7 — Run first evaluation:** a deliberate button, **enabled only if a model key is
  configured** (`get_settings().openai_api_key`); otherwise disabled with a one-line CLI
  fallback (`mrds evaluate --feature <name>`). On click →
  `run_first_evaluation(installed, root=".", store=EvaluationStore(open_database()))` →
  render an **inline summary** (pass rate, passed/failed/errored, per-segment) and a
  **"View in dashboard ▸"** hint pointing at the Runs page.
- "Start over" resets the new state keys too.

**Risks:** (a) Streamlit not installed in the test venv → the page can't be unit-tested
(consistent with the project); verified by Ruff + byte-compile, logic covered by Step-1
tests. (b) Running an eval writes to `data/eval.db` (the dashboard's DB) — correct for the
real platform; the demonstration uses tmp/in-memory to avoid touching the repo. (c) No key
→ graceful degradation (button disabled + CLI hint), never a dead end.
**Test strategy:** byte-compile + Ruff; the wrapped lifecycle is covered by Step-1/Step-4
tests; a script demonstrates the end-to-end UI path with a stub.
**Backward compatibility:** the wizard's existing Steps 1–5 are unchanged; the additions
are new steps reached only after Generate.

---

## Step 3 — `dashboard/app.py` (cross-link)

**Files changing:** `src/mrds/dashboard/app.py`.

- Add one caption/markdown line on Home: "➕ **Onboard a feature** — run the wizard:
  `streamlit run src/mrds/onboarding/app.py`." Display-only; no logic, no data changes.

**Risks:** none of substance (a text line).
**Test strategy:** byte-compile (pages aren't unit-tested).
**Backward compatibility:** additive; dashboard reads nothing new and writes nothing.

---

## Step 4 — `tests/unit/test_lifecycle.py`

**Files changing:** new test file.

- `activate_bundle` installs + registers into a **local** registry (isolated `root`).
- `run_first_evaluation` with a **stub client** produces metrics, persists to an in-memory
  store, and the run is visible via `DashboardData`.
- **Full lifecycle:** onboard (core) → `activate_bundle` → `run_first_evaluation` →
  `DashboardData.features()` includes the new feature with its run.

**Backward compatibility:** new tests only.

---

## Backward-compatibility & safety summary

- **Untouched:** evaluation engine, regression detector, DB schema, reporting, alerting
  (only *used*, never modified).
- **Email Classifier / Ticket Router:** unaffected — no changes to their packages, and the
  global feature registry still resolves to exactly them (no `specs/` in the repo → the
  discovery hook stays a no-op).
- **Isolation:** all new logic is parameterized by `root`/`store`/`client`; tests and the
  demo use tmp dirs + in-memory stores + a stub client, so the repo working tree and the
  shared `datasets/` invariant are never disturbed.
- **Demo mode:** unaffected; the unified flow is a real-platform path. With no key, Step 7
  degrades to a CLI hint rather than failing.

## Smallest-change rationale
One new helper module carries all the logic; the wizard and dashboard gain thin UI/links;
the engine/regression/DB/reporting/alerting are reused as-is. This delivers
Create→Activate→Evaluate→Results continuity with the minimum new surface and zero core
modification.
