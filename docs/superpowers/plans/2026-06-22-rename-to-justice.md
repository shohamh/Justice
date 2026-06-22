# Rename Project: callofduty2/cod2 → justice

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename every in-repo reference to "callofduty2", "cod2", or "Call of Duty 2" to "justice" / "Justice" across config, code, migrations, and docs.

**Architecture:** Pure search-and-replace across config files, source files, and docs. The only structural complexity is the PostgreSQL database rename, which cannot run inside Alembic (you can't rename the database you're connected to), so it is a one-time manual DBA step for existing installations; fresh installs just pick up the new name from config.

**Tech Stack:** Python/FastAPI, TypeScript/Vite, PostgreSQL, Alembic, Docker Compose, GitHub Actions

---

## File Map

| File | Change |
|---|---|
| `.env` | DB URLs: `cod2` → `justice`; Telegram username |
| `.env.example` | DB URLs: `cod2` → `justice` |
| `docker-compose.yml` | `POSTGRES_DB: cod2` → `justice` |
| `.github/workflows/ci.yml` | `POSTGRES_DB: cod2` + DB URL env vars |
| `backend/alembic/versions/0001_create_app_and_admin_roles.py` | SQL string `cod2` → `justice` |
| `backend/tests/conftest.py` | `dbname="cod2"` → `justice` |
| `backend/pyproject.toml` | `name = "cod2-backend"` → `justice-backend` |
| `backend/app/main.py` | FastAPI `title=` string |
| `frontend/package.json` | `"name": "cod2-frontend"` → `justice-frontend` |
| `frontend/src/utils/icsCalendar.ts` | UID suffix `@callofduty` → `@justice` |
| `CLAUDE.md` | Project name header |
| `README.md` | Title line |
| `docs/superpowers/specs/*.md` | Bulk find-replace |
| `docs/superpowers/plans/*.md` | Bulk find-replace |

---

## Task 1: Rename database in all config and infrastructure files

**Files:**
- Modify: `.env`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Update `.env`**

Change lines 2–3 and line 19:

```
DATABASE_URL=postgresql+psycopg://app:app_pw@db:5432/justice
DB_ADMIN_URL=postgresql+psycopg://db_admin:db_admin_pw@db:5432/justice
```

And:

```
TELEGRAM_BOT_USERNAME=justicebot
```

> Note: The Telegram bot username (`justicebot`) is what the app displays — the actual bot registered with Telegram still uses the old username until you rename it manually in BotFather. Updating the env var now lets you test the rename without blocking on Telegram.

- [ ] **Step 2: Update `.env.example`**

Apply the same two DB URL line changes (lines 2–3) as in Step 1. Do not change the Telegram line (`.env.example` has no bot config).

- [ ] **Step 3: Update `docker-compose.yml`**

Find the two occurrences of `cod2` and replace both with `justice`:

```yaml
# line ~7 in the postgres service env block
POSTGRES_DB: justice

# line ~13 in the healthcheck
test: ["CMD-SHELL", "pg_isready -U db_admin -d justice"]
```

- [ ] **Step 4: Update `.github/workflows/ci.yml`**

Replace all three occurrences of `cod2`:

```yaml
# in services.postgres.env (line ~79)
POSTGRES_DB: justice

# in job-level env (lines ~89-90)
DATABASE_URL: postgresql+psycopg://app:app_pw@localhost:5432/justice
DB_ADMIN_URL: postgresql+psycopg://db_admin:db_admin_pw@localhost:5432/justice
```

- [ ] **Step 5: Verify the changes are correct**

```powershell
Select-String -Path ".env", ".env.example", "docker-compose.yml", ".github/workflows/ci.yml" -Pattern "cod2"
```

Expected: no matches.

- [ ] **Step 6: Commit**

```powershell
git add .env .env.example docker-compose.yml .github/workflows/ci.yml
git commit -m "chore: rename database from cod2 to justice in all config files"
```

---

## Task 2: Update Alembic migration SQL and test container config

**Files:**
- Modify: `backend/alembic/versions/0001_create_app_and_admin_roles.py`
- Modify: `backend/tests/conftest.py`

> **Why migration 0001 needs updating:** The migration hard-codes `GRANT/REVOKE CONNECT ON DATABASE cod2`. On fresh installs (CI, new devs, new Docker volumes) the database will be named `justice` going forward, so the migration SQL must match. For **existing local installations** with a running `cod2` database, you must run one manual SQL command before restarting (see Step 1 below).

- [ ] **Step 1: For existing local installations — rename the database manually**

From a `psql` session connected to the `postgres` default database (not `cod2`):

```sql
-- Connect as db_admin to the postgres maintenance db, then:
ALTER DATABASE cod2 RENAME TO justice;
```

Using docker exec:

```powershell
docker exec -it callofduty2-db-1 psql -U db_admin -d postgres -c "ALTER DATABASE cod2 RENAME TO justice;"
```

Skip this step if you are setting up from scratch (fresh Docker volume).

- [ ] **Step 2: Update migration 0001 SQL**

In `backend/alembic/versions/0001_create_app_and_admin_roles.py`, replace both occurrences of `cod2`:

```python
def upgrade() -> None:
    # ... role creation ...
    op.execute("GRANT CONNECT ON DATABASE justice TO app;")
    # ... rest unchanged ...

def downgrade() -> None:
    # ...
    op.execute("REVOKE CONNECT ON DATABASE justice FROM app;")
    op.execute("DROP ROLE IF EXISTS app;")
```

- [ ] **Step 3: Update `backend/tests/conftest.py` line ~164**

```python
with PostgresContainer(
    "postgres:16-alpine", username="db_admin", password="db_admin_pw", dbname="justice"
) as pg:
```

Also update the comment above it:

```python
# Match the prod database/role names so migration 0001's hardcoded
# `GRANT CONNECT ON DATABASE justice` and the 'app'/'app_pw' role line apply cleanly.
```

- [ ] **Step 4: Run the backend tests to verify the rename works end-to-end**

```powershell
cd backend
.\.venv\Scripts\activate
pytest -q -m "not slow"
```

Expected: all tests pass (same count as before).

- [ ] **Step 5: Commit**

```powershell
git add backend/alembic/versions/0001_create_app_and_admin_roles.py backend/tests/conftest.py
git commit -m "chore: rename database from cod2 to justice in migration and test fixtures"
```

---

## Task 3: Rename Python package and FastAPI app title

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Update `backend/pyproject.toml`**

Find `name = "cod2-backend"` (line ~9) and change to:

```toml
name = "justice-backend"
```

- [ ] **Step 2: Update FastAPI app title in `backend/app/main.py` line 59**

```python
app = FastAPI(
    title="Justice API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None,
    lifespan=lifespan,
)
```

- [ ] **Step 3: Verify no remaining cod2 in backend Python files**

```powershell
Select-String -Path "backend\pyproject.toml", "backend\app\main.py" -Pattern "cod2|call.of.duty" -CaseSensitive:$false
```

Expected: no matches.

- [ ] **Step 4: Commit**

```powershell
git add backend/pyproject.toml backend/app/main.py
git commit -m "chore: rename backend package and API title to justice"
```

---

## Task 4: Rename frontend npm package

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [ ] **Step 1: Update `frontend/package.json` line 2**

```json
{
  "name": "justice-frontend",
```

- [ ] **Step 2: Regenerate `package-lock.json` to pick up new name**

```powershell
cd frontend
npm install
```

This updates the two `"name": "cod2-frontend"` occurrences in `package-lock.json` automatically.

- [ ] **Step 3: Verify**

```powershell
Select-String -Path "frontend\package.json", "frontend\package-lock.json" -Pattern "cod2"
```

Expected: no matches.

- [ ] **Step 4: Commit**

```powershell
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: rename frontend npm package to justice-frontend"
```

---

## Task 5: Update ICS calendar UID

**Files:**
- Modify: `frontend/src/utils/icsCalendar.ts`

- [ ] **Step 1: Locate and update the UID line (~line 16)**

```typescript
const uid = `duty-${duty.assignment_id}@justice`;
```

> Note: Changing the UID format will cause calendar clients that already have imported duty events to treat them as new events on next import (duplicate detection is UID-based). This is acceptable for a project rename.

- [ ] **Step 2: Verify**

```powershell
Select-String -Path "frontend\src\utils\icsCalendar.ts" -Pattern "callofduty|cod2"
```

Expected: no matches.

- [ ] **Step 3: Commit**

```powershell
git add frontend/src/utils/icsCalendar.ts
git commit -m "chore: update ICS calendar UID domain from callofduty to justice"
```

---

## Task 6: Update CLAUDE.md and README.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update `CLAUDE.md` header line 1**

```markdown
# Project: justice
```

- [ ] **Step 2: Update `README.md` title (line 1)**

```markdown
# Justice — Army Duty Management System
```

- [ ] **Step 3: Verify no remaining old names in these two files**

```powershell
Select-String -Path "CLAUDE.md", "README.md" -Pattern "callofduty2|cod2|call.of.duty" -CaseSensitive:$false
```

Expected: no matches.

- [ ] **Step 4: Commit**

```powershell
git add CLAUDE.md README.md
git commit -m "docs: rename project to Justice in CLAUDE.md and README"
```

---

## Task 7: Bulk rename in docs/superpowers/ files

**Files:**
- Modify: multiple files under `docs/superpowers/`

> These are historical planning/spec documents. The rename is documentation hygiene — no functional impact.

- [ ] **Step 1: Run bulk find-replace via PowerShell**

```powershell
$files = Get-ChildItem -Path "docs\superpowers" -Recurse -Filter "*.md"
foreach ($f in $files) {
    $content = Get-Content $f.FullName -Raw -Encoding utf8
    $updated = $content `
        -replace 'callofduty2', 'justice' `
        -replace 'cod2-backend', 'justice-backend' `
        -replace 'cod2-frontend', 'justice-frontend' `
        -replace 'cod2', 'justice' `
        -replace 'Call of Duty 2', 'Justice' `
        -replace 'call_of_duty2bot', 'justicebot'
    if ($updated -ne $content) {
        Set-Content $f.FullName $updated -Encoding utf8 -NoNewline
        Write-Host "Updated: $($f.FullName)"
    }
}
```

- [ ] **Step 2: Verify the bulk replace**

```powershell
Select-String -Path "docs\superpowers\**\*.md" -Pattern "callofduty2|cod2|call.of.duty" -CaseSensitive:$false
```

Expected: no matches (or only legitimate false-positives like historical commit SHA references).

- [ ] **Step 3: Spot-check one of the changed files**

```powershell
Select-String -Path "docs\superpowers\specs\2026-06-07-ci-design.md" -Pattern "justice"
```

Expected: lines that previously said `cod2` or `callofduty2` now say `justice`.

- [ ] **Step 4: Commit**

```powershell
git add docs/
git commit -m "docs: rename callofduty2/cod2 to justice across all superpowers docs"
```

---

## Task 8: Manual / external steps (not automatable in-repo)

These require actions outside the repository. Do them after all in-repo commits are merged.

- [ ] **Step 1: Rename the GitHub repository**

Go to **https://github.com/shohamh/callofduty2 → Settings → Repository name → `justice`**.

After renaming, GitHub redirects the old URL automatically, but update your local remote:

```powershell
git remote set-url origin https://github.com/shohamh/justice.git
```

- [ ] **Step 2: Rename the working directory on disk**

Close all terminals and editors that have the directory open, then:

```powershell
Rename-Item -Path "C:\Users\Shoham\workspace\callofduty2" -NewName "justice"
```

Update VS Code workspace / any pinned shells to point to `C:\Users\Shoham\workspace\justice`.

- [ ] **Step 3: Migrate Claude Code memory files**

The memory directory `C:\Users\Shoham\.claude\projects\C--Users-Shoham-workspace-callofduty2\` is keyed by the project path. After renaming the directory, copy the memory files to the new path-keyed location:

```powershell
$old = "$env:USERPROFILE\.claude\projects\C--Users-Shoham-workspace-callofduty2"
$new = "$env:USERPROFILE\.claude\projects\C--Users-Shoham-workspace-justice"
New-Item -ItemType Directory -Force $new
Copy-Item "$old\*" $new -Recurse
```

Then open a new Claude Code session in the renamed directory to verify memory loads.

- [ ] **Step 4: Rename the Telegram bot in BotFather**

In the Telegram app, open **@BotFather** and send `/mybots` → select the bot → **Edit Bot** → **Edit Name** / **Edit Username**.

Set the username to `justicebot` (or `justice_bot` if taken). After renaming, update `.env`:

```
TELEGRAM_BOT_USERNAME=justicebot
```

Commit this final `.env` change:

```powershell
git add .env
git commit -m "chore: update Telegram bot username to justicebot"
```

- [ ] **Step 5: Push the branch and open a PR**

```powershell
git push -u origin rename-to-justice
```

Then open a PR from `rename-to-justice` → `master`.

---

## Verification checklist

After all tasks are done, run this final sweep to confirm nothing was missed:

```powershell
# In the renamed project directory (C:\Users\Shoham\workspace\justice)
Select-String -Path "." -Recurse -Pattern "callofduty2|cod2|call.of.duty" `
    -CaseSensitive:$false `
    -Exclude "*.lock", "*.pyc", "MEMORY.md" `
    | Where-Object { $_.Path -notmatch "\\.git\\" } `
    | Select-Object Path, LineNumber, Line
```

Expected: zero results (or only `.superpowers/brainstorm/` auto-generated state files, which can be ignored).
