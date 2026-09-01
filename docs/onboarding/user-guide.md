# User Guide — Justice

How to use the duty-management system, organised by role. The interface is in
**Hebrew (RTL)**; this guide names each screen in Hebrew with an English gloss so
you can match the sidebar.

- [Getting started (everyone)](#getting-started-everyone)
- [The sidebar & what each role sees](#the-sidebar--what-each-role-sees)
- [Soldier (חייל)](#soldier-חייל)
- [Commander (מפקד)](#commander-מפקד)
- [Duty Manager (מנהל תורנויות)](#duty-manager-מנהל-תורנויות)
- [Admin (מנהל מערכת)](#admin-מנהל-מערכת)
- [Core concepts](#core-concepts)
- [Demo accounts](#demo-accounts)

---

## Getting started (everyone)

1. **Log in** at the system URL (locally `http://localhost:5173`). Sign in with
   your **personal number** (מספר אישי) and password.
2. **First login forces a password change.** If your account was just created or
   its password was reset, you are sent to *שינוי סיסמה* (Change password) and
   cannot use anything else until you set a new one. Passwords must be **at least
   10 characters**.
3. After that you land on **ראשי** (Home). Use the sidebar to navigate. The
   **יציאה** (Logout) button is top-right.

> Too many failed logins triggers a temporary lockout (rate limit). Wait a few
> minutes and try again, or ask a duty manager/admin to reset your password.

---

## The sidebar & what each role sees

Navigation entries appear based on your role. Everyone sees the personal items;
management items are added for commanders, duty managers, and admins.

| Sidebar item (Hebrew) | English | Soldier | Commander | Duty Manager | Admin |
|---|---|:--:|:--:|:--:|:--:|
| ראשי | Home | ✓ | ✓ | ✓ | ✓ |
| היומן שלי | My calendar | ✓ | ✓ | ✓ | ✓ |
| הבקשות שלי | My requests | ✓ | ✓ | ✓ | ✓ |
| החלפות | Swaps | ✓ | ✓ | ✓ | ✓ |
| שקיפות | Transparency | ✓ | ✓ | ✓ | ✓ |
| אנשי צוות והיררכיה | Team & hierarchy | — | ✓ | ✓ | ✓ |
| היומן של היחידה | Unit calendar | — | ✓ | ✓ | ✓ |
| אישור בקשות | Approvals | — | ✓ | ✓ | ✓ |
| הגדרות תורנויות | Duty config | — | — | ✓ | ✓ |
| ניהול תורנויות | Duty management | — | — | ✓ | ✓ |
| תבניות משמרת | Shift templates | — | — | ✓ | ✓ |
| פרופיל | Profile | ✓ | ✓ | ✓ | ✓ |

**Scope matters.** Commanders and duty managers only see and act on soldiers
**within the part of the hierarchy they govern** — a commander's commanded
node(s) and everything beneath; a duty manager's assigned node and everything
beneath. Admins act globally but stay out of duty operations by design.

---

## Soldier (חייל)

Your day-to-day surface is four screens.

### ראשי — Home
Your landing page: a greeting and quick access to the rest of the app.

### היומן שלי — My calendar
A calendar of the duties assigned to you.
- Click a date to see the duties for that day (type, location, date range).
- Use **הצג הכל** (Show all) to list every upcoming duty.

### הבקשות שלי — My requests
Two things live here:
- **Personal constraints** (בקשות אישיות) — dates you need off (e.g. an exam, a
  family event). Submit a request with a **start date, end date, and reason**.
  There is a **cap** on how many total days you may have requested across
  pending + approved future constraints (a system setting; default 15 days) — the
  form rejects requests that exceed it (*חרגת ממכסת הימים המותרת*). You can
  **cancel** (בטל בקשה) your own pending requests.
- **Exemption requests** (בקשות פטור) — request an exemption type (e.g. medical)
  for a date range. These are reviewed by your commander or duty manager.
- Your **active exemptions** are listed read-only.

Each request shows its status: **ממתין לאישור** (pending, amber), **אושר**
(approved, green), or **נדחה** (rejected, red).

### שקיפות — Transparency
The fairness scoreboard. A table of soldiers showing name, unit, enrolment date,
active days, **cumulative score** (ניקוד מצטבר) and **normalised score** (ניקוד
מנורמל). You can expand **your own row** for a breakdown (duty-day contributions
and any score adjustments); other rows are not expandable. This is how everyone
can see that effort is distributed fairly. See
[Core concepts → Scoring](#scoring-cumulative-vs-normalised).

### החלפות — Swaps

Two sections:

- **הבקשות שלי** (My requests): see your own open/pending swap postings. Cancel a
  posting any time while it's still open or awaiting approval. Use **צור בקשה**
  to post a duty-day you need covered, optionally targeting a specific peer.
- **לוח מחליפים** (Swap board): see open postings from other soldiers (ones you
  are permitted to claim). Click **אני מכסה** to offer to cover a posting. If
  manager approval is required, the request queues for both soldiers' managers; if
  not, it applies immediately and the scoreboard credits you.

### פרופיל — Profile
View your info and change your password.

---

## Commander (מפקד)

A commander is a soldier set as the `commander_id` of one or more hierarchy
nodes. You get everything a soldier has, **plus** read and approval authority over
**the subtree(s) you command**.

### אנשי צוות והיררכיה — Team & hierarchy *(read within scope)*
Browse the hierarchy tree and the soldiers under you. View their records,
exemptions, and constraints. (Structural editing — moving/renaming nodes — is a
duty-manager/admin action.)

### היומן של היחידה — Unit calendar
A calendar across the soldiers in your subtree, so you can see who is on duty
when and spot gaps or clustering.

### אישור בקשות — Approvals
Your action centre. Two tabs:
- **בקשות אישיות** (personal constraints) — approve (**אשר**) or reject (**דחה**)
  pending constraint requests from soldiers in your subtree, with an optional
  decision note (הערה).
- **בקשות פטור** (exemption requests) — approve/reject pending exemption requests.

Approving an exemption request grants the soldier the exemption for the requested
dates. A **badge** on the sidebar shows how many requests are waiting.

### Granting exemptions directly
Commanders may grant or revoke exemptions for soldiers in their subtree (e.g. a
medical exemption that maps to certain duty types). Exemptions remove a soldier
from the duty types that the exemption type covers, for the exemption's date
range.

> Commanders **do not** create or edit duty assignments, adjust scores, or edit
> duty configuration — those are duty-manager powers.

---

## Duty Manager (מנהל תורנויות)

The operational owner. A duty manager is scoped to **their assigned hierarchy
node** and everything beneath it. They have all commander abilities within scope,
plus full duty operations.

### ניהול תורנויות — Duty management
The command centre for duties:
- **Create a duty** (צור תורנות): pick a soldier, duty type, location, start/end
  date, and optional notes. A duty is a **contiguous block** of days.
- **Cancel a duty** (בטל תורנות): requires a **cancellation reason** (saved to the
  audit log).
- **Per-day override / replacement** (החלפה ליום): swap the effective soldier for
  a single day of a block, or mark a day cancelled — without breaking the block
  into pieces. This covers replacements and no-shows.
- **Score adjustment** (תיקון ניקוד): apply a manual `delta` (positive or
  negative) to a soldier's score with a **required reason** — e.g. to compensate
  for an off-system duty or correct an error.
- **Run the algorithm** (הרץ אלגוריתם): select a set of duty shifts, click "הרץ
  אלגוריתם", and the CP-SAT solver assigns eligible soldiers fairly. Review the
  proposed assignments — each can be inspected for the solver's reasoning — then
  publish or discard them. Infeasibility is surfaced with a human-readable
  explanation.

### אישור בקשות — Approvals (duty manager view)

In addition to personal-constraint and exemption-request tabs, a **החלפות** tab
shows swap requests that are waiting for managerial approval. Approve each side
(requesting soldier and covering soldier) independently; the swap applies
automatically once both sides are confirmed.

### תבניות משמרת — Shift templates

Create reusable weekly shift templates: set the duty type, location, days of the
week, time window, and default headcount. Then pick a date range, preview the
shifts that would be generated (with "חדש"/"קיים" indicators for slots already on
the calendar), and confirm. Generated shifts start empty — the algorithm fills them
on the next planning run. Templates can be set to **auto_roll** for automatic
horizon generation.

### הגדרות תורנויות — Duty config
Configure the building blocks:
- **Duty types** (סוגי תורנויות): name + **score per day** + description. The
  score per day drives the fairness scoreboard. Types can be deactivated.
- **Locations** (מיקומים): named duty locations (with an optional base).
- **Exemption types** (סוגי פטור) and their **mapping to duty types** (פוטר מ־):
  define which exemptions excuse a soldier from which duty types.

### Soldiers, exemptions, constraints, hierarchy *(within scope)*
A duty manager can also onboard soldiers, reset passwords, grant/revoke
exemptions, approve/reject requests, and edit the hierarchy structure — all
limited to their scope. See the admin section for the soldier/hierarchy
mechanics; they are the same screens, bounded by scope.

---

## Admin (מנהל מערכת)

System-level authority, **global** across the whole hierarchy. By design, the
admin handles accounts and structure, **not** day-to-day duty operations
(separation of concerns).

### אנשי צוות והיררכיה — Team & hierarchy
- **Onboard a soldier** (הוסף איש צוות): create an account with personal number,
  full name, and role, placed at a hierarchy node. A **temporary password** is
  generated and shown once (*סיסמה זמנית*); the soldier must change it on first
  login.
- **Reset a password** (אפס סיסמה): generates a new temporary password and forces
  a change on next login.
- **Assign / change roles** (תפקיד): set a soldier as soldier / commander / duty
  manager / admin. *(Role assignment is an admin-only power.)*
- **Edit the hierarchy**: add nodes (יחידה / תת-יחידה), rename them, move them
  (re-parent), delete them, and set a node's **commander** (קביעת מפקד). The four
  levels are אגף (department) → זרוע (branch) → יחידה (group) → צוות (team).
- **Remove** (הסר) a soldier — a soft delete that preserves audit history.

### Command-line admin tools
Some operations are done from the server shell rather than the UI:

```bash
cd backend
uv run python -m app.scripts.bootstrap            # create the very first admin (idempotent)
uv run python -m app.scripts.reset_password <pn>  # reset a password; prints a temp one
```

`bootstrap` reads `BOOTSTRAP_ADMIN_*` from `.env` and refuses to run again once
any admin exists. `reset_password` sets `must_change_password=True`.

---

## Core concepts

### Hierarchy & scope
Four levels, small to big: **team → group → branch → department** (צוות → יחידה
→ זרוע → אגף). Each node stores its full ancestor chain, so "scope" means "this
node and everything beneath it." A commander's scope is the node(s) they command;
a duty manager's scope is their assigned node. Admins are unscoped; soldiers have
no management scope.

### Scoring: cumulative vs. normalised
- **Cumulative score** = sum over all duty-days effectively assigned to you of
  the duty type's *score per day*, plus any manual score adjustments. Harder /
  less desirable duties carry more points per day.
- **Active days** = days from the later of the system rollout reference date and
  your unit-entry date, through today (or discharge/leave), minus full exemption
  days that overlap that interval. Legacy records without a unit-entry date use
  the system reference date. Personal constraints affect eligibility, not this
  denominator.
- **Normalised score** = cumulative ÷ active days. This is the fair comparison:
  it accounts for how long you've been around and time you were exempt. The
  שקיפות table is the shared view of this.

### Duties, blocks & overrides
A duty assignment is a **contiguous block** `(soldier, duty type, location, start
date, end date)`. A 7-day block is a single record. To handle a one-day
replacement or cancellation, the system adds a **per-day override** rather than
splitting the block — so the effective assignee for any given day is "the
override if one exists, otherwise the block's soldier."

### Exemptions vs. personal constraints
- An **exemption** (פטור) excuses a soldier from specific **duty types** (via the
  exemption-type → duty-type mapping) for a date range. Granted by a
  commander/duty manager.
- A **personal constraint** (בקשה אישית) is a soldier-requested **time off** for
  any reason, subject to a per-soldier day **cap**, and approved/rejected by a
  commander/duty manager.

### Audit trail
Every state-changing action is recorded in an append-only audit log with
before/after snapshots. Irreversible actions (cancelling a duty, score
adjustments) require a free-text reason that is stored with the audit entry.

---

## Demo accounts

These exist **only after running the seed script** (`uv run python -m
app.scripts.seed`) and are for development. All seeded users have password
`1234567890` and do not need to change it.

Personal numbers are assigned during seeding and can shift as the seed script evolves — the
seed script itself prints one example login per role at the end of a run
(`uv run python -m app.scripts.seed`), under "Demo logins". Use those exact values; don't
rely on any specific personal number written down here going stale.

The admin's personal number `1000001` is always valid — it's created deterministically by
`bootstrap.py`/`seed.py`'s special-cased admin block (`seed.py:294-317`) and won't drift.

The seed also creates duty types (morning/evening/night shift, Shabbat, holiday),
locations, three exemption types with duty-type mappings, ~30 days of duty
assignments, sample personal constraints in each status, granted exemptions, and
a couple of score adjustments — enough to exercise every screen.
