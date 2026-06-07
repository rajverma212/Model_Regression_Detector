# Support Ticket Router — Onboarding Report

> **Exercise:** Platform validation, not a product initiative. We onboarded a second
> feature (**Support Ticket Router**) to measure how feature-agnostic MRDS really is,
> against the prediction in [multi-feature-audit.md](multi-feature-audit.md).
> **Result:** Onboarded end-to-end with **no changes to any core subsystem.** All 219
> tests pass; the email classifier is behaviourally unchanged; the dashboard shows
> both features. **Date:** 2026-06-06.

---

## 1. Files added

| File | Purpose |
|------|---------|
| [src/mrds/features/ticket_router/schema.py](../src/mrds/features/ticket_router/schema.py) | `TicketCategory`, `TicketPriority`, `TicketRoutingInput/Output` Pydantic models. |
| [src/mrds/features/ticket_router/scorers.py](../src/mrds/features/ticket_router/scorers.py) | `CategoryMatchScorer`, `PriorityMatchScorer` (deterministic exact-match). |
| [src/mrds/features/ticket_router/feature.py](../src/mrds/features/ticket_router/feature.py) | `TicketRouterFeature` implementing the `Feature` contract; `build_feature()`. |
| [src/mrds/features/ticket_router/__init__.py](../src/mrds/features/ticket_router/__init__.py) | Exports + factory. |
| [prompts/ticket_router/v1.yaml](../prompts/ticket_router/v1.yaml) | Versioned routing prompt (system + 4 few-shot examples). |
| [datasets/ticket_router/v1.json](../datasets/ticket_router/v1.json) | Golden dataset — 20 hand-labeled cases across 4 queues, with priority + difficulty + notes. |
| [src/mrds/demo/ticket_client.py](../src/mrds/demo/ticket_client.py) | Deterministic offline client (demo only). |
| [tests/unit/test_ticket_router.py](../tests/unit/test_ticket_router.py) | End-to-end onboarding test (scorers + engine + store + regression + dashboard data). |
| [docs/support-ticket-router-onboarding.md](support-ticket-router-onboarding.md) | This report. |

## 2. Files modified

**The only *required* change to make the feature work is one line in the registry.**
The rest support the exercise's goals (live demo visibility, keeping the suite green).

| File | Change | Category | Required to function? |
|------|--------|----------|:---------------------:|
| [src/mrds/features/__init__.py](../src/mrds/features/__init__.py) | One factory entry: `"ticket_router": build_ticket_router`. | **Intended extension seam** | **Yes** |
| [src/mrds/dashboard/help_text.py](../src/mrds/dashboard/help_text.py) | Added a `FEATURE_INFO["ticket_router"]` copy entry. | Dashboard **content** (falls back to slug) | No (cosmetic) |
| [src/mrds/demo/seed.py](../src/mrds/demo/seed.py) | Appended ticket-router seeding; **switched the dataset resolver to the default** (see §4). | Demo (Tier B) | No (demo only) |
| [src/mrds/demo/__init__.py](../src/mrds/demo/__init__.py) | Exported `DeterministicTicketRouterClient`. | Demo (Tier B) | No |
| [tests/unit/test_demo.py](../tests/unit/test_demo.py) | Updated **one** assertion: `features()` now lists two features. | Test | No |
| [tests/unit/test_cli.py](../tests/unit/test_cli.py) | Switched a hardcoded dataset resolver to the default (see §4). | Test harness | No |
| [tests/unit/test_evaluation_engine.py](../tests/unit/test_evaluation_engine.py) | Same resolver switch. | Test harness | No |

### Core systems — UNTOUCHED (the success criterion)
No edits to: **Evaluation Engine** ([engine.py](../src/mrds/evaluation/engine.py)),
**Metrics** ([metrics.py](../src/mrds/evaluation/metrics.py)), **Regression Detector**
([regression/](../src/mrds/regression/)), **Database schema/repositories/store**
([db/](../src/mrds/db/)), **Dashboard architecture** (pages, `_shared.py`, `data.py`),
**Reporting** ([reporting/](../src/mrds/reporting/)), **Alerting**
([alerting/](../src/mrds/alerting/)), **CLI** ([cli/](../src/mrds/cli/)), core
interfaces, or the prompt/dataset loaders. The dashboard renders the new feature with
**zero** dashboard-architecture changes.

## 3. Time / effort estimate

| Activity | Effort |
|----------|:------:|
| Feature code (schema, feature, scorers, `__init__`) — mechanical mirror of email | ~20 min |
| Prompt YAML | ~10 min |
| **Golden dataset (20 cases)** — the dominant cost | ~35 min |
| Registry line + dashboard copy | ~5 min |
| Demo client + seeding (for live dashboard visibility) | ~25 min |
| End-to-end test | ~20 min |
| Diagnosing & fixing the resolver coupling (§4) | ~15 min |
| **Total** | **~2 hours** |

The feature *itself* (registry line + 4 code files + prompt + dataset) is ~1 hour and
needs no core knowledge. The demo + the resolver fix were the only "platform" work.

## 4. Pain points encountered

1. **The hardcoded `model_resolver` (the main one).** Adding a second dataset to the
   shared `datasets/` directory broke the demo seed **and two existing email tests**.
   `DatasetRegistry.from_directory` **eagerly loads every** dataset in the tree, but
   those call sites passed `model_resolver=lambda _f: (Email*Input, Email*Output)` —
   a single-feature resolver that then tried to validate *ticket* cases against *email*
   models (and vice-versa), raising `DatasetValidationError`. **Fix:** drop the
   hardcoded lambda and use the **registry-based default resolver** (`from_directory(dir)`),
   which already exists and resolves each feature to its own models. This is a call-site
   fix, **not** a core change — the engine itself already used the default resolver, so
   it was unaffected. The audit predicted this exact Tier-B coupling for the demo; it
   turned out to also live in two tests.
2. **The demo is single-feature by construction.** `seed_demo` and its
   `DeterministicEmailClient` are email-shaped; showing a second feature in the *live*
   demo required a parallel deterministic client + an additive seed block. Functional
   work, isolated to `demo/` — exactly the "Medium" effort the audit flagged.
3. **One demo test assertion was feature-count-specific** (`features() == ["email_classifier"]`).
   A legitimate one-line update once the demo is intentionally multi-feature.

None of these touched core; all were anticipated (the first two explicitly) by the audit.

## 5. Unexpected assumptions discovered

- **`from_directory` is eager + global-resolver.** The non-obvious one: a per-feature
  directory layout plus a *fixed* resolver works only while there's exactly one feature.
  The clean pattern (default registry resolver) was already available but not used at
  several call sites — a latent assumption that "there is one feature."
- **`segment_field` is per-run, and it just works.** Routing segmented cleanly by
  `category` with no engine awareness — confirming the metrics/segment design is
  genuinely generic (a second exact-match scorer, `priority_match`, was also
  auto-discovered and aggregated with no special handling).
- **The dashboard needed nothing.** Human-readable run names, the explorer, comparison,
  regressions, and KPIs all rendered ticket_router with no page edits — the recent
  feature-agnostic dashboard work held up.

## 6. Recommended onboarding improvements

1. **Default the resolver everywhere.** Treat `DatasetRegistry.from_directory(dir)`
   (registry resolver) as the only blessed pattern; remove hardcoded
   `model_resolver=lambda …` from demo and tests. Consider making a fixed-model
   resolver an explicit opt-in for isolated tmp-dir tests only.
2. **Write a short `docs/adding-a-feature.md` recipe**: "create `features/<name>/`
   (schema, feature, scorers, `__init__`), author `prompts/<name>/v1.yaml` and
   `datasets/<name>/v1.json`, add one line to `features/__init__.py`." That is the whole
   required path.
3. **Optionally generalize the demo** into a small per-feature `DemoSpec` (oracle +
   run specs + deterministic client) so adding a second/third demo narrative is data,
   not code. Only worth it once 2–3 features want hosted demos.
4. **Optional dashboard nicety:** multi-field input rendering in `_primary_input_text`
   (not needed here — tickets are single-field — but useful for Resume Screener later).

## 7. Final verdict

> **Can a developer onboard a new *classification* feature without modifying core MRDS
> systems?**
>
> **Yes — conclusively.**

### Evidence
- **Zero core edits.** Engine, metrics, regression detector, DB schema, dashboard
  architecture, reporting, and alerting were not modified (§2). The only *required*
  change was a **one-line registry entry**; everything else was new per-feature files.
- **End-to-end works, fully offline.** [test_ticket_router.py](../tests/unit/test_ticket_router.py)
  drives the real engine over the 20-case dataset → a perfect run scores 100% with both
  scorers (`category_match`, `priority_match`) and 4 category segments auto-discovered;
  a degraded run persists, promotes a baseline, and the **regression detector flags the
  drop** — all surfaced through `DashboardData` (`features()` includes `ticket_router`,
  runs/metrics reconstruct, regressions resolve).
- **Dashboard shows it.** In demo mode the dashboard now lists **both** features —
  `email_classifier` (5 runs, 74%, critical) and `ticket_router` (2 runs, 65%, critical)
  — with no dashboard-architecture changes.
- **Email is unchanged.** The email classifier's tests pass with byte-identical
  behaviour; the only email-adjacent edits were swapping a hardcoded test resolver for
  the default (no behavioural change). **219/219 tests pass.**
- **The one friction was non-core and predicted.** A hardcoded dataset resolver assumed
  a single-feature directory; the fix was to use the already-existing feature-agnostic
  default resolver — a call-site change, not an architecture change.

**Conclusion:** MRDS's feature-agnostic claim holds. A classification feature is
onboarded with a registry line plus self-contained feature/prompt/dataset files; the
shared evaluation, regression, persistence, reporting, and dashboard machinery absorb it
unchanged. The only platform-level lesson is to standardise on the registry-based
dataset resolver so the "one feature" assumption is removed for good.
