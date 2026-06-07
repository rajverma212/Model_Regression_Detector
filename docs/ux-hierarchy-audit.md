# UX Information-Hierarchy Audit

> **Status:** Analysis only — **no code changes.** This document proposes how to
> reorder what each page *already shows* so the most important answer lands first.
> **Hard constraints (per the brief):** no new features, no redesign, no architecture
> change, no navigation change, no new pages, no data-model change. Every
> recommendation uses functionality and data that **already exist** today.
> **Sources of truth:** [current-system-analysis.md](current-system-analysis.md),
> [product-audit.md](product-audit.md). **Date:** 2026-06-03.

### The single principle

Every page is restructured to the same shape:

> **Conclusion → Evidence → Details**
>
> - **Conclusion** — the one-line answer to the page's primary question, visible
>   immediately, ideally with a 🟢/🟡/🔴 verdict the system *already computes*.
> - **Evidence** — the metrics/tiles that justify the conclusion, still on screen.
> - **Details** — per-case rows, full tables, raw payloads — tucked behind
>   `st.expander`s or pushed below the fold for those who want to investigate.

The recurring problem across the app is **flat hierarchy**: a run's identity, its
verdict, and its raw case rows are all rendered at the same visual weight, so the eye
has no path. Nothing below requires new data — only moving existing elements and
wrapping some in expanders.

A note on scope: a few recommendations add a **one-line text summary of values the
page already displays** (e.g. "trending down; latest is below baseline"). This is a
comprehension aid built from existing numbers — not a new feature, metric, or data
source. Where a recommendation would surface a value computed *elsewhere* in the app
(e.g. the baseline's pass rate, already used on Runs), it is flagged explicitly and
kept optional.

---

## 1. Home

**1. Primary question:** *"What is this, and is everything healthy right now?"*
**2. Current information order:** Title → safety-net info box → (sidebar guide) →
`Features under test: N` tile → per feature: title → summary → category bullets →
4 tiles (Runs, Latest pass rate, Runs with regressions, **Health**) → health caption →
"open a page" footer.
**3. Most important:** the **Health verdict** (🟢/🟡/🔴) for each feature's latest run.
**4. Supporting evidence:** latest pass rate, runs-with-regressions count, run count.
**5. Detailed investigation data:** the category-meaning bullets; the safety-net analogy.
**6. Should move higher:** the **Health** tile and its caption — currently last of four.
**7. Should move lower:** `Features under test: N` (a count, not an answer) and the
long category bullets.
**8. Behind expanders:** the per-feature category-meaning bullets ("What the categories
mean"); optionally the safety-net explainer.
**9. Immediately visible:** feature name + health verdict + latest pass rate.

**Current Flow:** Generic framing → a low-value feature count → product description →
four equally-weighted tiles where the verdict is in the last slot.
**Problems:** The viewer reads marketing copy and a "1" before learning the actual
state. Health — the thing they came to learn — is bottom-right, same weight as a run
count. The category bullets push the tiles below the fold.
**Recommended Flow (Conclusion → Evidence → Details):**
- **Conclusion:** per feature, a heading line *"Customer Support Email Classifier —
  🔴 Blocked"* with the health caption directly under it.
- **Evidence:** the tile row, reordered to **Health · Latest pass rate · Runs with
  regressions · Runs** (verdict first, count last).
- **Details:** category-meaning bullets inside a "What it classifies" expander;
  `Features under test` demoted to a small caption or moved beside the title.
**Expected User Benefit:** a recruiter/EM learns "healthy or blocked?" in the first
second, per feature, without scrolling past framing copy.
**Implementation Complexity:** **Low** (reorder tiles; wrap bullets in an expander;
compose one heading string from existing values).

---

## 2. Runs

**1. Primary question:** *"Was this run good or bad — and if bad, why?"*
**2. Current information order:** runs table → "Inspect run" picker → 4 tiles (Pass
rate w/ vs-baseline delta, Passed, Failed, Errored) → prompt/dataset/model caption →
Scorer metrics table → Segment metrics table → weakest-segment caption → "How to reach
a perfect run" → Per-case results table → Test-log explorer (filters + `render_case`).
**3. Most important:** the verdict — pass rate **and its delta vs baseline** (good/bad).
**4. Supporting evidence:** passed/failed/errored counts; scorer and segment tables.
**5. Detailed investigation data:** the per-case results table and the test-log
explorer (every input/expected/actual).
**6. Should move higher:** the **vs-baseline verdict** (already on the pass-rate tile,
but could be stated in words); the **"perfect run" summary** (it answers "why bad?"
concisely) belongs *above* the raw per-case table.
**7. Should move lower:** the **Per-case results** table — it duplicates, less richly,
what the test-log explorer below already shows.
**8. Behind expanders:** the **Scorer metrics** and **Segment metrics** tables (evidence,
not headline); the raw **Per-case results** table.
**9. Immediately visible:** run identity (label) + pass rate + vs-baseline verdict +
"N of M cases failing."
**Current Flow:** Pick a run → tiles → two metric tables → recommendations → a flat
per-case table → then the richer explorer. Two case views (table + explorer) sit
back-to-back.
**Problems:** Strong but flat. The pass/fail verdict has no words, only a delta on a
tile. The page shows **two** per-case surfaces (the plain table and the explorer),
which is redundant and buries the explorer. Scorer/segment tables compete with the
headline.
**Recommended Flow (Conclusion → Evidence → Details):**
- **Conclusion:** under the tiles, one line — *"🔴 12 pts below baseline · 14 of 54
  cases failing"* (all values already computed: vs-baseline delta + the perfect-run
  summary).
- **Evidence:** the 4 tiles (already good); Scorer and Segment tables moved **inside
  expanders** ("Scores by check", "Scores by category") with the weakest-segment
  caption kept visible.
- **Details:** the Test-log explorer as the single case surface; the redundant flat
  **Per-case results** table folded into an "All cases (table view)" expander (or
  removed in favor of the explorer).
**Expected User Benefit:** the good/bad answer and "where to look" arrive before any
table; one canonical case browser instead of two.
**Implementation Complexity:** **Low–Medium** (reorder; wrap two tables + the flat
case table in expanders; compose one conclusion line from existing values).

---

## 3. Trends

**1. Primary question:** *"Is quality improving, holding, or sliding over time?"*
**2. Current information order:** four line charts in fixed order — Pass rate →
Scorer means → Latency → Token usage.
**3. Most important:** the **Pass-rate** trajectory and where the latest point sits.
**4. Supporting evidence:** scorer-mean trajectories (which aspect moved).
**5. Detailed investigation data:** latency and token-usage charts (cost/speed, not
the primary quality question).
**6. Should move higher:** a one-line **read of the pass-rate chart** ("latest run is
down vs the previous / below baseline") — derivable from data already plotted.
**7. Should move lower:** the **Latency** and **Token usage** charts.
**8. Behind expanders:** Latency and Token-usage charts inside a "Speed & cost"
expander; optionally scorer means inside "Quality by check."
**9. Immediately visible:** the pass-rate chart + a plain-language read of its direction.
**Current Flow:** Four equally-weighted charts; quality, speed and cost share the stage;
the viewer must interpret the line themselves.
**Problems:** No conclusion — the page shows movement but never states it. Cost/speed
charts (secondary to "is quality sliding?") get equal billing and crowd the quality
signal below the fold.
**Recommended Flow (Conclusion → Evidence → Details):**
- **Conclusion:** a caption above the first chart reading the latest movement in words
  (e.g. *"Pass rate fell from 92% to 74% over the last run."*) — composed from the
  same `TrendPoint` values already charted.
- **Evidence:** the **Pass rate** chart, then **Scorer means** (what aspect moved).
- **Details:** **Latency** and **Token usage** inside a "Speed & cost over time"
  expander.
**Expected User Benefit:** a PM sees *whether and how* quality is moving without
decoding axes, and isn't distracted by cost charts when asking about quality.
**Implementation Complexity:** **Low** (reorder charts; one expander; one text line
from existing series).

---

## 4. Compare

**1. Primary question:** *"Did run B change versus run A — better or worse, and why?"*
**2. Current information order:** two run pickers → prompt/dataset-changed attribution
caption → verdict (success/warning) → headline metric tiles → full all-metrics table.
**3. Most important:** the **verdict** (no regressions vs N critical/warning) and the
headline pass-rate Δ.
**4. Supporting evidence:** the headline metric tiles; the prompt/dataset attribution.
**5. Detailed investigation data:** the full all-metrics table (every shared metric).
**6. Should move higher:** the **verdict** line — it currently sits *after* the
attribution caption.
**7. Should move lower:** the full all-metrics table (it's the deep dive).
**8. Behind expanders:** the **All metrics** table (e.g. "All N metrics").
**9. Immediately visible:** the two run labels, the verdict, and the headline Δ tiles.
**Current Flow:** Pickers → attribution → verdict → tiles → full table. Mostly sound,
but the conclusion (verdict) trails the attribution detail, and the long table is
always expanded.
**Problems:** Minor ordering: the viewer reads "prompt unchanged · dataset unchanged"
*before* learning whether B regressed. The full table competes with the headline.
**Recommended Flow (Conclusion → Evidence → Details):**
- **Conclusion:** the verdict line first (*"🔴 5 metrics regressed from A to B"* or
  *"🟢 no regressions"*).
- **Evidence:** headline Δ tiles, then the prompt/dataset attribution caption ("why it
  may have moved").
- **Details:** the **All metrics** table inside an expander.
**Expected User Benefit:** "did my change help?" is answered before any table or
caption; attribution becomes supporting context rather than the lead.
**Implementation Complexity:** **Low** (swap two blocks; wrap the table in an expander).

---

## 5. Regressions

**1. Primary question:** *"Did this run regress, how serious, and what caused it?"*
**2. Current information order:** run (candidate) picker → impact banner (🔴/🟡) →
baseline caption → regressed-metrics table (with reasons) → root-cause section
(metric picker → reason → contributing cases via `render_case`).
**3. Most important:** the **impact banner** — would this block the deploy?
**4. Supporting evidence:** the regressed-metrics table with plain-English reasons.
**5. Detailed investigation data:** the per-metric root-cause cases (full case detail).
**6. Should move higher:** already strong — the banner leads. Optionally a one-line
"N metrics regressed; worst is X" summary beside the banner.
**7. Should move lower:** nothing major; the root-cause drill correctly sits last.
**8. Behind expanders:** the **regressed-metrics table** could collapse once the banner
+ summary convey severity, keeping the root-cause drill prominent.
**9. Immediately visible:** the blocking verdict, the baseline it was measured against,
and the count/worst regressed metric.
**Current Flow:** Banner → baseline caption → reasons table → root-cause drill. This is
the page **closest to ideal** already (it leads with the conclusion).
**Problems:** Mostly polish: the reasons table and the root-cause drill both demand
attention; on a clean run the success state is fine. The table can crowd the drill.
**Recommended Flow (Conclusion → Evidence → Details):**
- **Conclusion:** impact banner + a one-line summary ("3 metrics regressed; worst:
  general / category_match, −90.9%") composed from existing comparison values.
- **Evidence:** the regressed-metrics table (optionally inside a "All regressed
  metrics" expander).
- **Details:** the root-cause metric picker → contributing cases (unchanged).
**Expected User Benefit:** the EM gets verdict + worst offender instantly, then drills;
the table stops competing with the root-cause story.
**Implementation Complexity:** **Low** (optional expander on the table; one summary
line from existing values).

---

## 6. Baselines

**1. Primary question:** *"What is the trusted bar, and what quality does it represent?"*
**2. Current information order:** active-baseline success line (run label) → promoted-by
caption → optional note → promotion-history table.
**3. Most important:** **which run** is the baseline **and how good it is** (its quality
level).
**4. Supporting evidence:** who promoted it, when, and the note.
**5. Detailed investigation data:** the full promotion history.
**6. Should move higher:** the baseline's **quality level**. Today the page names the
baseline run but shows no sense of *how high the bar is*.
**7. Should move lower:** the promotion-history table (audit trail = detail).
**8. Behind expanders:** the **promotion history** table inside a "Promotion history"
expander.
**9. Immediately visible:** the baseline run's label **and** its headline pass rate.
**Current Flow:** Names the active baseline + provenance, then the full history table —
all flat.
**Problems:** The page establishes *that* a bar exists but not *its height*. A viewer
can't tell whether the trusted bar is 95% or 70% without leaving for Runs. History is
shown at full weight alongside the active baseline.
**Recommended Flow (Conclusion → Evidence → Details):**
- **Conclusion:** *"Active baseline: Email Classifier #1 — 94% pass rate."* The pass
  rate here uses the **existing** `baseline_pass_rate(feature)` helper already used on
  the Runs page — surfacing an existing value, not adding a feature or new data.
- **Evidence:** promoted-by / when / note.
- **Details:** the promotion-history table inside an expander.
**Expected User Benefit:** the viewer sees the *height of the bar*, not just its name —
the page's biggest comprehension gap, closed by reusing an existing computation.
**Implementation Complexity:** **Low** (reuse the existing helper for one line; wrap
history in an expander). *If reusing the existing helper is considered out of scope,
the reorder + expander alone is still Low and a net improvement.*

---

## 7. Dataset

**1. Primary question:** *"What is the feature tested on, and how well does it cover the
problem?"*
**2. Current information order:** subheader (feature · version) → description → 3 tiles
(Cases, Difficulty levels, Category values) → two distribution bar charts → filters →
cases table.
**3. Most important:** a one-line **coverage conclusion** — how many cases, spanning how
many categories/difficulties.
**4. Supporting evidence:** the distribution charts (is coverage balanced?).
**5. Detailed investigation data:** the searchable per-case table (inputs, expected,
notes).
**6. Should move higher:** nothing major; the description + tiles already lead well.
**7. Should move lower:** the per-case table (already last — correct).
**8. Behind expanders:** optionally the two distribution charts inside a "Coverage
breakdown" expander, so the case browser is closer to the fold.
**9. Immediately visible:** description + the three coverage tiles.
**Current Flow:** Description → tiles → distributions → filtered table. This page is
**already close to the ideal shape** (summary → evidence → detail).
**Problems:** Minor: the two charts can push the case table far down; the description
can be long; there's no single "54 cases, 4 categories, 3 difficulty levels, balanced"
takeaway line.
**Recommended Flow (Conclusion → Evidence → Details):**
- **Conclusion:** a one-line coverage summary above the tiles (composed from existing
  counts), e.g. *"54 hand-labeled cases across 4 categories and 3 difficulty levels."*
- **Evidence:** the three tiles; distribution charts (optionally in a "Coverage
  breakdown" expander).
- **Details:** the filter + searchable case table (unchanged).
**Expected User Benefit:** a recruiter grasps the dataset's scale and balance in one
line; the actual cases are reachable without scrolling past two charts.
**Implementation Complexity:** **Low** (one summary line; optional expander on charts).

---

## Cross-page summary

| Page | Lead today | Lead after | Key move | Complexity |
|------|-----------|-----------|----------|:----------:|
| Home | Feature count | **Health verdict** per feature | Reorder tiles; bullets → expander | Low |
| Runs | Runs table → flat tiles | **Pass/fail + vs-baseline verdict line** | Tables → expanders; one case browser | Low–Med |
| Trends | 4 equal charts | **Pass-rate read in words** | Reorder; speed/cost → expander | Low |
| Compare | Attribution → verdict | **Verdict first** | Swap two blocks; table → expander | Low |
| Regressions | Banner (already good) | Banner **+ worst-offender line** | Table → expander (optional) | Low |
| Baselines | Baseline name only | Baseline name **+ its pass rate** | Reuse existing helper; history → expander | Low |
| Dataset | Description (already good) | **One-line coverage takeaway** | Summary line; charts → expander | Low |

### Three patterns that recur

1. **Lead with the verdict the system already computes.** Health (Home), vs-baseline
   delta (Runs), comparison severity (Compare), impact (Regressions) all exist — they
   just need to be first and, where helpful, stated in one plain sentence.
2. **Demote raw tables behind expanders.** Scorer/segment tables (Runs), all-metrics
   (Compare), promotion history (Baselines), distributions (Dataset) are *evidence*,
   not headlines.
3. **One canonical detail surface.** Runs currently has two per-case views; collapsing
   to the test-log explorer removes redundancy and clarifies the Conclusion→Details path.

Every item above is a **reorder, an expander, or a one-line summary of existing values**
— no new features, pages, navigation, data models, or architecture, exactly as required.
