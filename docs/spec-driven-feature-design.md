# Spec-Driven Feature Design (Architecture Analysis)

> **Status:** Architecture analysis only. Nothing implemented, no code modified.
> **Builds on:** [feature-specification-audit.md](feature-specification-audit.md), which
> showed Email Classifier and Ticket Router are fully declarative.
> **Question:** could MRDS *generate* a feature from a specification instead of
> hand-written `schema.py` / `feature.py` / `scorers.py`?
> **Date:** 2026-06-07.

---

## 1. Flows: today vs proposed

### Today (per-feature Python)
There is **no `feature.yaml`** yet. Onboarding a feature means hand-writing four Python
files + two content files + one registry line:

```
features/<name>/schema.py    (hand-written Pydantic models)
features/<name>/scorers.py   (hand-written Scorer classes)
features/<name>/feature.py   (hand-written Feature impl: build messages, call LLM, parse)
features/<name>/__init__.py  (exports + build_feature factory)
prompts/<name>/v1.yaml       (content)
datasets/<name>/v1.json      (content)
features/__init__.py         (one registry line)
        │
        ▼
   feature_registry  ──►  EvaluationEngine ──► metrics / store / regression / dashboard
```

### Proposed (spec-driven)
A single declarative spec replaces the four Python files; everything downstream is
unchanged:

```
features/<name>/feature.yaml   (declares input/output fields, scoring, refs)
        │  (loaded once at startup)
        ▼
  Dynamic input/output Pydantic models   (generated)
  Dynamic Scorer instances (from a library)  (generated)
  one GenericStructuredFeature instance       (generated, implements Feature)
        │
        ▼
   feature_registry  ──►  EvaluationEngine ──► metrics / store / regression / dashboard
                                              (all unchanged)
```

The decisive architectural fact: the engine, dataset resolver, metrics, regression
detector, DB, dashboard, reporting, and alerting depend **only** on the `Feature` and
`Scorer` interfaces ([core/interfaces.py](../src/mrds/core/interfaces.py)). If a *generated*
object satisfies those interfaces, the entire platform consumes it with **no changes** —
exactly as it already absorbs the two hand-coded features.

---

## 2. Which existing code could be removed

"Removed" = no longer **hand-written per feature** (the generic path subsumes it). Subject
to the dependency caveats in §5.

| Candidate | Replaced by | Notes |
|-----------|-------------|-------|
| `features/email_classifier/schema.py`, `features/ticket_router/schema.py` | Generated input/output models from `output_fields`/`input_fields`. | The enums become dynamically-created `StrEnum`s. |
| Both `feature.py` | One shared `GenericStructuredFeature` parameterized by the spec. | The two are already near-identical; only model/scorer names differ. |
| `scorers.py` (exact-match scorers) | `exact_match` library scorer bound to a field. | Pure boilerplate today. |
| Email `summary_quality` scorer | `text_bounds` library scorer (params: `min_words=3, max_words=40, max_sentences=1, nonempty=true`). | The only non-trivial scorer; generalizes cleanly. |
| Per-feature `__init__.py` + the `_FEATURE_FACTORIES` lines | A spec-discovery loader that builds + registers a `GenericStructuredFeature` per `feature.yaml`. | The **registry mechanism stays**; only the hand-written factory entries go. |

**Not removed, just relocated:** the prompt (`vN.yaml`) and dataset (`vN.json`) remain
versioned content artifacts; the spec *references* them.

---

## 3. Which existing code must remain

Everything generic — untouched — plus the interfaces that make generation possible.

- **`core/interfaces.py`** — `Feature` (ABC), `Scorer` (Protocol), `ScoreResult`,
  `FeatureRunResult`. **The seam.** The generic feature implements `Feature`; library
  scorers implement `Scorer`. Must remain exactly as-is.
- **Evaluation engine + `metrics.py` + `scoring.py`** — call `feature.run_with_usage()`
  and `score_case(feature.scorers(), …)`; both satisfiable generically. Unchanged.
- **`datasets/` loader + registry + models** — `DatasetDefinition[Input, Output]` is
  already generic, and the **default `model_resolver` pulls `input_model`/`output_model`
  off the registered feature instance.** A `GenericStructuredFeature` that exposes its
  *generated* models means dataset validation works with **zero** dataset-layer changes.
- **`prompts/` loader + registry** — unchanged; the generic feature loads the prompt and
  assembles messages (system + few-shot + input) the same way the hand-coded features do.
- **LLM client (`StructuredLLMClient`, OpenAI client)** — `parse_structured(schema=…)`
  accepts any Pydantic model, including a generated one. Unchanged.
- **`core/registry.py`, `ids.py`, `hashing.py`, `config/settings.py`** — unchanged.
- **DB, regression detector + thresholds, reporting, alerting, dashboard, CLI** — all
  feature-agnostic already; unchanged.

> In short: **nothing in the core changes.** Spec-driven features are an *additive*
> producer of `Feature`/`Scorer` objects, not a rewrite.

---

## 4. Runtime objects that must be generated

From each `feature.yaml`, at load time:

1. **A dynamic input model** — `pydantic.create_model(<Name>Input, **fields)` from
   `input_fields` (e.g. `ticket_text: (str, Field(min_length=1))`), `extra="forbid"`.
2. **Dynamic enum types** — for each categorical output field, a `StrEnum` built from the
   declared `values` (e.g. `category` → `{billing, technical_support, …}`).
3. **A dynamic output model** — `create_model(<Name>Output, **fields)` whose categorical
   fields use the generated enums; `extra="forbid"`.
4. **Scorer instances** — one per `scoring` entry, instantiated from the **library**
   (§D.2 of the spec audit) bound to a field name + params:
   `exact_match("category")`, `exact_match("priority")`, `text_bounds("summary", …)`.
   **These read fields by name (`getattr`) on the validated output — they must not depend
   on a concrete class.**
5. **One `GenericStructuredFeature`** implementing `Feature`:
   - `name` = `feature_name`; `dataset_ref` = `feature_name`.
   - `input_model` / `output_model` = the generated models (so the dataset resolver and
     LLM parsing just work).
   - `scorers()` = the generated scorer list.
   - `run_with_usage()` = generic: resolve prompt, build messages from `input_fields`,
     `client.parse_structured(schema=generated_output_model)`, return usage.
6. **Registration** — register that instance under `feature_name` (same registry,
   different producer).

A design-level reproducibility object also belongs here: a **content hash of the spec**
(like the existing prompt/dataset hashes), so "the feature definition changed" is
trackable. (Surfacing it on the run record is a separate schema decision — noted as a
risk, not a requirement for a first cut.)

---

## 5. Risks

1. **Dynamic models defeat static typing.** Generated models are opaque to mypy/IDEs;
   hand-written guarantees (and tests asserting concrete types/enums) are lost. *Mitigation:*
   library scorers operate on field **names**, not concrete classes; validate output
   against the generated model (the LLM client already does) before scoring.
2. **`isinstance`-based scorers won't translate.** Today's scorers do
   `isinstance(actual, EmailClassificationOutput)`. Generic scorers must be
   **field-name/`getattr`-based**. This is a real behavioral shift to design for.
3. **Spec ↔ prompt ↔ dataset drift.** The prompt must emit JSON matching the generated
   schema, and dataset `expected_output` values must lie within declared enums.
   *Mitigation:* validate dataset cases against the generated output model at load
   (DatasetRegistry already validates) and lint the prompt's few-shot JSON against it.
4. **OpenAI structured-output compatibility.** The structured-output path derives a JSON
   schema from the Pydantic model; dynamically-created models *should* work, but this must
   be verified (a known unknown).
5. **Expressiveness ceiling / config-cramming.** Anything beyond the library (custom
   heuristics, judge/semantic scoring) can't be declared. *Mitigation:* keep a **code
   escape hatch** — custom features still register via the existing factory path, so
   spec-driven and code-driven features **coexist**. Resist pushing real logic into YAML.
6. **Reproducibility/versioning.** The feature definition becomes data; without hashing +
   versioning it, run provenance is incomplete. *Design decision*, not free.
7. **Demo/test coupling.** The demo clients and several tests import concrete classes
   (`EmailClassificationOutput`, `TicketRoutingOutput`, `EmailCategory.BILLING`). Migrating
   removes those classes → demo + tests must construct/assert via the generated models (by
   feature name → `output_model`). Risk of breaking the very validation evidence; needs a
   migration plan.
8. **Debuggability.** Stack traces and validation errors reference generated classes;
   less obvious than hand-written ones.

None of these touch the core; they are properties of the **generation layer** and its
boundary with the demo/tests.

---

## 6. Could Email Classifier and Ticket Router be migrated completely?

**Yes — both are fully expressible**, contingent on the scorer library including
`text_bounds`.

| Feature | Inputs | Outputs | Scoring (library) | Fully declarable? |
|---------|--------|---------|-------------------|:-----------------:|
| **Ticket Router** | `ticket_text: string` | `category: enum`, `priority: enum` | `exact_match` ×2 | **Yes — 100%** |
| **Email Classifier** | `email_text: string` | `category: enum`, `summary: string` | `exact_match` + `text_bounds` | **Yes — 100%** (summary heuristic → `text_bounds`) |

**Conditions for *complete* removal of the hand-coded packages** (not just functional
parity):
- **Scorer-library parity** — `exact_match` and `text_bounds` must reproduce the existing
  scorers' behavior (including the `summary_quality` word/sentence bounds) exactly.
- **Demo migration** — `DeterministicEmailClient` / `DeterministicTicketRouterClient`
  construct concrete output classes; they'd construct the generated `output_model`
  (resolved by feature name) instead.
- **Test migration** — tests importing `EmailCategory`, `EmailClassificationOutput`, etc.
  would shift to generated models or string values.
- **Parity (golden) test** — prove a generated feature yields **byte-identical**
  `AggregateMetrics` to the hand-coded one over the same dataset, before deleting code.

With those, both packages could be deleted and replaced by two `feature.yaml` specs plus
the shared generic machinery.

---

## 7. Architecture verdict & recommended boundaries

- **Feasible with zero core changes.** The `Feature`/`Scorer` interfaces are the exact
  seam needed; a generation layer is an *additive producer* of those objects.
- **Coexistence, not replacement.** Keep the code-defined path (factory registration) as
  the **escape hatch** for features the library can't express (custom scorers, and —
  once built — judge/semantic scoring). Spec-driven handles the structured-output family;
  code-driven handles the rest. The registry hosts both.
- **The generation layer is the new, isolated risk surface** — dynamic models, the scorer
  library, and spec↔prompt↔dataset validation. Contain it; don't let it leak typing or
  logic concerns into the core.
- **Two prerequisites for "complete" coverage** (from the spec audit, restated): a
  **built-in scorer library** (`exact_match`, `numeric_tolerance`, `set_overlap/f1`,
  `text_bounds`) for the structured family, and — separately, later — the **judge/semantic
  adapter** for RAG-style graded features.
- **Versioning:** treat the spec as a first-class, content-hashed artifact alongside
  prompts and datasets, so feature-definition changes are tracked for reproducibility.

> **Bottom line:** MRDS can generate features from a specification by adding a thin
> generation layer that emits `Feature`/`Scorer` objects from a `feature.yaml`. The core
> stays untouched; Email Classifier and Ticket Router are both fully migratable once a
> small scorer library exists; and a code escape hatch should remain for everything the
> declarative model can't yet express.
