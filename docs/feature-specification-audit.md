# Feature Specification Audit — Toward Self-Service Onboarding

> **Status:** Analysis only. No code, no UI, no onboarding screens, nothing implemented.
> **Question:** what is the *minimum declarative specification* a user must supply for
> MRDS to evaluate a feature **without custom feature code per use case**?
> **Inputs:** the two validated features (Email Classifier, Support Ticket Router) and
> the earlier [multi-feature-audit.md](multi-feature-audit.md).
> **Date:** 2026-06-07.

---

## Part A — The two features, decomposed

### A.1 Email Classifier

| Aspect | Today |
|--------|-------|
| **Inputs** | `email_text: str` (single free-text field). |
| **Outputs** | `category` (enum: billing / technical / account / general), `summary` (free-text, one sentence). |
| **Scorers** | `category_match` — exact string equality on the enum field. `summary_quality` — heuristic: non-empty, ≤1 sentence, 3–40 words. |
| **Segments** | by `category` (an output enum field). |
| **Evaluation assumptions** | Deterministic, local scoring; a case **passes iff all scorers pass** (binary); structured JSON output produced by an LLM from a system prompt + few-shot; exactly one text input. |
| **Required metadata** | feature name, model, a versioned prompt, a versioned dataset (input + expected_output per case, with difficulty + notes). |

### A.2 Support Ticket Router

| Aspect | Today |
|--------|-------|
| **Inputs** | `ticket_text: str` (single free-text field). |
| **Outputs** | `category` (enum: billing / technical_support / account_access / feature_request), `priority` (enum: low / medium / high). |
| **Scorers** | `category_match` — exact equality. `priority_match` — exact equality. |
| **Segments** | by `category`. |
| **Evaluation assumptions** | Identical to email: deterministic exact-match, binary pass, structured JSON via prompt + few-shot, one text input. |
| **Required metadata** | feature name, model, versioned prompt, versioned dataset. |

---

## Part B — Common vs feature-specific

### B.1 Common across both (the generalizable skeleton)
- **One free-text input field.**
- **Structured output** = a small set of named fields, at least one **categorical (enum)**.
- **Exact-match scoring on categorical fields.**
- **Segment = one categorical output field.**
- **Binary pass = all scorers pass.**
- **Prompt shape** = system prompt + few-shot examples; the model emits JSON matching the
  output schema.
- **Dataset shape** = `[{id, input, expected_output, expected_difficulty, notes}]`.
- **The feature code itself is near-identical** — `feature.py` differs only by which
  models/scorers it names; message assembly and the LLM call are the same.

### B.2 Feature-specific (what actually varies)
- The **set of enum values** (billing/technical/account/general vs the ticket queues).
- The **number and names of output fields** (1 enum + summary vs 2 enums).
- **Which scorer applies to which field** — exact-match for enums; a *heuristic* scorer
  for the email `summary` (the one non-exact, code-only scorer in either feature).
- The **prompt text** and **few-shot examples**.
- The **dataset content** (the labeled cases).

> **Key observation:** everything that varies is **data** (field names, enum values,
> scorer choice per field, prompt, dataset) **except** the email `summary_quality`
> heuristic. The Python files (`schema.py`, `feature.py`, `scorers.py`) are
> boilerplate derivable from a declaration — they encode no logic that a spec couldn't.

---

## Part C — What could become configuration vs what still needs code

### C.1 Could become configuration (data-driven, no per-feature code)
- **Feature identity & metadata** — name, title/description, model.
- **Input fields** — names + types (`string`, later `number`/`enum`/`list`).
- **Output fields** — names + types + **enum value sets**. (A dynamic Pydantic model can
  be built from these at load time — no hand-written `schema.py`.)
- **Scorer assignment** — `{field → built-in scorer + params}`, drawn from a **scorer
  library** (see Part D.2). Exact-match, numeric-tolerance, set/F1, and simple
  text-heuristics are all parameterizable.
- **Segment field** — already config (`--segment-field` / `EvaluationConfig`).
- **Prompt** — already a versioned YAML file (config).
- **Dataset** — already a versioned JSON file (config).
- **Regression thresholds** — already config (`ThresholdConfig.per_metric`).
- **Message assembly** — for single-text-input chat features it's fully generic
  (system + few-shot + input); a generic "structured-output feature" could do this for
  any such spec with no custom code.

### C.2 Still requires custom code (today)
- **Non-library scorers** — anything beyond the built-in set (e.g. the email
  `summary_quality` heuristic, or domain-specific logic). Custom logic = custom code.
- **Graded / free-text scoring** — faithfulness, relevance, semantic similarity,
  LLM-as-judge. The architecture's `ScorerAdapter`/judge seam is **not built**
  (multi-feature-audit §3.3); until it is, RAG-style evaluation can't be declared.
- **Non-standard input handling** — multi-field inputs render fine, but features needing
  *retrieval* or special context assembly (RAG) need code in the run path.
- **Non-binary pass semantics** — a configurable "pass = score ≥ threshold" rule would
  need a small engine addition (not a redesign, but not pure config today).

---

## Part D — Proposed generic feature specification model

A declarative spec (e.g. a `feature.yaml`) from which MRDS could build the input/output
models, attach scorers, and run — **for the structured-output family** (classification,
routing, extraction, screening). Free-text/graded features need the judge seam first.

### D.1 Spec fields

| Field | Why it exists | Required? | Example values |
|-------|---------------|:---------:|----------------|
| `feature_name` | Stable id used by the registry, DB, CLI, dashboard. | **Yes** | `ticket_router` |
| `title` / `description` | Human/business framing for the dashboard (today's `FEATURE_INFO`). | No (falls back to slug) | `"Support Ticket Router"` |
| `feature_type` | Picks sensible **defaults** for scoring/segment/pass-rule. | **Yes** | `classification` · `routing` · `extraction` · `screening` · `rag_qa` |
| `model` | Which LLM to run; reproducibility. | No (defaults to settings) | `gpt-4o-mini` |
| `input_fields` | Declares the input schema → generated input model + message assembly. | **Yes** (≥1) | `[{name: ticket_text, type: string}]` |
| `output_fields` | Declares the output schema (incl. enum value sets) → generated output model + the JSON contract the prompt must satisfy. | **Yes** (≥1) | `[{name: category, type: enum, values: [billing, technical_support, account_access, feature_request]}, {name: priority, type: enum, values: [low, medium, high]}]` |
| `segment_field` | Which output field to break metrics down by. | No | `category` |
| `scoring` | Maps each scored field to a **built-in scorer** + params (Part D.2). | **Yes** (≥1) | `[{field: category, scorer: exact_match}, {field: priority, scorer: exact_match}]` |
| `pass_rule` | How per-scorer results roll up to a case pass. | No (default `all_scorers_pass`) | `all_scorers_pass` · `mean_score >= 0.7` |
| `prompt_ref` | Pointer to the versioned prompt (instructions + few-shot). | **Yes** | `prompts/ticket_router/v1.yaml` |
| `dataset_ref` | Pointer to the versioned golden dataset. | **Yes** | `datasets/ticket_router/v1.json` |
| `thresholds` | Optional per-metric regression-threshold overrides. | No | `{scorer.category_match.mean_score: {critical_rel_drop: 0.1}}` |

### D.2 Built-in scorer library (config-selectable, no per-feature code)
The unit that makes scoring declarative. Each is parameterized:

| Scorer | Field types | Params | Covers |
|--------|-------------|--------|--------|
| `exact_match` | enum / string | — | category, priority, decision. |
| `numeric_tolerance` | number | `abs` / `rel` tolerance | fit scores, confidence. |
| `set_overlap` / `f1` | list / set | — | extraction (predicted vs expected items). |
| `text_bounds` | string | `min_words`, `max_words`, `max_sentences`, `nonempty` | the email `summary_quality` heuristic, generalized. |
| `llm_judge` *(future)* | string (free-text) | rubric, threshold | faithfulness, relevance, correctness — **needs the judge seam**. |
| `semantic_similarity` *(future)* | string | threshold | answer-vs-reference closeness — **needs embeddings/adapter**. |

> With `exact_match`, `numeric_tolerance`, `set_overlap/f1`, and `text_bounds`, **both
> current features become 100% declarative** — including the email `summary_quality`
> heuristic, which generalizes to `text_bounds`.

---

## Part E — Future feature types under this spec

| Type | Output shape | Scoring | Declarable today? | Gap |
|------|-------------|---------|:-----------------:|-----|
| **Classification** (email) | enum + text | `exact_match` + `text_bounds` | **Yes** | none |
| **Routing** (ticket) | enum(s) | `exact_match` ×N | **Yes** | none |
| **Extraction** | list/struct of fields | `set_overlap`/`f1` + per-field `exact_match` | **Mostly** | nested structures need richer field types; flat extraction is fine |
| **Resume Screening** | decision(enum) + fit_score(number) [+ reasons text] | `exact_match` + `numeric_tolerance` [+ `text_bounds`] | **Yes** | multi-field input display is cosmetic; decide pass-rule (decision-only vs threshold) |
| **RAG Evaluation** | free-text answer | faithfulness / relevance / correctness | **No** | requires `llm_judge`/`semantic_similarity` (the **unbuilt** `ScorerAdapter` seam) + non-binary `pass_rule` |

**Reading:** the entire **structured-output family** (classification, routing,
extraction, screening) is reachable with *configuration + a built-in scorer library* and
**no custom code**. **RAG is the boundary** — it needs one piece of *infrastructure*
(graded/judge scoring) built once, after which RAG features also become declarable.

---

## Part F — The minimum self-service specification

> **What is the smallest set of information a user must provide for MRDS to onboard a
> new feature without custom engineering?**

For a **structured-output feature** (classification / routing / extraction / screening),
the irreducible minimum is:

1. **`feature_name`** — an id.
2. **`feature_type`** — to select defaults.
3. **`input_fields`** — at least one field (name + type).
4. **`output_fields`** — names + types, with **enum values for categorical fields**.
5. **`scoring`** — one built-in scorer per scored output field (often *inferable* from
   field type: enum→`exact_match`, number→`numeric_tolerance`).
6. **A prompt / instructions** — what the model should do (few-shot optional).
7. **A labeled dataset** — cases of `input → expected_output`.

Optional but valuable: `segment_field`, `title/description`, `model`, `pass_rule`,
`thresholds`.

### What is genuinely irreducible (cannot be defaulted away)
- **The labeled dataset.** You cannot evaluate quality without a golden set; *someone*
  must label it. This is inherent to evaluation, not a platform limitation.
- **Instructions/prompt.** What "correct" means must be expressed; a template can be
  generated from `feature_type` + enum values, but quality benefits from human authoring.

Everything else in items 1–5 is **schema-level declaration** that MRDS can turn into the
input/output models, scorer wiring, and run path **without per-feature Python** —
because, as Part B showed, the current feature code encodes no logic a spec couldn't.

### The one infrastructure prerequisite for full coverage
To extend self-service from "structured output" to **all** features (RAG included), MRDS
must first build the **judge/semantic scoring adapter** (off by default in CI,
deterministic-stubbed in tests) and a **threshold-based `pass_rule`**. That is a
*one-time platform investment*, not per-feature work — after it lands, the same
declarative spec covers graded features too.

---

## Caveats
- This audit defines the **specification**, not an implementation or UI. Realizing it
  implies a generic "spec-driven structured feature" loader + a scorer library — both
  out of scope here.
- The proposal **preserves the current architecture**: a spec-driven feature would still
  register through the existing factory seam and run through the unchanged engine,
  metrics, regression, DB, dashboard, reporting, and alerting layers — exactly as the
  hand-coded email and ticket features do today.
- Dataset/prompt remain versioned, content-hashed artifacts; the spec references them
  rather than replacing them.
