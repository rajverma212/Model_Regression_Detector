# Onboarding MVP — Smallest Implementation Plan

> **Status:** Plan only. Nothing implemented, no code modified.
> **Builds on:** [self-service-onboarding-design.md](self-service-onboarding-design.md)
> (the experience) and the completed spec-driven generation layer
> (`src/mrds/features/spec/`, Phases 1–2).
> **Date:** 2026-06-07.

## Scope
- **Families:** Classification and Routing **only**. (No RAG, Resume Screening, or
  Extraction.)
- **Why these are free:** both produce a **text input → one-or-more enum outputs** shape,
  graded by `exact_match` — which the existing scorer library and field types
  (`string`, `enum`) already cover **with zero generation-layer additions**.
- **MVP goal (and boundary):** let a user **name a feature, upload a labeled dataset,
  confirm the inferred schema, enter instructions, and produce a validated `FeatureSpec`**
  plus its prompt + dataset artifacts. Making the new feature *globally discoverable/
  runnable from the live dashboard* is an explicit follow-on (see §6).

## Architecture stance
- **A pure, UI-free core** (`src/mrds/onboarding/`) does inference, prompt scaffolding,
  assembly, validation, and artifact writing. It is fully unit-testable.
- **A thin Streamlit page** drives the wizard (file upload + confirm forms) and calls the
  core. Kept **separate from the read-only dashboard** so the dashboard's "never writes"
  invariant is preserved (onboarding *writes* artifacts).
- **Reuses** `mrds.features.spec` (`FeatureSpec`, `build_input_model/output_model`,
  `build_from_spec`, `load_feature_spec`) and the existing prompt/dataset loaders. **No**
  changes to the engine, regression detector, DB, dashboard architecture, or existing
  features.

---

## 1. Files required

### New — pure core (`src/mrds/onboarding/`)
| File | Responsibility |
|------|----------------|
| `__init__.py` | Exports; no side effects. |
| `errors.py` | `OnboardingError` for clear, surfaced failures. |
| `inference.py` | `infer_feature_spec(raw_dataset, *, feature_name, feature_type) -> FeatureSpec` — derive `input_fields`, `output_fields` (with enum value sets), `scoring` (`exact_match` per enum output), and `segment_field` (first enum output). Pure. |
| `scaffold.py` | `scaffold_prompt(spec, *, feature_type) -> str` — generate a system-prompt template enumerating the output enums and demanding strict JSON. Pure. |
| `writer.py` | `write_feature_bundle(spec, *, cases, system_prompt, root) -> BundlePaths` — write `feature.yaml`, `datasets/<name>/v1.json`, `prompts/<name>/v1.yaml` into an **isolated per-feature bundle** (the Phase-2 layout). File I/O only. |

### New — thin UI
| File | Responsibility |
|------|----------------|
| `src/mrds/onboarding/app.py` | A small Streamlit wizard: identity → upload → confirm schema → instructions → review → save. Pure presentation + calls into the core. (Run standalone; not part of the read-only dashboard.) |

### New — tests
`tests/unit/test_onboarding_inference.py`, `test_onboarding_scaffold.py`,
`test_onboarding_writer.py`, `test_onboarding_end_to_end.py`.

### Reused unchanged
`mrds.features.spec.*`, `mrds.prompts.*`, `mrds.datasets.*`, and (only in the
end-to-end test) `mrds.evaluation` + `mrds.db`.

---

## 2. Data flow

```
 uploaded dataset (JSON)        feature_name + feature_type (form)
        │                                   │
        ▼                                   ▼
  parse + validate            infer_feature_spec(...)  ──►  proposed FeatureSpec
        │                                   │                (fields, enums, scoring, segment)
        └───────────────┬───────────────────┘
                        ▼  (user confirms / edits schema on screen)
              confirmed FeatureSpec
                        │
                        ▼  scaffold_prompt(spec) → user edits → system_prompt
                        ▼
        assemble + VALIDATE  (FeatureSpec validators; every dataset case round-trips
                              through build_input_model/build_output_model; prompt non-blank)
                        │
                        ▼  write_feature_bundle(...)  →  features/<name>/feature.yaml
                                                          features/<name>/prompts/<name>/v1.yaml
                                                          features/<name>/datasets/<name>/v1.json
```

The "assemble + validate" step **reuses the generation layer**: `FeatureSpec` validation
is the spec's own validators; dataset consistency is checked by validating every case
against the generated models (no LLM needed). The written bundle is exactly the shape the
Phase-2 PoC already runs end-to-end.

---

## 3. Validation points

1. **Dataset parse** — valid JSON; ≥1 case; each case has a unique `id`, an `input`, and
   an `expected_output`; consistent keys across cases.
2. **Inference sanity** — ≥1 enum output detected (required for Classification/Routing);
   inputs resolve to text/scalar fields. Enum detection heuristic (few, repeated string
   values) is a **proposal**, surfaced for confirmation.
3. **Identity** — `feature_name` non-blank, identifier-safe, **unique** vs existing
   features and existing bundle dirs (never overwrite).
4. **Spec validity** — `FeatureSpec` validators: unique field names; enum fields have
   non-blank, de-duplicated values; every `scoring.field` is an output field;
   `segment_field` (if set) is an output field.
5. **Cross-artifact consistency** — `expected_output` keys == `output_fields`; every
   observed label ⊆ declared enum values; **every case validates against the generated
   input/output models** (the LLM-free consistency gate); `system_prompt` non-blank.
6. **Write safety** — target bundle does not already exist; artifacts written atomically
   (temp then move) so a partial failure leaves nothing half-written.

---

## 4. Risks

- **Enum vs free-text misinference.** A string output with many distinct values might be
  free text, not a category. *Mitigation:* heuristic proposes, the **confirm-schema screen
  requires the user to accept/edit**; MVP requires ≥1 enum output and only scores enums.
- **Type ambiguity** (int vs number vs string). *Mitigation:* propose, user confirms.
- **Artifact location coupling (the Phase-2 lesson).** Writing the dataset into the
  *shared* `datasets/` dir would break default-resolver consumers unless the feature is
  globally registered. *Mitigation:* write to an **isolated per-feature bundle** under
  `features/<name>/` (exactly like `sentiment_poc`). The MVP produces a valid, loadable
  bundle without touching shared dirs or global registration.
- **Name collisions / overwrite.** *Mitigation:* uniqueness check + refuse to overwrite an
  existing bundle.
- **Scope creep toward non-enum outputs / other families.** *Mitigation:* MVP explicitly
  rejects datasets whose gradeable outputs aren't enums, pointing to the deferred families.
- **UI ↔ core entanglement.** *Mitigation:* all logic in the pure core; the Streamlit page
  only collects inputs and renders results.

---

## 5. Test strategy

All core logic is pure and unit-tested; the Streamlit page is not unit-tested (consistent
with the project — logic lives in the testable core).

- **`test_onboarding_inference.py`** — feed a small classification dataset and a routing
  dataset (multi-enum) as dicts; assert the proposed `FeatureSpec`: input/output field
  names + types, enum value sets, `exact_match` scoring per enum, `segment_field` = first
  enum. Edge cases: a non-enum (free-text) output is *not* auto-scored / triggers the
  required-enum rule; numeric/bool type inference.
- **`test_onboarding_scaffold.py`** — `scaffold_prompt` returns a non-blank prompt that
  enumerates the declared enum values and is accepted by the prompt schema.
- **`test_onboarding_writer.py`** — write a bundle to `tmp_path`; assert
  `load_feature_spec`, `PromptRegistry.from_directory`, and
  `DatasetRegistry.from_directory` all succeed against it; refuse to overwrite an existing
  bundle; partial-failure leaves nothing.
- **`test_onboarding_end_to_end.py`** — the headline test: from a raw dataset + name +
  instructions, run inference → assemble → write, then **drive the written bundle through
  the engine with a deterministic stub client** (the Phase-2 pattern) and assert metrics,
  persistence, and `DashboardData` visibility. Proves the onboarding output is a genuine,
  runnable spec-driven feature.
- **Validation tests** — malformed dataset, label outside enum, duplicate ids, blank
  name/instructions, duplicate feature name → clear `OnboardingError`s.

---

## 6. Smallest path & deferrals

**Smallest usable MVP:** identity → upload dataset → confirm inferred schema → enter
instructions → **validated `FeatureSpec` + bundle written**. For Classification/Routing
this needs **no generation-layer changes** — only the new `onboarding/` core + a thin page.

**Deferred (out of the smallest path):**
- **Global discovery/registration** that makes the new feature appear in the live
  dashboard and run via the CLI without an explicit path (the Phase-2 "global wiring"
  follow-on).
- **Model-backed dry-run** during onboarding (the MVP's consistency gate is the LLM-free
  schema round-trip; a real evaluation preview is a later add).
- **Other families** (Resume Screening → `numeric_tolerance`; Extraction → `list` type +
  `set_overlap`/`f1`) and **free-text outputs** (judge scoring).
- **Feature iteration** (new prompt/dataset versions for an existing feature).

> **Bottom line:** a pure `onboarding/` core (inference + scaffold + writer + validation)
> plus a thin Streamlit wizard turns a name, a labeled dataset, and instructions into a
> validated `FeatureSpec` bundle — reusing the existing spec-driven layer, touching no core
> subsystem, and limited to the exact-match Classification/Routing families that need no
> new scorers.
