# Web Frontend & HTTP API — the Evaluation OS

> **Status:** Implemented. Adds two presentation layers — `src/mrds/api/` (FastAPI) and
> `web/` (Next.js) — over the existing, unchanged platform core.
> **Principle:** the evaluation engine, regression detector, golden datasets, baselines,
> DB schema, onboarding, and CLI are **reused, not modified**. Both new layers are
> feature-agnostic, in the same spirit as the Streamlit dashboard.
> **Date:** 2026-06-13.

## 1. What the product is

MRDS grew from a regression detector into a platform. The capabilities were strong but the
experience felt like *several tools* — a separate onboarding wizard, a read-only Streamlit
dashboard of flat tables and raw UUIDs, baseline promotion only on the CLI. The audits
(`product-audit.md`, `ux-hierarchy-audit.md`, `unified-platform-flow.md`) named the gap
precisely: **rich data shown without a verdict, and a workflow split across disconnected
surfaces.**

The reframe: this is an **AI Evaluation Operating System** — the control plane for the
health, quality, and evolution of a *fleet* of AI features. One product, one mental model:

```
Create a feature → Activate → Evaluate → Analyze → Promote / Gate
```

## 2. The HTTP API (`src/mrds/api/`)

A thin, feature-agnostic FastAPI layer — the missing contract a modern frontend needs.
It adds **no evaluation logic**; every endpoint reuses the read-only `DashboardData` seam
(or, for promotion, `EvaluationStore` + `BaselinePromoter`) and a serializer.

- **`serializers.py`** — the stable JSON wire contract. Enriches the platform's records
  with what the UI needs: plain-language verdicts, baseline deltas, humanized metric
  labels, per-case explanations (actual vs expected + each scorer's reason), sparklines.
- **`runtime.py`** — a **per-request** `ApiSession` (one SQLite connection per request).
  Sharing one connection across FastAPI's threadpool races under the parallel fetches a
  page issues; per-request connections + WAL are safe and cheap.
- **`app.py`** — the routes (all feature-agnostic):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/features` | fleet overview (health, baseline delta, sparkline) |
| GET | `/api/features/{f}` | one feature's headline status |
| GET | `/api/features/{f}/runs` | run timeline |
| GET | `/api/features/{f}/trend` | metric time series |
| GET | `/api/features/{f}/dataset` | golden dataset + coverage |
| GET | `/api/features/{f}/baseline` | active baseline + promotion history |
| POST | `/api/features/{f}/baseline/promote` | promote a run (guarded; see below) |
| GET | `/api/runs/{uuid}` | **the hero payload**: verdict → metrics → explained cases |
| GET | `/api/runs/{uuid}/regressions` | root cause: regressed metric → contributing cases |
| GET | `/api/compare?a=&b=` | run-vs-run diff |
| POST | `/api/onboarding/infer` | infer a feature spec + scaffold a prompt from a dataset |

**Promotion stays honest.** `POST .../promote` runs `BaselinePromoter.check`; a run with a
critical regression returns `promoted: false` + reasons (HTTP 200, no mutation) unless
`force: true` — preserving the platform's "never silently overwrite with a worse run" rule,
now surfaced in the UI as an explicit "promote anyway".

Run it with `python -m mrds.api` (or the `mrds-api` script). Covered by
`tests/unit/test_api.py` (TestClient over a seeded temp DB; OpenAI never called).

## 3. The frontend (`web/`)

Next.js 16 / React 19 / TypeScript / Tailwind v4. Server components fetch from the API;
client components (filters, compare, promote, the create wizard) call `/api/*` same-origin
via a rewrite. Charts are **bespoke SVG** (no chart lib) for design control and reliable
rendering on this stack. See `web/README.md` for structure and the design system.

### Information architecture

The old IA was seven peer pages (Home · Runs · Trends · Compare · Regressions · Baselines ·
Dataset) plus a disjoint wizard. The new IA is a **fleet → workspace** hierarchy:

- **Mission Control** — the fleet. Each feature is a card with a health verdict, latest
  pass rate vs baseline, a trend sparkline, and flagged-run count. This is the "managing
  the health of AI systems" feeling, not a database dump.
- **Feature workspace** — one feature's whole story behind a single header + sub-nav:
  Overview, Runs, Run detail, Trends, Compare, Regressions, Dataset, Baseline. Selecting a
  feature in the rail carries through every tab (the cross-page state the audit asked for).
- **Create** — onboarding folded into the same app: dataset → inferred schema → prompt →
  activate, flowing toward the workspace instead of dead-ending at "bundle generated".

### Verdict-first, explainable

Every screen leads with a conclusion, then evidence, then detail — the pattern
`ux-hierarchy-audit.md` prescribed. The run-detail page is the clearest example and closes
the platform's biggest unmet promise: it opens with *"20 pts below baseline · 14 of 54
cases failing"* and a red score ring, exposes the weak segment (`general` at 8%) visually,
explains **why it regressed** in words, and every failing case shows the model's actual
output against expected plus each scorer's reason. Baseline promotion is now a UI action.

## 4. Design system

**Instrument-grade observatory:** a warm-ink dark field; one cool instrument-cyan signal
accent held against warm neutrals; a strict **green / amber / red verdict triad** used
*only* for AI-health semantics (so color always means "how is this doing"). Type is a
three-role system — Instrument Serif (hero), Hanken Grotesk (UI), JetBrains Mono (all
metrics and ids, so numbers read like instrument readouts). Motion is one orchestrated
staggered reveal per view, never decoration. Tokens: `web/app/globals.css`.

## 5. What stayed untouched / what's deferred

- **Untouched:** evaluation engine, regression detector, thresholds, DB schema, reporting,
  alerting, golden datasets, baselines, CLI, and the spec/onboarding cores. The Streamlit
  dashboard remains as the original prototype.
- **Deferred:** wiring the Create flow's final "activate + first evaluation" through the
  API end-to-end (it writes to the platform and calls a model — deliberately a CLI step
  today, matching `post-onboarding-flow.md`); auth/multi-tenant; live run streaming.
