# Post-Onboarding Flow — Bundle → Feature Appears in MRDS

> **Status:** Analysis & design only. No code, no implementation.
> **Question:** what is the *smallest* path from a generated bundle to a feature that is
> actually usable inside MRDS (runnable **and** visible)?
> **Builds on:** the onboarding wizard (produces a validated `features/<name>/` bundle)
> and the spec-driven layer (`build_from_spec`, `load_feature_spec`).
> **Date:** 2026-06-10.

## What "appears in MRDS" means
Two distinct things, with different requirements:
1. **Runnable** — `mrds evaluate --feature <name>` resolves and executes the feature.
2. **Visible** — the feature shows up in the dashboard.

They are sequential: a feature must be runnable and **have at least one persisted run**
before it is visible (the dashboard lists features that exist in the `runs` table —
`RunRepository.features()` = `SELECT DISTINCT feature_name FROM runs`).

## Where the bundle sits today
The wizard writes an **isolated** bundle:
```
features/<name>/feature.yaml
features/<name>/prompts/<name>/v1.yaml
features/<name>/datasets/<name>/v1.json
```
Nothing in the running platform reads it. The engine/CLI resolve features from the
**global `feature_registry`**, and the default prompt/dataset registries scan the
**shared roots** `prompts/` and `datasets/` (`DEFAULT_PROMPTS_DIR` / `DEFAULT_DATASETS_DIR`).
The bundle is in neither.

---

## Part 1 — Current blockers

| # | Blocker | Why it blocks | Anchor |
|---|---------|---------------|--------|
| **B1** | **Not registered.** No mechanism loads `feature.yaml` into the global registry. | `mrds evaluate --feature <name>` → `feature_registry.get(name)` → not found. | `features/__init__.py` `register_all()` only registers hand-coded factories. |
| **B2** | **Artifacts aren't on the discoverable paths.** Prompt/dataset live in the bundle, not in shared `prompts/`+`datasets/`. | The engine/CLI build default registries that scan the shared roots; they won't find bundle-local files. | `EvaluationEngine` defaults → `PromptRegistry.from_directory("prompts")`, `DatasetRegistry.from_directory("datasets")`. |
| **B3** | **Model resolution needs registration.** The default dataset resolver pulls a feature's `input_model`/`output_model` off the registered instance. | Even if the dataset were in shared `datasets/`, the default resolver can't resolve an unregistered feature (and would *break* loading the whole dir — the Phase-2 lesson). | `DatasetRegistry` default `model_resolver` → `feature_registry.get(name)`. |
| **B4** | **Dashboard needs a persisted run.** It lists features that appear in `runs`, not registered features. | A registered-but-never-run feature is invisible. | `RunRepository.features()`. |

**Net:** the bundle is a valid artifact, but **registration is entirely absent**, the
**artifacts are off the default paths**, and **visibility additionally requires one
evaluation run**.

---

## Part 2 — Required registration / discovery mechanisms

The smallest set of mechanisms that close the blockers, in dependency order:

1. **Spec discovery + registration (the one real new mechanism — closes B1 & B3).**
   A loader that, at registration time, scans a known **installed-specs location**,
   `load_feature_spec` + `build_from_spec` each one, and registers the resulting
   `GenericStructuredFeature` in the global `feature_registry`. This is **additive** to
   the existing `register_all()` (the deferred "global discovery" from the Phase-2 plan).
   Because the registered generic feature exposes its generated models, the **default
   dataset resolver then works** for it (B3) with no resolver/engine change.

2. **Discoverable artifact placement (closes B2).** The feature's prompt and dataset
   must live on the default paths: `prompts/<name>/v1.yaml` and `datasets/<name>/v1.json`.
   Either the wizard writes there directly, or — preferred — an explicit **install step**
   copies the bundle's prompt/dataset into the shared roots (and the spec into the
   installed-specs location). Placement + registration must happen **together** so the
   shared `datasets/` invariant holds (every dataset there resolves to a registered
   feature — otherwise default-resolver consumers break).

3. **A first evaluation run (closes B4).** Once runnable, a single
   `mrds evaluate --feature <name>` persists a run, after which the dashboard lists it.
   No new mechanism — the existing CLI path.

> Note: registration is **import-time** (`register_all` runs on `import mrds.features`).
> A long-running process must **restart** to pick up a newly installed spec — acceptable
> for an MVP, and consistent with how hand-coded features become available.

---

## Part 3 — Which parts are currently manual

Everything between "bundle written" and "feature usable" is manual or absent today:

- **Discovery/registration:** *absent.* No code loads `feature.yaml`; a developer would
  have to hand-register or hand-write a factory.
- **Artifact placement:** *manual.* Prompt/dataset must be moved from the bundle into
  shared `prompts/`+`datasets/`.
- **Process restart:** *manual.* Registration is import-time.
- **First run:** *manual.* `mrds evaluate --feature <name>` must be invoked to populate
  the DB.
- **Visibility:** *implicit/manual.* The dashboard only reflects features with runs.

So today the answer to "bundle → appears in MRDS" is: **it doesn't, without manual
engineering** — which is exactly the gap this design closes.

---

## Part 4 — Should registration be automatic, user-triggered, or admin-triggered?

| Option | Pros | Cons / risk |
|--------|------|-------------|
| **Automatic** (wizard registers on generate) | Fewest clicks. | An onboarded feature is **unvetted** (demo-grade prompt/dataset). Auto-installing into shared `prompts/`+`datasets/` that CI/nightly evals consume creates an implicit quality commitment, risks the dataset-resolver invariant, and import-time registration won't take effect without a restart anyway. **Rejected.** |
| **User-triggered** | Self-service; the onboarder activates when ready. | The onboarder may not own the feature; writes into shared, versioned locations the team governs. Fine for **local/dev**. |
| **Admin-triggered** | Deliberate gate; a maintainer reviews the bundle before it becomes a platform feature; mirrors the existing **baseline-promotion** ethos (nothing becomes "trusted" silently). | One more step. |

**Recommendation — two-stage, deliberate activation (not automatic):**
- **Onboarding (anyone):** produce a validated bundle. Self-service, low stakes.
- **Activation (deliberate):** a separate **install** step that places artifacts on the
  default paths and registers the spec.
  - **Local/dev:** *user-triggered* — an explicit `mrds feature install <bundle>` (or a
    wizard "Activate locally" action).
  - **Shared/prod:** *admin-triggered / review-gated* — installation lands via **PR
    review** (the bundle is committed; spec discovery picks it up on deploy). This matches
    the project's "deliberate promotion, never silent" principle and the earlier
    "don't merge an unvetted feature without a product decision" finding.

In short: **never automatic; explicit install — user-triggered locally, admin/review-gated
for the shared platform.**

---

## Part 5 — The smallest path (design)

```
generated bundle  (features/<name>/…)                         [done by the wizard]
        │
        ▼  INSTALL  (deliberate; user- or admin-triggered)
   ├─ copy feature.yaml  → installed-specs location (e.g. features/specs/<name>.yaml)
   ├─ copy prompt        → prompts/<name>/v1.yaml         (shared, discoverable)
   └─ copy dataset       → datasets/<name>/v1.json        (shared, discoverable)
        │   (refuse on name collision; validate the bundle first)
        ▼  REGISTER  (import-time)
   register_spec_features()  ── scans installed specs ──► build_from_spec ──► feature_registry
        │   (the one new mechanism; restart to take effect)
        ▼  RUN  (existing CLI)
   mrds evaluate --feature <name>   ──► persists a run in the DB
        │
        ▼
   Feature is RUNNABLE (CLI/engine) and VISIBLE (dashboard lists features with runs)
```

**The single new mechanism** is *spec discovery at registration time*
(`register_spec_features()` added alongside `register_all`). Everything else is artifact
placement (an install step) and a normal evaluation run.

**What stays untouched** (by design): the evaluation engine, regression detector, DB
schema, dashboard architecture, reporting, and alerting. The generic feature satisfies
the existing `Feature`/`Scorer` contracts, so once registered it flows through the
unchanged platform exactly like a hand-coded feature.

**Why this is the smallest:** it reuses the spec-driven layer end-to-end, adds **one**
import-time loader, relies on the **existing** CLI for the first run, and requires **no**
changes to any consumer of features — at the cost of (a) an explicit install step and
(b) a process restart, both acceptable for an MVP.

---

## Risks & deferrals

- **Shared-`datasets/` invariant.** Installing a dataset without registering its spec
  would break default-resolver consumers. *Mitigation:* install does placement +
  registration together; treat install as the only sanctioned activation.
- **Restart requirement.** Import-time registration means hot pickup isn't available;
  acceptable for MVP. (Dynamic re-scan is a later enhancement.)
- **Dashboard shows features only after a run.** If "appears the moment it's installed"
  is desired, that would require the dashboard to also list registered-but-unrun features
  — a dashboard change, deliberately **out of scope** here.
- **Governance.** For the shared platform, activation should be review-gated (PR), giving
  a human the chance to vet the (possibly demo-grade) prompt/dataset before the feature
  becomes a first-class, CI-evaluated citizen.
- **Versioning/uniqueness.** Install must refuse to clobber an existing feature; feature
  *iteration* (new prompt/dataset versions) is a separate follow-on flow.

> **Bottom line:** the bundle is one deliberate **install** (place artifacts + a new
> import-time spec-discovery registration) and one **evaluation run** away from being a
> fully usable MRDS feature — with no changes to any core subsystem. Activation should be
> explicit (user-triggered locally, admin/review-gated for the shared platform), never
> automatic.
