# Unified Platform Flow (UX Design)

> **Status:** Design only (Task 1). No code in this document.
> **Goal:** turn four working-but-disconnected systems (onboarding wizard, activation,
> evaluation engine, dashboard) into one continuous experience:
> **Create → Activate → Evaluate → View Results** — with no tool-switching and no need to
> know internal MRDS concepts.
> **Constraint:** do not modify the evaluation engine, regression detector, DB schema,
> reporting, or alerting. Preserve all existing behavior.
> **Date:** 2026-06-10.

## 1. Current flow & where users get stuck

```
Onboarding wizard (separate app)            Dashboard (separate app)
  1 Identity → 2 Upload → 3 Schema             Home · Runs · Trends · Compare ·
  → 4 Prompt → 5 Generate Bundle  ⟂            Regressions · Baselines · Dataset
        │
        ▼
   "Bundle generated."   ← DEAD END
```

**The wall is at "Generate Bundle."** The wizard tells the user a bundle was written and
stops. To go further the user must, on their own, **know internal concepts and switch
tools**:
- *that activation exists* and run an install (place artifacts + register the spec),
- *that a first evaluation is needed* and invoke `mrds evaluate --feature <name>` from a
  terminal,
- *that the dashboard is a separate app* and open it to see results.

None of this is surfaced. The four systems work, but the **seams between them are the
user's problem**.

### What the user needs immediately after bundle generation
- Confirmation: "**<feature>** is ready" (in their words, not "bundle").
- The **next action**, one click away: *Activate*.
- After activating: the next action, *Run a first evaluation*.
- After evaluating: **results, in context** (a summary) + a way into the dashboard.
- Throughout: plain language — never "registry", "resolver", "spec", "install path".

## 2. Automatic vs deliberate

| Action | Decision | Why |
|--------|----------|-----|
| Place artifacts + register the feature (**Activate**) | **User-triggered** (one click) | Writes into the platform; per [post-onboarding-flow.md](post-onboarding-flow.md), activation is deliberate, never silent. But it's *one click*, not a manual multi-step chore. |
| Registering the just-installed feature **into the running process** | **Automatic** (part of the Activate click) | An internal mechanic the user shouldn't think about; folded into "Activate". |
| **Run first evaluation** | **User-triggered** (one click) | It calls the model and **costs money/time**; the user opts in. Offered immediately after activation. |
| Show a **results summary** after the run | **Automatic** | Results should appear in context, not require navigating away. |
| Deep-dive monitoring (Runs/Trends/Compare/Regressions) | **User-triggered** | The dashboard's ongoing job; reached via a clear link. |

Principle: **automate the mechanics; keep the commitments (write to platform, spend on a
model) one deliberate click each.**

## 3. The five questions, answered

1. **What happens after Generate Bundle?** The wizard *continues* into a lifecycle: it
   confirms the feature is ready and presents **Activate** as the next step — no dead end.
2. **Automatic or user-triggered activation?** **User-triggered**, one click. The
   internal registration is automatic within that click.
3. **When does the first evaluation run?** **Immediately offered after activation**, on a
   deliberate **Run first evaluation** click (it costs an LLM call). It runs **in-process**
   using the just-activated artifacts and persists a run.
4. **How does the user reach results?** Two ways, in order of immediacy: (a) an **inline
   results summary** shown by the wizard right after the run (pass rate, per-category
   counts), and (b) a **"View in dashboard"** link to the Runs page for full monitoring.
5. **How should onboarding and the dashboard relate?** Two surfaces, **bidirectionally
   linked**, with a clear division of labor: the **wizard owns the creation lifecycle**
   (create → activate → evaluate → first results); the **dashboard owns ongoing
   monitoring**. The wizard links into the dashboard; the dashboard's home links back to
   "create a feature". (A full single-app merge is possible later but is **not necessary**
   for continuity — see §5.)

## 4. The designed flow (smallest that feels like one platform)

The wizard gains three post-generation stages; everything stays in **one place** until the
user chooses to monitor in the dashboard:

```
 CREATE                          ACTIVATE                 EVALUATE                  VIEW
 1 Identity                      6 Activate               7 Run first              Results summary
 2 Upload dataset      ─────►    (one click:      ─────►   evaluation     ─────►   (inline) +
 3 Review schema                  install + register)      (one click)             "Open dashboard ▸"
 4 Review/edit prompt
 5 Generate bundle
```

- **Step 6 — Activate (deliberate, 1 click).** "Make **<feature>** available." Behind the
  scenes: install the bundle into the platform and register it. Plain-language success:
  "<feature> is now part of MRDS."
- **Step 7 — Run first evaluation (deliberate, 1 click).** "Score **<feature>** against
  its examples now." Runs in-process; on completion shows a **summary** (pass rate,
  passed/failed, per-category). If no model key is configured, the button is disabled with
  a one-line explanation and the exact CLI fallback — the flow degrades gracefully, never
  dead-ends.
- **View results.** The summary is right there; a **"View in dashboard ▸"** link opens the
  Runs page for the new feature. The dashboard home gains a small **"➕ Onboard a feature"**
  pointer back to the wizard.

**No internal concepts surface** to the user: they see *Create → Activate → Evaluate →
Results*, in one wizard, with one link out to monitoring.

## 5. Why not merge the two apps (for now)

A single multipage app (onboarding as a dashboard page) is the eventual "one URL" ideal,
but it is **not necessary** for the continuity this task targets, and it carries real cost:
the dashboard is read-only and cached (`@st.cache_resource`, demo-seeding); folding a
*writing* wizard into it muddies that contract and risks the demo. The **smallest** design
that removes the discontinuity is the in-wizard lifecycle (§4) plus bidirectional links —
the user never has to *find* the next step or open a terminal. Full merge is recorded as a
deliberate future option, not a v1 requirement.

## 6. Testability note (shapes the implementation)

A real first evaluation requires an LLM call. To keep the lifecycle **testable without a
key**, the activation+evaluation logic must live in a **pure, UI-free helper** with an
**injectable client** (the engine itself is unchanged and merely *used*). The wizard is a
thin caller; the demonstration and tests drive the same helper with a deterministic stub.

> **Bottom line:** the wizard continues past "Generate Bundle" into **Activate** (1 click)
> → **Run first evaluation** (1 click) → an **inline results summary** with a link into the
> dashboard. Mechanics are automated; the two commitments (write-to-platform, spend-on-model)
> are one deliberate click each. Onboarding and dashboard stay cross-linked surfaces with a
> clear division of labor.
