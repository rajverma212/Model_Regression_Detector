# Adding a Feature to MRDS

> The official workflow for onboarding a new AI-powered feature into the Model
> Regression Detection System. Audience: developers adding a feature under test.
> **Validated by:** the Support Ticket Router onboarding —
> [support-ticket-router-onboarding.md](support-ticket-router-onboarding.md) — which
> added a complete second feature with **no core changes**.
> **Date:** 2026-06-06.

---

## TL;DR — the whole recipe

A new **classification-style** feature is onboarded with:

```
src/mrds/features/<name>/schema.py     # Pydantic input/output models   (required)
src/mrds/features/<name>/scorers.py    # deterministic Scorer(s)         (required)
src/mrds/features/<name>/feature.py    # Feature impl + build_feature()  (required)
src/mrds/features/<name>/__init__.py   # exports + factory               (required)
prompts/<name>/v1.yaml                 # versioned prompt                (required)
datasets/<name>/v1.json                # versioned golden dataset        (required)
```

plus **one line** in [src/mrds/features/__init__.py](../src/mrds/features/__init__.py):

```python
_FEATURE_FACTORIES = {
    "email_classifier": build_email_classifier,
    "<name>": build_<name>,          # <-- the only edit outside your feature folder
}
```

Then it runs from the CLI immediately:

```bash
mrds evaluate --feature <name> --segment-field <field>
```

**You do not touch** the evaluation engine, metrics, regression detector, database,
dashboard, reporting, or alerting. They absorb your feature through interfaces.

---

## 1. Architecture overview (what you're plugging into)

MRDS is **feature-agnostic at its core.** Everything generic depends only on two
contracts in [core/interfaces.py](../src/mrds/core/interfaces.py):

- **`Feature`** — declares input/output models, how to run one input, and which scorers
  grade it.
- **`Scorer`** — grades one actual output against the expected output, returning a
  `ScoreResult(name, score, passed, detail)`.

The flow your feature joins:

```
CLI evaluate ─► EvaluationEngine ──► for each dataset case:
                                       feature.run_with_usage(input)  -> output + tokens
                                       feature.scorers() grade it     -> ScoreResults
                                     aggregate() -> AggregateMetrics (pass/fail, per-scorer,
                                                    per-segment, latency, tokens)
                                     EvaluationStore.save_evaluation() -> SQLite
        compare ─► RegressionDetector (baseline vs candidate, dynamic metric names)
        dashboard / reports / Slack  ─► all read the same generic records
```

Key consequences:
- **Metric names are discovered dynamically** (e.g. `scorer.<your_scorer>.mean_score`).
  Add a scorer and it shows up in metrics, trends, comparison, and regression detection
  automatically.
- **Segmentation is one configurable field** (`--segment-field`), an *expected-output*
  key the engine breaks metrics down by. The engine knows nothing about it.
- **The dashboard is generic** — it lists every feature with runs and renders your
  metrics, run labels, explorer, comparison, and regressions with no page changes.

---

## 2. Required files

> Mirror [features/email_classifier/](../src/mrds/features/email_classifier/) or
> [features/ticket_router/](../src/mrds/features/ticket_router/); they are the reference
> implementations.

### 2.1 `schema.py` — input/output models
Define Pydantic v2 models. Use `Enum`/`StrEnum` for categorical fields, `extra="forbid"`,
and validators for non-empty text.

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator

class MyCategory(StrEnum):
    A = "a"
    B = "b"

class MyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v

class MyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: MyCategory
    # ... more structured fields as needed
```

### 2.2 `scorers.py` — deterministic graders
Each scorer is a pure class with a `name` and a `score(actual, expected) -> ScoreResult`.
Keep them deterministic and dependency-free.

```python
from pydantic import BaseModel
from mrds.core.interfaces import ScoreResult
from mrds.features.<name>.schema import MyOutput

def _as_output(v: BaseModel) -> MyOutput:
    if not isinstance(v, MyOutput):
        raise TypeError(f"expected MyOutput, got {type(v).__name__}")
    return v

class CategoryMatchScorer:
    name = "category_match"
    def score(self, actual: BaseModel, expected: BaseModel) -> ScoreResult:
        a, e = _as_output(actual), _as_output(expected)
        matched = a.category == e.category
        return ScoreResult(
            name=self.name,
            score=1.0 if matched else 0.0,
            passed=matched,
            detail="category matched" if matched
                   else f"expected '{e.category.value}', got '{a.category.value}'",
        )
```

> The `detail` string is **surfaced verbatim in the dashboard** (failure explanations,
> root-cause drill). Make it human-readable — it's how users learn *why* a case failed.

### 2.3 `feature.py` — the `Feature` implementation
Mirror the email/ticket feature. The essentials:

```python
class MyFeature(Feature):
    name: ClassVar[str] = "<name>"
    dataset_ref: ClassVar[str] = "<name>"

    def __init__(self, *, client=None, prompt_registry=None, ...): ...   # all lazy

    @property
    def input_model(self) -> type[BaseModel]: return MyInput
    @property
    def output_model(self) -> type[BaseModel]: return MyOutput

    def scorers(self) -> list[Scorer]:
        return [CategoryMatchScorer(), ...]

    def run_with_usage(self, payload) -> FeatureRunResult:
        # resolve prompt -> build messages -> client.parse_structured(schema=MyOutput)
        # return FeatureRunResult(output=..., input_tokens=..., output_tokens=..., total_tokens=...)

def build_feature() -> MyFeature:
    return MyFeature()
```

Rules that matter:
- **Keep construction lazy.** Registration must not need secrets, a network, or files —
  only an actual `run` does (the registry instantiates every feature at import).
- **Accept an injectable `client`.** The `StructuredLLMClient` parameter is the seam that
  lets tests and the demo run you offline (no OpenAI). Real runs lazily build the OpenAI
  client only when no client is injected and a key is present.
- **Load the prompt through the registry**, never hardcode prompt text.

### 2.4 `__init__.py` — exports + factory
Re-export your models/feature and `build_feature` so the registry and tests can import them.

### 2.5 `prompts/<name>/v1.yaml` — the prompt
Schema (validated by [prompts/models.py](../src/mrds/prompts/models.py); unknown keys are
rejected):

```yaml
version: v1                 # must match v<number>
created_at: 2026-06-06
description: >-
  One-line human summary of this prompt version.
tags: [<name>, classification]
system_prompt: |
  Clear instructions. Enumerate the exact output categories. Demand strict JSON
  matching your output schema, with no markdown fences.
few_shot_examples:          # optional but recommended
  - input: |
      <example input text>
    output: |
      {"category": "a"}     # must parse into MyOutput
```

### 2.6 `datasets/<name>/v1.json` — the golden set
Schema (validated by [datasets/models.py](../src/mrds/datasets/models.py)):

```json
{
  "version": "v1",
  "created_at": "2026-06-06",
  "description": "Human-authored golden set for <name>. N cases across ...",
  "cases": [
    {
      "id": "xx-001",
      "input": { "text": "..." },
      "expected_output": { "category": "a" },
      "expected_difficulty": "easy",
      "notes": "Why this case / what edge it covers."
    }
  ]
}
```

Authoring tips:
- `input` must validate against `MyInput`; `expected_output` against `MyOutput`. **Field
  names must match exactly** (`extra="forbid"` rejects typos).
- `expected_difficulty` ∈ `easy | medium | hard`. Case `id`s must be unique.
- Cover every category and include a few deliberate edge/ambiguous cases — the dataset is
  the ceiling on what evaluation can catch. **This is the most time-consuming step.**

---

## 3. Registry wiring (the one required edit outside your folder)

In [src/mrds/features/__init__.py](../src/mrds/features/__init__.py):

```python
from mrds.features.<name> import build_feature as build_<name>

_FEATURE_FACTORIES = {
    "email_classifier": build_email_classifier,
    "<name>": build_<name>,     # add this line
}
```

That's it. `register_all()` runs on import and your feature is now discoverable by name
from the CLI, engine, dashboard, and dataset resolver.

---

## 4. Optional files

| File | Why | Effect if omitted |
|------|-----|-------------------|
| `FEATURE_INFO["<name>"]` in [dashboard/help_text.py](../src/mrds/dashboard/help_text.py) | Business-framed title + category descriptions on the Home page. | Home falls back to the humanized slug — fully functional, just less polished. |
| A deterministic demo client + seeding in [demo/](../src/mrds/demo/) | Makes the feature appear in the **offline demo dashboard** (`MRDS_DEMO=true`) with no API key. | The feature still works against a real key / injected client; it just won't auto-populate the hosted demo. |

Neither is required for the feature to evaluate and persist.

---

## 5. Scorer creation — guidance

- **Prefer deterministic scorers** (exact match, numeric tolerance, simple heuristics).
  They're free, reproducible, and CI-safe.
- **One scorer per aspect.** Each becomes its own metric (`scorer.<name>.mean_score` /
  `.pass_rate`) and is independently tracked, compared, and regression-checked.
- **A case "passes" iff *all* its scorers pass.** Design scorers so that's the behaviour
  you want; split concerns into separate scorers rather than one mega-scorer.
- **Graded / free-text grading (e.g. RAG)** needs LLM-as-judge or semantic scoring, which
  is **not yet built** (see [multi-feature-audit.md](multi-feature-audit.md) §3.3). That's
  beyond the classification recipe — build the `ScorerAdapter` seam first.

---

## 6. Testing workflow

The OpenAI API is **always mocked** — never make real model calls in tests.

1. **Write a stub client** implementing `StructuredLLMClient.parse_structured` that returns
   a `LLMResult[MyOutput]` from an in-test oracle (see
   [tests/unit/test_ticket_router.py](../tests/unit/test_ticket_router.py) for the pattern).
2. **Unit-test the scorers** directly (match, mismatch, the `detail` string).
3. **End-to-end test** through the real pipeline, offline:
   - Build `MyFeature(client=stub, prompt_registry=...)`, register it in a fresh
     `FeatureRegistry`, build an `EvaluationEngine`, and `engine.run(EvaluationConfig(
     feature="<name>", segment_field="<field>"))`.
   - Assert metrics (pass rate, scorers discovered, segments).
   - Persist to an in-memory `EvaluationStore`, promote a baseline, run a degraded
     candidate, `RegressionDetector().compare(...)`, save it, and assert the regression.
   - Assert visibility through `DashboardData` (`features()`, `runs()`, `run_detail()`,
     `regressions_for_run()`) — this is exactly what the dashboard renders.
4. **Load datasets with the default resolver** in tests that read the real `datasets/`
   directory: `DatasetRegistry.from_directory(Path("datasets"))` — see Pitfalls.
5. **Before done:** `ruff check` + `ruff format --check` clean, and `pytest` green. Verify
   the existing features' tests still pass unchanged.

---

## 7. Common pitfalls

1. **Hardcoded dataset `model_resolver` (the big one).**
   `DatasetRegistry.from_directory` **eagerly loads every** dataset in the tree. If you
   call it with a fixed resolver — `model_resolver=lambda _f: (MyInput, MyOutput)` — it
   will try to validate *other features'* datasets against *your* models and raise
   `DatasetValidationError`. **Always use the default (registry-based) resolver:**
   `DatasetRegistry.from_directory(dir)`. It resolves each feature to its own models via
   the registry. Reserve a fixed resolver for isolated tmp-dir tests only. *(This bit the
   Ticket Router onboarding in the demo seed and two tests.)*
2. **Schema/field-name mismatches.** `extra="forbid"` means a stray or misspelled key in
   the prompt's few-shot JSON or a dataset case fails validation loudly. Keep
   `expected_output` keys identical to your `MyOutput` fields.
3. **Non-lazy feature construction.** Doing I/O, reading secrets, or building the OpenAI
   client in `__init__` breaks registration (which instantiates every feature on import).
   Keep it lazy.
4. **Forgetting `--segment-field`.** Without it, you get overall metrics but no
   per-category breakdown (and the dashboard's segment views/weakest-segment hints stay
   empty). Pass the expected-output key you want to slice by.
5. **Feature-count-specific assertions.** A second feature changes
   `store.runs.features()` from one name to a sorted list of names. Tests asserting a
   single-feature list need updating (a legitimate, one-line change).
6. **Prompt version must match `v<number>`** and the dataset/prompt `version` fields must
   be consistent; immutable per version — create `v2` rather than editing `v1`.

---

## 8. Lessons learned from the Support Ticket Router

The second feature was onboarded end-to-end (20-case dataset, two scorers) in ~2 hours,
**without touching any core subsystem**. What the exercise taught us:

- **The contracts hold.** A registry line + self-contained feature/prompt/dataset files
  was the entire *required* path. Engine, metrics, regression detector, DB, dashboard,
  reporting, and alerting needed **zero** changes.
- **Everything generic "just worked":** a second scorer (`priority_match`) was
  auto-discovered and tracked; `segment_field="category"` segmented with no engine
  awareness; and the dashboard rendered the new feature (names, explorer, comparison,
  regressions, KPIs) with no page edits.
- **The one real friction was the hardcoded resolver** (Pitfall #1), which the audit had
  predicted as a Tier-B coupling. It lived in the demo *and* two tests, and the fix was to
  use the already-existing feature-agnostic default resolver — a call-site change, not an
  architecture change.
- **The dataset is the cost, not the code.** The code files are near-mechanical mirrors;
  authoring a good golden set (coverage + edge cases) dominates the effort.
- **The demo is single-feature by construction.** Showing a feature in the *offline* demo
  requires a per-feature deterministic client + seed block — optional, and the only part
  that scales poorly today (a candidate for a future `DemoSpec` abstraction).

> **Bottom line:** if you're adding a classification feature, follow §§2–3, write the
> tests in §6, avoid the resolver pitfall in §7, and you will not need to understand or
> modify the platform's core.
