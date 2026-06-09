# Self-Service Onboarding Design

> **Status:** Design only. No implementation, no code, no framework/deployment specifics.
> This designs the **onboarding experience that produces a valid `FeatureSpec`** (plus a
> prompt and a labeled dataset) — the inputs the Phase 1–2 generation layer already
> consumes.
> **Builds on:** [feature-specification-audit.md](feature-specification-audit.md),
> [spec-driven-feature-design.md](spec-driven-feature-design.md),
> [spec-driven-implementation-plan.md](spec-driven-implementation-plan.md).
> **Date:** 2026-06-07.

## What the flow must produce
Three artifacts the platform already understands:
1. A valid **`FeatureSpec`** (`feature_name`, `input_fields`, `output_fields`, `scoring`,
   `segment_field`, …).
2. A **prompt** (system instructions + optional few-shot).
3. A **labeled dataset** (`input → expected_output` cases).

Everything below exists to fill those three with the least possible manual effort. Scope:
the **structured-output family** — Classification, Routing, Extraction, Resume Screening
(no free-text/judge scoring).

---

## Part 1 — Information classification (Q1–Q5)

The guiding move is **dataset-first inference**: once the user uploads a labeled dataset,
the system can *propose* most of the spec, so the user mostly **confirms** rather than
types.

| Information | Q1 Must provide? | Q2 Inferable? | Q3 Form | Q4 Upload | Q5 Optional? |
|-------------|:----------------:|---------------|:------:|:---------:|:------------:|
| `feature_name` | **Yes** | slug from title | ✔ | | No |
| `feature_type` (classification/routing/extraction/screening) | **Yes** | — (drives other defaults) | ✔ | | No |
| `title` / `description` | No | title ← name | ✔ | | Yes |
| `input_fields` (names, types) | **Yes** (≥1) | **from dataset** (keys + value types) | ✔ (confirm) | (derived from upload) | No |
| `output_fields` (names, types) | **Yes** (≥1) | **from dataset** (`expected_output` keys + types) | ✔ (confirm) | (derived) | No |
| enum **values** per categorical field | **Yes** (for enums) | **from dataset** (distinct labels observed) | ✔ (confirm) | (derived) | No |
| `scoring` (scorer per field) | **Yes** (≥1) | **from field type** (see §2) | ✔ (confirm/override) | | No (auto-filled) |
| scorer **params** (e.g. `text_bounds` bounds) | No | sensible defaults | ✔ (advanced) | | Yes |
| `segment_field` | No | first enum output field | ✔ (dropdown) | | Yes |
| **prompt** (system instructions) | **Yes** | **scaffolded** from type + fields + enum values | ✔ (editable) | optional file | No (but pre-filled) |
| few-shot examples | No | sampled from the dataset | ✔ | optional | Yes |
| **dataset** (labeled cases) | **Yes** | — (the irreducible) | | ✔ **required** | No |
| `model` | No | default from settings | ✔ (advanced) | | Yes |
| `thresholds` (regression overrides) | No | platform defaults | ✔ (advanced) | | Yes |
| `prompt_feature` | No | = `feature_name` | (internal) | | Yes |

**The irreducible minimum the user must supply** (cannot be inferred or defaulted):
`feature_name`, `feature_type`, the **labeled dataset**, and the **intent of the
instructions**. Everything else is either inferred from the dataset, derived from
`feature_type`/field types, or defaulted.

---

## Part 2 — Inference rules (what the system fills in)

These are the rules that let the user mostly confirm:

- **Fields & enum values ← dataset.** From the uploaded cases: input field names/types =
  keys/value-types of `input`; output field names/types = keys/value-types of
  `expected_output`; **enum values = the distinct observed labels** for each categorical
  output field. The user confirms or edits the proposal.
- **Scorer ← field type** (the default `scoring` proposal):
  - enum / string-categorical → `exact_match`
  - number → `numeric_tolerance` *(library addition required — see §6)*
  - free-text → `text_bounds`
  - list / set → `set_overlap` / `f1` *(library addition required — see §6)*
- **`segment_field` ← first enum output field** (overridable; clearable).
- **Scorer metric name ← field** (`<field>_match`, `<field>_quality`), matching existing
  conventions; user may override.
- **Prompt scaffold ← `feature_type` + output schema.** Generate a system-prompt template
  enumerating the declared categories/fields and demanding strict JSON matching the output
  schema; the user edits it. Few-shot examples can be sampled from the dataset.
- **`model`, `thresholds`, `prompt_feature` ← platform defaults.**

---

## Part 3 — User workflow (smallest path)

A short, linear wizard. Identity first, then **upload-drives-proposal**, then confirm,
then a dry-run gate.

```
1. Identity        -> feature_name + feature_type (+ optional title/description)
2. Dataset upload  -> upload labeled cases; system parses & infers fields/enums
3. Confirm schema  -> review/edit inferred input_fields, output_fields, enum values
4. Confirm scoring -> review/edit auto-proposed scorers + pick segment_field
5. Instructions    -> edit the scaffolded prompt; (optional) accept sampled few-shot
6. Review & dry-run-> see the assembled FeatureSpec; run a smoke evaluation on a sample
7. Save            -> persist spec + prompt + dataset as versioned artifacts
```

The user can also choose a **"declare-first"** variant (define fields before uploading),
but **dataset-first is the smallest path** and the recommended default, because steps 3–5
arrive pre-filled.

---

## Part 4 — Required screens (logical views, not UI tech)

For each: purpose · inputs · what's inferred/pre-filled · validation · exit criterion.

### Screen 1 — Feature identity
- **Purpose:** name the feature and pick its family.
- **Inputs:** `feature_name` (required), `feature_type` (required), `title`/`description`
  (optional).
- **Inferred:** `title` ← `feature_name`; `feature_type` seeds later defaults.
- **Validation:** name non-blank, identifier-safe, **unique vs existing features**;
  `feature_type` is one of the supported families.
- **Exit:** a valid, unique identity.

### Screen 2 — Dataset upload (the inference driver)
- **Purpose:** provide the irreducible labeled set and let the system infer the schema.
- **Inputs:** a dataset **file upload** (the labeled cases).
- **Inferred:** input/output field names + types, and enum value sets, from the cases.
- **Validation:** parseable; ≥1 case; each case has a unique `id`, an `input`, and an
  `expected_output`; consistent keys across cases.
- **Exit:** a parsed dataset + a *proposed* schema.

### Screen 3 — Confirm schema
- **Purpose:** lock the input/output fields and enum values.
- **Inputs:** confirm/edit field names, types, `required` flags, and enum `values`.
- **Inferred/pre-filled:** everything from Screen 2.
- **Validation:** ≥1 input and ≥1 output field; **unique field names**; enum fields have
  ≥1 non-blank value; non-enum fields declare no values; every observed dataset label is
  within the declared enum values.
- **Exit:** a valid set of `input_fields` + `output_fields`.

### Screen 4 — Confirm scoring & segmentation
- **Purpose:** decide how each output field is graded and how metrics segment.
- **Inputs:** confirm/override the proposed scorer per field; choose `segment_field`;
  (advanced) scorer params.
- **Inferred/pre-filled:** scorer-per-field from type; `segment_field` = first enum field.
- **Validation:** ≥1 scoring entry; each references an existing output field; **scorer is
  compatible with the field type**; `segment_field` (if set) is an output field (warn if
  not categorical).
- **Exit:** a valid `scoring` list (+ optional `segment_field`).

### Screen 5 — Instructions (prompt)
- **Purpose:** give the model its instructions.
- **Inputs:** edit the scaffolded system prompt; optionally accept dataset-sampled
  few-shot examples (or upload a prompt file).
- **Inferred/pre-filled:** prompt scaffold from `feature_type` + output schema; few-shot
  candidates sampled from the dataset.
- **Validation:** non-blank system prompt; any few-shot `output` is valid JSON that
  **validates against the output schema**; soft-lint that enum names mentioned in the
  prompt match declared values.
- **Exit:** a versioned prompt.

### Screen 6 — Review & dry-run
- **Purpose:** prove the three artifacts are mutually consistent before saving.
- **Inputs:** read-only assembled `FeatureSpec` preview; trigger a **dry-run evaluation**
  over a small sample of dataset cases.
- **Inferred:** the full spec, composed from prior screens.
- **Validation:** the dry-run produces schema-valid outputs and computable metrics with no
  validation errors (this is the consistency gate).
- **Exit:** a green dry-run → enable Save.

### Screen 7 — Save
- **Purpose:** persist the feature.
- **Inputs:** confirm.
- **Validation:** name still unique; spec re-validates.
- **Exit:** spec + prompt + dataset saved as versioned, content-hashed artifacts; the
  feature becomes available to the existing CLI/engine/dashboard.

---

## Part 5 — Per-family walkthroughs

| Family | User declares | Inferred from dataset | Scoring (proposed) | Notes |
|--------|---------------|-----------------------|--------------------|-------|
| **Classification** | name, type | one text input; one enum output + values | `exact_match` (+ `text_bounds` if a summary field) | Fully supported today. |
| **Routing** | name, type | one text input; one or more enum outputs (e.g. queue, priority) | `exact_match` per enum | Fully supported today. |
| **Resume Screening** | name, type | resume (+ JD) text inputs; decision enum + numeric fit score | `exact_match` (decision) + `numeric_tolerance` (score) | Needs `numeric_tolerance` (§6); multi-field input supported. |
| **Extraction** | name, type | document text input; a **list** of extracted items/fields | `set_overlap`/`f1` (+ per-field `exact_match`) | Needs `list` field type + set scorers (§6). |

The **flow is identical** across families; only the inferred field types and proposed
scorers differ.

---

## Part 6 — Validation rules (consolidated)

**Identity**
- `feature_name`: non-blank, identifier-safe, unique across existing features.
- `feature_type`: one of the supported families.

**Fields**
- ≥1 input field and ≥1 output field; field names unique within each list.
- Enum fields: ≥1 non-blank, de-duplicated `values`. Non-enum fields: no `values`.

**Scoring & segmentation**
- ≥1 scoring entry; each `field` exists in `output_fields`.
- Scorer ↔ field-type compatibility (e.g. `numeric_tolerance` only on numbers).
- `segment_field` (if set) is an output field; warn if not categorical.

**Dataset (the gate)**
- Parseable; ≥1 case; unique case `id`s.
- Every case `input` validates against `input_fields`; every `expected_output` validates
  against `output_fields` (enum labels within declared values).
- **Coverage warnings:** a declared enum value that never appears; a category with very few
  cases; missing/extra keys vs the declared schema.

**Cross-artifact consistency**
- `expected_output` keys == `output_fields`.
- Few-shot example outputs are valid JSON validating against the output schema.
- Dry-run over a sample produces schema-valid outputs and computable metrics.

---

## Part 7 — Smallest flow & what's deferred

**Smallest happy path (4 real decisions + 1 upload):** name → type → **upload dataset** →
confirm the inferred schema/scoring → edit the scaffolded prompt → dry-run → save.
Two of those (scoring, schema) are usually one-click confirmations.

**Deferred / prerequisites (not onboarding-flow problems):**
- Scorer-library additions for full coverage: **`numeric_tolerance`** (screening) and
  **`set_overlap`/`f1`** + a **`list` field type** (extraction). The flow already accounts
  for them; they must exist in the generation layer to actually run those families.
- **Judge/semantic scoring** for free-text/RAG features — out of this family's scope.
- Versioning/iteration of an existing feature (new prompt/dataset versions) — a follow-on
  flow; this design covers initial onboarding.

> **Bottom line:** the user must supply only an **identity**, a **family**, a **labeled
> dataset**, and the **intent of the instructions**. Dataset-first inference fills the
> rest of the `FeatureSpec`; the user confirms, edits the scaffolded prompt, and passes a
> dry-run gate — producing exactly the spec + prompt + dataset the existing platform
> already evaluates, with no Python.
