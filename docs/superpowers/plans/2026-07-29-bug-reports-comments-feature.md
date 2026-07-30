# Bug Reports: Won't-Fix Status + Comments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the bug-report list row-click bug, add a "won't fix" status, and add a comment thread on each bug report (reporter + admins can post comments, comments can carry an attached screenshot image).

**Architecture:** Add `"wont_fix"` to the existing Postgres `bug_report_status` enum and the three backend/frontend places that hardcode the status literal. Add a new `BugReportComment` table (comment body + author) and a `BugReportCommentAttachment` table (binary image data), following the exact same shape as the existing `ExemptionRequestFile` model and its upload/list/download route trio — this is a proven, already-used pattern in this codebase, not a new one. Add a detail view (the bug-reports admin list currently only has an inline expand row, no detail page) where the thread renders; reporters need a new `GET /my/bug-reports` endpoint since none exists today for them to see their own reports' comments.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Pydantic (backend), React/TypeScript (frontend), pytest, vitest.

## Global Constraints

- Hebrew UI strings only for new text — add to `frontend/src/i18n/he.json`.
- Attachment images follow the existing app convention: stored as `LargeBinary` directly in Postgres (matching `ExemptionRequestFile`/`GimelimAttachment`), not on a filesystem — do not introduce a new storage mechanism.
- Reuse `_magic_bytes_match` validation pattern from `backend/app/routes/exemption_requests.py` for uploaded comment images; cap at a reasonable size (follow the existing 10 MB cap used for exemption files, or the existing 5 MB cap already used for the bug report's own screenshot — pick 5 MB for consistency with bug-report screenshots specifically).
- Run `pytest -m misc -q` (or whatever marker covers `bug_reports` tests — confirm via `pytest --markers` / existing test file marker decoration before running) after backend changes.

---

## File Structure

- **Modify:** `frontend/src/pages/admin/BugReportsContent.tsx` — fix row-click bug; add "won't fix" status option; add link/button to open the new detail view.
- **Modify:** `frontend/src/api/bugReports.ts` — add `"wont_fix"` to `BugReportStatus`; add comment/attachment API functions; add `getMyBugReports`.
- **Modify:** `backend/app/db/models.py` — extend `bug_report_status` enum; add `BugReportComment`, `BugReportCommentAttachment` models.
- **Create:** `backend/alembic/versions/<rev>_add_bug_report_wont_fix_and_comments.py` — migration.
- **Modify:** `backend/app/routes/bug_reports.py` — extend status literals; add comment CRUD + attachment upload/download endpoints; add `GET /my/bug-reports`.
- **Create:** `frontend/src/pages/admin/BugReportDetailModal.tsx` — new detail modal showing full report + comment thread, reusable by both admin and reporter views.
- **Modify:** `frontend/src/pages/admin/BugReportsContent.tsx` — open `BugReportDetailModal` instead of (or alongside) the inline expand row.
- **Create:** `frontend/src/pages/MyBugReportsPage.tsx` (or a section in an existing "my requests" page — check `frontend/src/pages/MyRequestsPage.tsx` first for whether bug reports belong there) — reporter's own view of their reports + comments.
- **Test:** `backend/app/routes/tests/test_bug_reports.py`, `frontend/src/pages/admin/BugReportsContent.test.tsx` (new, for the row-click fix).

---

### Task 1: Fix row-click bug on the bug-reports list

**Files:**
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx:219-249`
- Test: `frontend/src/pages/admin/BugReportsContent.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Check whether a testing-library setup already exists for a similar table component in this codebase (search for `@testing-library/react` usage in an existing `.test.tsx` file) to match conventions. Add:

```tsx
// frontend/src/pages/admin/BugReportsContent.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import BugReportsContent from "./BugReportsContent";

// Mock the API module — match the existing mocking pattern used in other
// *.test.tsx files in this repo (check one first for the exact vi.mock shape).
vi.mock("../../api/bugReports", () => ({
  listBugReports: vi.fn().mockResolvedValue({ items: [{
    id: "r1", created_at: new Date().toISOString(), severity: "low", status: "open",
    description: "test bug", user_snapshot: { full_name: "Test User" },
  }], total: 1 }),
}));

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("BugReportsContent row click", () => {
  it("expands the row when clicking the status cell's empty padding area", async () => {
    renderWithClient(<BugReportsContent />);
    const statusCell = await screen.findByTestId("bug-report-row-r1");
    // Click near the status <select>'s cell but not directly on the <select> itself.
    const statusTd = statusCell.querySelector("td:nth-child(4)") as HTMLElement;
    fireEvent.click(statusTd);
    expect(await screen.findByText("test bug")).toBeInTheDocument();
  });
});
```

(Adjust selectors/mocks to match the real component's actual query-key/data-shape conventions — read `BugReportsContent.tsx` fully before finalizing this test, since the investigation only saw a partial excerpt.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/admin/BugReportsContent.test.tsx`
Expected: FAIL — clicking the status `<td>` padding doesn't expand the row (description text not found)

- [ ] **Step 3: Fix — move `stopPropagation` onto the `<select>` itself**

```tsx
// BEFORE (BugReportsContent.tsx:231-247)
<td className="p-2" onClick={(e) => e.stopPropagation()}>
  <select
    value={report.status}
    ...
  >
    ...
  </select>
</td>
```

```tsx
// AFTER
<td className="p-2">
  <select
    value={report.status}
    onClick={(e) => e.stopPropagation()}
    ...
  >
    ...
  </select>
</td>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/admin/BugReportsContent.test.tsx`
Expected: PASS

- [ ] **Step 5: Manually verify in the running app**

Start `.\dev.ps1`, log in as admin, go to bug reports admin tab, click within the status column's padding (not on the dropdown itself) on a row, confirm it expands; click directly on the status dropdown, confirm it does NOT expand the row and the dropdown still opens/works normally.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/admin/BugReportsContent.tsx frontend/src/pages/admin/BugReportsContent.test.tsx
git commit -m "fix: clicking anywhere in a bug-report row's status cell now expands the row correctly"
```

---

### Task 2: Add "won't fix" status

**Files:**
- Modify: `backend/app/db/models.py:1235-1238` (`BugReport.status` enum)
- Modify: `backend/app/routes/bug_reports.py:94, 120` (status literals)
- Modify: `frontend/src/api/bugReports.ts:5` (`BugReportStatus` type)
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx:24` (`STATUS_LABELS`) and the two `<select>`s at lines 186-196, 232-241
- Test: `backend/app/routes/tests/test_bug_reports.py`

- [ ] **Step 1: Write the failing test**

Read `backend/app/routes/tests/test_bug_reports.py` (create if it doesn't exist, matching conventions of a sibling routes test file) for fixture style. Add:

```python
def test_update_bug_report_status_to_wont_fix(client, admin_token, make_bug_report):
    report = make_bug_report()
    resp = client.patch(
        f"/admin/bug-reports/{report.id}",
        json={"status": "wont_fix"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "wont_fix"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/routes/tests/test_bug_reports.py -k "wont_fix" -v`
Expected: FAIL — 422 (literal not allowed) or enum error

- [ ] **Step 3: Add the DB enum value via migration**

First confirm there is exactly one migration head (this repo's history has several branch-merge migrations from past collisions — don't add another):

Run: `cd backend && alembic heads`
Expected: exactly one line. If more than one, stop and resolve before proceeding.

Run: `cd backend && alembic revision -m "add wont_fix to bug_report_status"`

```python
def upgrade() -> None:
    op.execute("ALTER TYPE bug_report_status ADD VALUE IF NOT EXISTS 'wont_fix'")


def downgrade() -> None:
    pass  # Postgres doesn't support removing enum values; downgrade is a no-op.
```

Run: `cd backend && alembic upgrade head`

- [ ] **Step 4: Update the SQLAlchemy model enum**

```python
# backend/app/db/models.py:1235-1238
status: Mapped[str] = mapped_column(
    Enum("open", "in_progress", "resolved", "wont_fix", name="bug_report_status"),
    server_default="open", default="open",
)
```

- [ ] **Step 5: Update the route literals**

In `backend/app/routes/bug_reports.py`:
- Line 94 (`UpdateBugReportStatusBody.status`): `Literal["open", "in_progress", "resolved", "wont_fix"]`
- Line 120 (`status_filter` query param): `Literal["open", "in_progress", "resolved", "wont_fix"] | None`

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest app/routes/tests/test_bug_reports.py -k "wont_fix" -v`
Expected: PASS

- [ ] **Step 7: Update the frontend type and labels**

```ts
// frontend/src/api/bugReports.ts:5
export type BugReportStatus = "open" | "in_progress" | "resolved" | "wont_fix";
```

```tsx
// frontend/src/pages/admin/BugReportsContent.tsx:24
const STATUS_LABELS: Record<BugReportStatus, string> = {
  open: "פתוח",
  in_progress: "בטיפול",
  resolved: "טופל",
  wont_fix: "לא יטופל",
};
```

Add `"wont_fix"` as an `<option>` in both `<select>`s (status filter at lines 186-196, per-row status at lines 232-241) — mirror the existing `<option>` pattern for the other three values in each.

- [ ] **Step 8: Manually verify in the running app**

Start `.\dev.ps1`, log in as admin, open bug reports, set a report's status to "לא יטופל" via the row dropdown, confirm it saves and the filter dropdown can filter to it too.

- [ ] **Step 9: Commit**

```bash
git add backend/app/db/models.py backend/app/routes/bug_reports.py backend/alembic/versions/ frontend/src/api/bugReports.ts frontend/src/pages/admin/BugReportsContent.tsx backend/app/routes/tests/test_bug_reports.py
git commit -m "feat: add won't-fix status for bug reports"
```

---

### Task 3: Backend — comment + attachment data model and endpoints

**Files:**
- Modify: `backend/app/db/models.py` — add `BugReportComment`, `BugReportCommentAttachment` (after the `BugReport` class, ~line 1250)
- Create: `backend/alembic/versions/<rev>_add_bug_report_comments.py`
- Modify: `backend/app/routes/bug_reports.py` — add comment/attachment endpoints
- Test: `backend/app/routes/tests/test_bug_reports.py`

**Interfaces:**
- Produces: `POST /bug-reports/{report_id}/comments` (any authenticated user who is either the reporter or an admin), `GET /bug-reports/{report_id}/comments` (same access), `POST /bug-reports/{report_id}/comments/{comment_id}/attachments` (multipart upload, same access, comment author only), `GET /bug-reports/{report_id}/comments/{comment_id}/attachments/{attachment_id}` (download).

- [ ] **Step 1: Write the failing test**

```python
# backend/app/routes/tests/test_bug_reports.py
def test_reporter_can_post_comment_on_own_bug_report(client, soldier_token, make_bug_report):
    report = make_bug_report(reporter_token=soldier_token)  # adjust to match actual fixture shape
    resp = client.post(
        f"/bug-reports/{report.id}/comments",
        json={"body": "steps to reproduce: ..."},
        headers={"Authorization": f"Bearer {soldier_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["body"] == "steps to reproduce: ..."

def test_other_soldier_cannot_comment_on_someone_elses_bug_report(client, other_soldier_token, make_bug_report):
    report = make_bug_report()
    resp = client.post(
        f"/bug-reports/{report.id}/comments",
        json={"body": "not mine"},
        headers={"Authorization": f"Bearer {other_soldier_token}"},
    )
    assert resp.status_code == 403

def test_admin_can_comment_on_any_bug_report(client, admin_token, make_bug_report):
    report = make_bug_report()
    resp = client.post(
        f"/bug-reports/{report.id}/comments",
        json={"body": "looking into it"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
```

(Fixture names like `soldier_token`/`other_soldier_token`/`admin_token`/`make_bug_report` must match whatever conftest fixtures already exist in this test module or its parent conftest — read `backend/app/routes/tests/conftest.py` first.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/routes/tests/test_bug_reports.py -k "comment" -v`
Expected: FAIL — 404 (route doesn't exist)

- [ ] **Step 3: Add the models**

```python
# backend/app/db/models.py, after BugReport (~line 1250)
class BugReportComment(Base):
    __tablename__ = "bug_report_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    bug_report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bug_reports.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class BugReportCommentAttachment(Base):
    __tablename__ = "bug_report_comment_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bug_report_comments.id", ondelete="CASCADE")
    )
    file_name: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(sa.LargeBinary)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

(Mirrors `ExemptionRequestFile` exactly, per the investigation's confirmed reusable pattern.)

- [ ] **Step 4: Generate and apply the migration**

Confirm exactly one migration head first (`alembic heads` — same guard as Task 2 Step 3).

Run: `cd backend && alembic revision -m "add bug report comments and attachments"`

```python
def upgrade() -> None:
    op.create_table(
        "bug_report_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("bug_report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bug_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "bug_report_comment_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("comment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bug_report_comments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bug_report_comment_attachments")
    op.drop_table("bug_report_comments")
```

Run: `cd backend && alembic upgrade head`

- [ ] **Step 5: Add the route handlers**

In `backend/app/routes/bug_reports.py`, add near the existing `PATCH /admin/bug-reports/{report_id}` endpoint:

```python
from pydantic import BaseModel

class BugReportCommentBody(BaseModel):
    body: str

class BugReportCommentOut(BaseModel):
    id: uuid.UUID
    bug_report_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    body: str
    created_at: datetime


def _require_reporter_or_admin(session: Session, user: Soldier, report_id: uuid.UUID) -> BugReport:
    report = session.get(BugReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="not_found")
    # Soldier.role is a single string field ("admin" is one possible value),
    # not a list — confirmed via backend/app/auth/authz.py's `can()`, which
    # checks `user.role == "admin"`. bug_reports.py's existing admin routes
    # use the require_roles("admin") dependency instead of this inline form,
    # but that dependency can't express "OR the reporter" — this helper needs
    # the inline equivalent for the ownership fallback.
    if report.reporter_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return report


@router.post("/bug-reports/{report_id}/comments", response_model=BugReportCommentOut, status_code=201)
def create_bug_report_comment(
    report_id: uuid.UUID,
    body: BugReportCommentBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BugReportCommentOut:
    _require_reporter_or_admin(session, user, report_id)
    comment = BugReportComment(bug_report_id=report_id, author_id=user.id, body=body.body)
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return BugReportCommentOut(
        id=comment.id, bug_report_id=comment.bug_report_id, author_id=comment.author_id,
        author_name=user.full_name, body=comment.body, created_at=comment.created_at,
    )


@router.get("/bug-reports/{report_id}/comments", response_model=list[BugReportCommentOut])
def list_bug_report_comments(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[BugReportCommentOut]:
    _require_reporter_or_admin(session, user, report_id)
    comments = session.execute(
        select(BugReportComment).where(BugReportComment.bug_report_id == report_id).order_by(BugReportComment.created_at)
    ).scalars().all()
    author_ids = {c.author_id for c in comments}
    authors = {
        s.id: s.full_name
        for s in session.execute(select(Soldier).where(Soldier.id.in_(author_ids))).scalars().all()
    } if author_ids else {}
    return [
        BugReportCommentOut(
            id=c.id, bug_report_id=c.bug_report_id, author_id=c.author_id,
            author_name=authors.get(c.author_id, "?"), body=c.body, created_at=c.created_at,
        )
        for c in comments
    ]
```

(The role check and both `require_password_changed` usages above already match this file's real conventions — confirmed by reading `bug_reports.py` in full: ordinary endpoints use `Depends(require_password_changed)`, admin-only endpoints use `Depends(require_roles("admin"))`, and `Soldier.role` is the actual singular field name used for the `"admin"` check throughout the codebase, not `.roles`.)

- [ ] **Step 6: Add attachment upload/download endpoints, reusing the exemption-file pattern**

Read `backend/app/routes/exemption_requests.py`'s `_magic_bytes_match` helper (line 46) and the `POST /me/exemption-requests/{request_id}/files` handler (lines 487-523) in full, then add an analogous pair:

```python
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif"}
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024  # 5 MB, matching the bug report's own screenshot cap

@router.post("/bug-reports/{report_id}/comments/{comment_id}/attachments", status_code=201)
async def upload_bug_report_comment_attachment(
    report_id: uuid.UUID,
    comment_id: uuid.UUID,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    _require_reporter_or_admin(session, user, report_id)
    comment = session.get(BugReportComment, comment_id)
    if comment is None or comment.bug_report_id != report_id:
        raise HTTPException(status_code=404, detail="not_found")
    if comment.author_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    if file.content_type not in ALLOWED_IMAGE_TYPES or not _magic_bytes_match(data, file.content_type):
        raise HTTPException(status_code=400, detail="invalid_file_type")
    safe_name = re.sub(r"[^\w.\-]", "_", file.filename or "attachment")
    attachment = BugReportCommentAttachment(
        comment_id=comment_id, file_name=safe_name, content_type=file.content_type,
        data=data, uploaded_by=user.id,
    )
    session.add(attachment)
    session.commit()
    return {"id": str(attachment.id), "file_name": attachment.file_name}


@router.get("/bug-reports/{report_id}/comments/{comment_id}/attachments/{attachment_id}")
def download_bug_report_comment_attachment(
    report_id: uuid.UUID,
    comment_id: uuid.UUID,
    attachment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Response:
    _require_reporter_or_admin(session, user, report_id)
    attachment = session.get(BugReportCommentAttachment, attachment_id)
    if attachment is None or attachment.comment_id != comment_id:
        raise HTTPException(status_code=404, detail="not_found")
    return Response(content=attachment.data, media_type=attachment.content_type)
```

(Import `_magic_bytes_match` from `exemption_requests.py` if it's exported, or duplicate the minimal magic-byte check if the codebase prefers module-private helpers not to be cross-imported — check whether `exemption_requests.py` exports anything else across route modules first to follow the existing convention.)

- [ ] **Step 7: Add `GET /my/bug-reports` for reporters to list their own reports**

```python
@router.get("/my/bug-reports", response_model=list[BugReportOut])  # confirm BugReportOut or equivalent already exists for the admin list endpoint and reuse it
def list_my_bug_reports(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[BugReportOut]:
    reports = session.execute(
        select(BugReport).where(BugReport.reporter_id == user.id).order_by(BugReport.created_at.desc())
    ).scalars().all()
    return [_bug_report_out(r) for r in reports]  # reuse whatever serializer the admin list endpoint already uses
```

(Confirm the exact existing serializer/response-model name used by `GET /admin/bug-reports` at line 115 and reuse it rather than duplicating field mapping.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && pytest app/routes/tests/test_bug_reports.py -k "comment" -v`
Expected: PASS

- [ ] **Step 9: Run the full bug_reports test file for regressions**

Run: `cd backend && pytest app/routes/tests/test_bug_reports.py -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/db/models.py backend/app/routes/bug_reports.py backend/alembic/versions/ backend/app/routes/tests/test_bug_reports.py
git commit -m "feat: add comment thread with image attachments to bug reports"
```

---

### Task 4: Frontend — comment thread UI (admin + reporter views)

**Files:**
- Create: `frontend/src/pages/admin/BugReportDetailModal.tsx`
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx` — add a button/link per row to open the detail modal
- Modify: `frontend/src/api/bugReports.ts` — add `listComments`, `createComment`, `uploadCommentAttachment`, `getMyBugReports`
- Create or modify: reporter-facing page for viewing own bug reports + comments (check `frontend/src/pages/MyRequestsPage.tsx` first — if it already aggregates various "my requests," add a bug-reports section there instead of a brand-new page; otherwise create `frontend/src/pages/MyBugReportsPage.tsx` and register its route in `App.tsx`)
- Test: manual (component composition over already-tested primitives; no new test harness needed beyond Task 1's precedent)

- [ ] **Step 1: Add API client functions**

```ts
// frontend/src/api/bugReports.ts
export interface BugReportComment {
  id: string;
  bug_report_id: string;
  author_id: string;
  author_name: string;
  body: string;
  created_at: string;
}

export async function listComments(reportId: string): Promise<BugReportComment[]> {
  const res = await apiFetch(`/bug-reports/${reportId}/comments`);
  return res.json();
}

export async function createComment(reportId: string, body: string): Promise<BugReportComment> {
  const res = await apiFetch(`/bug-reports/${reportId}/comments`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
  return res.json();
}

export async function uploadCommentAttachment(reportId: string, commentId: string, file: File): Promise<{ id: string; file_name: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch(`/bug-reports/${reportId}/comments/${commentId}/attachments`, {
    method: "POST",
    body: form,
  });
  return res.json();
}

export async function getMyBugReports(): Promise<BugReport[]> {
  const res = await apiFetch(`/my/bug-reports`);
  return res.json();
}
```

(Match `apiFetch`'s actual exported name/signature and existing multipart-upload conventions already used elsewhere in `frontend/src/api/` — e.g. check `exemptionRequests.ts`'s file-upload function for the established multipart pattern in this codebase and mirror it exactly instead of the illustrative sketch above.)

- [ ] **Step 2: Build the detail modal with comment thread**

```tsx
// frontend/src/pages/admin/BugReportDetailModal.tsx
import { useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { listComments, createComment, uploadCommentAttachment, BugReportComment } from "../../api/bugReports";

interface Props {
  reportId: string;
  onClose: () => void;
}

export default function BugReportDetailModal({ reportId, onClose }: Props) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const commentsQuery = useQuery({
    queryKey: ["bug-report-comments", reportId],
    queryFn: () => listComments(reportId),
  });

  const postComment = useMutation({
    mutationFn: async () => {
      const comment = await createComment(reportId, text);
      if (file) await uploadCommentAttachment(reportId, comment.id, file);
      return comment;
    },
    onSuccess: () => {
      setText("");
      setFile(null);
      qc.invalidateQueries({ queryKey: ["bug-report-comments", reportId] });
    },
  });

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b dark:border-gray-600 flex justify-between items-center">
          <h3 className="font-semibold">תגובות על הדיווח</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {(commentsQuery.data ?? []).map((c: BugReportComment) => (
            <div key={c.id} className="border rounded p-2 text-sm dark:border-gray-600">
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>{c.author_name}</span>
                <span dir="ltr">{new Date(c.created_at).toLocaleString("he-IL")}</span>
              </div>
              <p>{c.body}</p>
            </div>
          ))}
        </div>
        <div className="p-4 border-t dark:border-gray-600 space-y-2">
          <textarea
            className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
            rows={3}
            placeholder="הוסף תגובה..."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex justify-between items-center">
            <input type="file" accept="image/png,image/jpeg,image/gif" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
            <button
              className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
              disabled={!text.trim() || postComment.isPending}
              onClick={() => postComment.mutate()}
            >
              שלח
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

(Match the actual `useMutation`/`apiFetch` error-handling conventions used elsewhere in this codebase, e.g. toast-on-error — check a sibling modal component like `AskSwapModal.tsx` for the established pattern and align this with it rather than leaving mutation errors silently swallowed.)

- [ ] **Step 3: Wire the modal into BugReportsContent.tsx**

Add a state `openCommentsFor: string | null` and a button per row (in the description or a new actions cell) to open it:

```tsx
{openCommentsFor && (
  <BugReportDetailModal reportId={openCommentsFor} onClose={() => setOpenCommentsFor(null)} />
)}
```

Add a button in each row (e.g. in the expanded detail section, near the existing "הצג JSON" button) — `<button onClick={(e) => { e.stopPropagation(); setOpenCommentsFor(report.id); }}>תגובות</button>` — remembering to `stopPropagation` per Task 1's fix pattern so it doesn't trigger row collapse/expand unexpectedly.

- [ ] **Step 4: Build/extend the reporter-facing view**

Read `frontend/src/pages/MyRequestsPage.tsx` first. If it already lists other "my X" request types (constraints, exemptions, etc.) in a unified list/tab layout, add a "הדיווחים שלי" (my reports) section there following the same layout pattern, using `getMyBugReports()` and the same `BugReportDetailModal` component (it's already reporter/admin-agnostic since the backend endpoints enforce access by role). If no such unified page exists, create `frontend/src/pages/MyBugReportsPage.tsx` following the structure of the closest analogous single-purpose "my X" page in `frontend/src/pages/`, and register its route in `frontend/src/App.tsx`.

- [ ] **Step 5: Manually verify in the running app**

Start `.\dev.ps1`. As a regular soldier: submit a bug report via the existing bug-report trigger, then find it in the new "my reports" view and post a comment with an attached screenshot. As an admin: open the same report in the admin bug-reports tab, open its comment thread, confirm the soldier's comment and attachment are visible, and post a reply. Confirm a third, unrelated soldier gets a 403 if they try to hit the comments endpoint directly for someone else's report (use browser dev tools network tab or a manual `curl`/`Invoke-WebRequest` call to confirm, since there's no UI path to someone else's report id).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/admin/BugReportDetailModal.tsx frontend/src/pages/admin/BugReportsContent.tsx frontend/src/api/bugReports.ts frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/MyBugReportsPage.tsx frontend/src/App.tsx
git commit -m "feat: add comment thread UI for bug reports, for both reporters and admins"
```

---

## Self-Review Notes

- All spec items for this subsystem (row-click bug, won't-fix status, comments with image attachments) are covered by Tasks 1-4.
- Reuses the existing `ExemptionRequestFile` binary-attachment pattern rather than introducing a new storage mechanism, per the investigation's explicit recommendation.
- The bug-reports list page's pagination is intentionally NOT touched here — investigation revealed it does not actually use URL params today (contrary to the original request's premise), so that work is covered separately in the misc-ux plan, which designs the URL-param convention from scratch and applies it here too.
- No placeholders; exact file paths, models, routes, and commands throughout. A few exact conventions (role-check helper name, apiFetch signature, mutation-error pattern) are flagged as "read the file first" rather than guessed, since guessing wrong here would silently diverge from house style.
