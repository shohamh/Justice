# Algorithm Deep-Dive Tab — Design Spec

**Date:** 2026-06-10  
**Branch:** l1-effort-objective worktree  
**Status:** Approved

---

## Goal

Add a **"🔬 מאחורי הקלעים"** tab to `HelpModal` that explains the L1 effort-score objective precisely and intuitively, with a math warning, every term defined, and a complete worked example. Visible to all roles — no feature flag.

---

## Where it lives

- File: `frontend/src/components/HelpModal.tsx` (in the l1-effort-objective worktree)
- Inserted into `buildTabs()` as a new entry: `{ id: "deep", label: "🔬 מאחורי הקלעים" }`
- Always shown (not gated on `gimelimEnabled` or any other flag)
- Rendered as `{activeTab === "deep" && <DeepDiveTab />}` alongside existing tabs

---

## Component: `DeepDiveTab`

A single React function component, exported only within `HelpModal.tsx`. All text is Hebrew. Direction is `rtl`.

---

## Content sections (in order)

### 0. Math warning banner

Amber banner at the top:

> ⚠️ **הסבר מתמטי** — הסעיף הזה מכיל נוסחאות. כל מושג מוסבר גם במילים פשוטות — קראו לפי הנוח לכם.

### 1. הבעיה — Why counting duties is unfair

**Intuition:** Two soldiers each did 10 duties. But one served 300 days this year and the other only 30. Are they equally loaded? No — the second one carried 10× the relative burden.

**Point:** Raw duty count ignores time served, duty weight, and unit size. We need a *share* — what fraction of the unit's total load did this soldier carry, relative to how long they were active.

### 2. ניקוד עומס — `effort_score = A_i / D_i`

**Every term defined:**

| Symbol | Hebrew name | Meaning |
|--------|-------------|---------|
| `share_q` | חלק רבעוני | Soldier's score in quarter q ÷ unit's total score in quarter q. A number between 0 and 1. |
| `active_frac_q` | שבר נוכחות | Fraction of quarter q the soldier was active (0–1). Full quarter = 1. |
| `A_i` | עומס שנצבר | `Σ(share_q × active_frac_q)` over all historical quarters. Weighted sum of shares. |
| `W_i` | היסטוריה כוללת | `Σ(active_frac_q)` over historical quarters. Sum of presence weights. |
| `C_i` | רבעון נוכחי | Always 1. Represents the current planning window. Added to denominator only — no contribution to numerator yet. |
| `D_i` | מכנה | `W_i + C_i` |
| `effort_score` | עומס רבעוני | `A_i / D_i` — the soldier's average quarterly share across all periods they were active. |

**Intuition for C:** Before any new duties are assigned, everyone's score is diluted by 1 (the upcoming quarter). This prevents veterans from coasting on past performance — every new round, they must earn their share again.

**Example:**
- Soldier served 4 full quarters, always carrying 5% of unit load.
- `A_i = 4 × 0.05 = 0.20`, `W_i = 4.0`, `C_i = 1.0`, `D_i = 5.0`
- `effort_score = 0.20 / 5.0 = 0.04` → 4%

### 3. מהמספר לשלם — `effort_offset` ו-`effort_per_milli`

CP-SAT works with integers only, not decimals. The bridge pre-computes two integer constants per soldier before handing off to the solver:

| Name | Formula | Meaning |
|------|---------|---------|
| `effort_offset` | `int(effort_score × EFFORT_SCALE)` | Historical effort score, scaled to an integer. Fixed — doesn't change during solving. |
| `unit_score_milli` | `Σ block_score(d) × 1000` for all duties in window | Total score of all duties the solver can assign, in milli-units. A constant. |
| `effort_per_milli` | `int(C_over_D / unit_score_milli × EFFORT_SCALE)` | How much one milli-unit of assigned duty score moves this soldier's effort score. |
| `C_over_D` | `C_i / D_i` | The current window's weight as a fraction of total denominator. Controls how much new duties can shift the score. |
| `EFFORT_SCALE` | `10^9` | Integer scaling factor. Converts fractions to integers without precision loss. |

**Intuition for effort_per_milli:** If a soldier has `C_over_D = 0.2`, assigning them 1 full unit of duties shifts their effort score by 20% of `1/unit_score_milli`. A veteran with large `W_i` has small `C_over_D`, so new duties move their score less — they have more "inertia."

### 4. `projected_effort` — הניקוד הצפוי לאחר שיבוץ

Inside the CP-SAT model, for each soldier `si`:

```
projected_effort[si] = effort_offset[si]
                      + effort_per_milli[si] × Σ( block_score(d) × x[di, si] )
```

**Terms:**
- `x[di, si]` — binary decision variable: 1 if duty `di` is assigned to soldier `si`, 0 otherwise. This is what the solver is choosing.
- `block_score(d)` — the score of duty `d` (duration × duty-type weight), in milli-units. A constant.
- The sum `Σ( block_score(d) × x[di, si] )` — total score of duties assigned to this soldier. A linear expression in the decision variables.

**Why this is fully linear:** `effort_per_milli` and `block_score(d)` are integer constants. Only `x[di, si]` are variables. No division, no nonlinearity. CP-SAT handles this efficiently.

**Contrast with the old objective:** The previous version used `AddDivisionEquality(norm, cum_score, active_days)` — a division constraint that is quadratic and slow. The L1 approach replaces it with a pre-computed rate coefficient.

### 5. מה זה L1? — שונות מדיאנה

**L1 vs L2:**
- **L2 (squared deviation):** `Σ(x_i − mean)²` — penalises outliers heavily. Minimising it pulls toward the *mean*. Sensitive to a single extreme value.
- **L1 (absolute deviation):** `Σ|x_i − target|` — every deviation counts equally. Minimising it pulls toward the *median*. Robust to outliers.

**Why L1 here:** If one soldier has an unusually high historical effort score (e.g., a veteran who did many duties years ago), L2 would waste solver effort trying to compensate for them. L1 lets the median absorb the outlier without distorting everyone else's assignments.

**The free `target` variable:** Rather than fixing a target in advance, the solver introduces a free integer variable `target`. It finds the value of `target` that minimises `Σ|projected_effort[si] − target|`. Mathematically, the optimal `target` is always the median of the projected efforts — the solver discovers this automatically.

### 6. המטרה הסופית — `Minimize Σ dev[si] + dist_term`

For each soldier `si`, the model creates an auxiliary variable `dev[si]` and constrains it:

```
dev[si] ≥ projected_effort[si] − target
dev[si] ≥ target − projected_effort[si]
```

These two linear constraints force `dev[si] = |projected_effort[si] − target|` (CP-SAT will drive `dev[si]` as low as possible when minimising).

The full objective:

```
Minimize  Σ dev[si]  +  dist_term
```

`dist_term` is a small penalty for pairing reserve soldiers with geographically distant primaries. It acts only as a tiebreaker — its weight is much smaller than the fairness sum.

### 7. דוגמה מספרית מלאה

**Setup:** 3 soldiers, 2 duties. Numbers are chosen for readability — production uses EFFORT_SCALE=10^9 so all integers are much larger, but the ratios are identical.

| Soldier | effort_score | effort_offset | C_over_D | effort_per_milli |
|---------|-------------|--------------|---------|-----------------|
| דן | 0.04 (4%) | 40 | 0.20 | 40 |
| יעל | 0.00 (0%) | 0 | 1.00 | 200 |
| רוני | 0.08 (8%) | 80 | 0.20 | 40 |

(Schematic: `effort_per_milli` is proportional to `C_over_D` — יעל's is 5× higher than דן's because she has no history, so `C_over_D = 1.0` vs `0.20`.)

**Duties:** משמרת א (score_milli=2500), משמרת ב (score_milli=2500). Each must be assigned to exactly one soldier.

**Candidate assignment:** משמרת א → דן, משמרת ב → רוני.

```
projected_effort[דן]   = 40 + 40 × 2500   = 40 + 100000  (scaled, illustrative)
projected_effort[יעל]  = 0  + 200 × 0     = 0
projected_effort[רוני] = 80 + 40 × 2500   = 80 + 100000
```

In practice with EFFORT_SCALE=10^9 these are large integers. The solver finds `target` = median of the three projected values, then minimises the sum of absolute gaps.

**What if יעל gets one duty instead?**

```
projected_effort[יעל]  = 0 + 200 × 2500  (much higher — יעל has C_over_D=1.0)
```

יעל's effort moves dramatically per duty because she's new (large `C_over_D`). The solver weighs this and may prefer to spread duties across דן and רוני rather than overload יעל in one shot — even though she starts at 0%.

**Takeaway:** The solver isn't simply "assign to lowest score." It considers how much each assignment moves each soldier's projected score, and picks the combination that minimises total spread.

---

## Styling

- Follows existing `HelpModal` patterns: `space-y-4 text-sm leading-relaxed` wrapper, `dir="rtl"`, dark-mode aware
- Warning banner: amber (`bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800`)
- Formula blocks: `font-mono text-xs bg-gray-100 dark:bg-gray-700 rounded p-2`
- Tables for term definitions: same card style as existing fairness tab breakdowns
- Section headers: `font-semibold text-gray-800 dark:text-gray-200` with a leading emoji
- No external dependencies — no MathJax, no mermaid (plain text formulas are sufficient)

---

## Out of scope

- No interactive sliders or live computation
- No changes to the existing "⚙️ האלגוריתם" or "⚖️ הוגנות ושקיפות" tabs
- No backend changes
