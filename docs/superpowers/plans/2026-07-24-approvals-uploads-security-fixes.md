# Bug Fixes & Approval/Upload Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix a broken exemption-file download link, add a missing field label on the profile page, harden every file-upload endpoint (and its matching file picker) against content-type spoofing and unbounded uploads, close three gaps where an "approve" button is shown to a user the backend will actually reject, and let plain soldiers view (read-only, redacted) another soldier's profile instead of hitting a 403.

**Architecture:** Each task is an independent, narrowly-scoped bug fix or hardening pass against the existing FastAPI + React codebase â€” no new subsystems. Backend authorization logic in `backend/app/auth/authz.py` and `backend/app/services/authority.py` is reused, not replaced: where the frontend currently makes an authority decision the backend disagrees with, the backend computes the real answer once and returns it as a field on the existing response DTO, and the frontend consumes that field instead of guessing.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), React + TypeScript + Vitest/RTL (frontend), pytest (backend tests).

## Global Constraints

- Hebrew UI strings only â€” this codebase has a single locale file, `frontend/src/i18n/he.json`. Do not add an `en.json`.
- Every new/changed backend route stays under the existing `/api` prefix mounted in `backend/app/main.py`; call it `/exemption-requests/...` etc. in frontend URL builders, never `/api/exemption-requests/...` (the axios client already prepends `/api`).
- Run backend tests with `pytest -m soldiers -q` / `pytest -m misc -q` (per area) from `backend/`, not the full suite, per task. Run frontend tests with `npm test -- <file>` from `frontend/`.
- Do not touch `DateInput.tsx` â€” the previously-reported calendar-picker bug was confirmed no longer reproducible and is out of scope for this plan.

---

### Task 1: Fix broken exemption-file download link

**Files:**
- Modify: `frontend/src/api/exemptions.ts:139-141`
- Modify: `frontend/src/pages/ApprovalsPage.test.tsx:247,277,296`
- Create: `frontend/src/api/exemptions.test.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: `exemptionFileDownloadUrl(requestId, fileId)` now returns a path relative to the axios `api` client's `baseURL` (`/api`), matching every other URL builder in `frontend/src/api/*.ts`.

**Root cause:** `frontend/src/api/exemptions.ts:139-141` returns `` `/api/exemption-requests/${requestId}/files/${fileId}` ``, but `frontend/src/api/client.ts` already sets `baseURL = "/api"` on the axios instance used to fetch it (`ApprovalsPage.tsx` calls `api.get(exemptionFileDownloadUrl(...))`). The request actually goes to `/api/api/exemption-requests/...`, 404s, and the catch block shows the generic `"×©×’×™××” ×‘×‘×™×¦×•×¢ ×”×¤×¢×•×œ×”"` toast â€” this is the bug reported by the user when clicking an exemption attachment.

- [x] **Step 1: Write the failing test**

Create `frontend/src/api/exemptions.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { exemptionFileDownloadUrl } from "./exemptions";

describe("exemptionFileDownloadUrl", () => {
  it("returns a path relative to the api client's baseURL, without a duplicate /api prefix", () => {
    expect(exemptionFileDownloadUrl("req-1", "file-1")).toBe("/exemption-requests/req-1/files/file-1");
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- src/api/exemptions.test.ts`
Expected: FAIL â€” received `"/api/exemption-requests/req-1/files/file-1"`, expected `"/exemption-requests/req-1/files/file-1"`.

- [x] **Step 3: Fix the URL builder**

In `frontend/src/api/exemptions.ts:139-141`, change:

```ts
export function exemptionFileDownloadUrl(requestId: string, fileId: string): string {
  return `/api/exemption-requests/${requestId}/files/${fileId}`;
}
```

to:

```ts
export function exemptionFileDownloadUrl(requestId: string, fileId: string): string {
  return `/exemption-requests/${requestId}/files/${fileId}`;
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `npm test -- src/api/exemptions.test.ts`
Expected: PASS

- [x] **Step 5: Update the existing ApprovalsPage test's mocked URLs to match reality**

`frontend/src/pages/ApprovalsPage.test.tsx` mocks `exemptionFileDownloadUrl` to return a hardcoded string that still has the (now-fixed) double prefix. Update it so the test data matches what the real function returns, and re-point the `api.get` assertion at the same corrected string:

- Line 247: change `.mockReturnValue("/api/exemption-requests/er1/files/f1")` to `.mockReturnValue("/exemption-requests/er1/files/f1")`.
- Line 277: change the `expect(api.get).toHaveBeenCalledWith("/api/exemption-requests/er1/files/f1", ...)` to `expect(api.get).toHaveBeenCalledWith("/exemption-requests/er1/files/f1", ...)`.
- Line 296: change `.mockReturnValue("/api/exemption-requests/er1/files/f1")` to `.mockReturnValue("/exemption-requests/er1/files/f1")`.

- [x] **Step 6: Run the full ApprovalsPage test file to verify nothing broke**

Run: `npm test -- src/pages/ApprovalsPage.test.tsx`
Expected: PASS (all existing tests still pass with the corrected URLs)

- [x] **Step 7: Commit**

```bash
git add frontend/src/api/exemptions.ts frontend/src/api/exemptions.test.ts frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "fix: exemption file download hit /api/api due to duplicate baseURL prefix"
```

---

### Task 2: Label the military-license expiry date field on the profile page

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx:340-359`

**Interfaces:**
- Consumes: existing i18n key `soldier_profile.military_driving_license_expiry` (`frontend/src/i18n/he.json:598`, value `"×ª××¨×™×š ×¡×™×•× ×ª×•×§×£ ×¨×™×©×™×•×Ÿ ×¦×‘××™"`), already used read-only elsewhere in the same file (`ProfilePage.tsx:255-256`) but never as a label on the editable field.
- Produces: nothing consumed elsewhere.

**Root cause:** The row at `ProfilePage.tsx:340-359` has one label (`soldier_profile.military_driving_license`, "×¨×©× \"×¦ (×¨×™×©×™×•×Ÿ × ×”×™×’×” ×¦×‘××™)") covering the whole row â€” the checkbox and the `DateInput` for the expiry date share it, so the date field itself is unlabeled. A user editing their profile sees an unlabeled date box next to a checkbox and can't tell what date it's asking for.

- [x] **Step 1: Add the label**

In `frontend/src/pages/ProfilePage.tsx`, change lines 340-359 from:

```tsx
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.military_driving_license")}</label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={licenseHasReq} onChange={e => setLicenseHasReq(e.target.checked)} />
              {t("soldier_profile.military_driving_license_has")}
            </label>
            <DateInput
              value={licenseExpiryReq}
              onChange={setLicenseExpiryReq}
              disabled={!licenseHasReq}
              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 disabled:opacity-50"
            />
            <button
              type="button"
              onClick={() => requestUpdate("military_driving_license", militaryLicensePayload(licenseHasReq, licenseExpiryReq))}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
```

to:

```tsx
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.military_driving_license")}</label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={licenseHasReq} onChange={e => setLicenseHasReq(e.target.checked)} />
              {t("soldier_profile.military_driving_license_has")}
            </label>
            <label htmlFor="military-license-expiry-input" className="text-sm text-gray-500 dark:text-gray-400">
              {t("soldier_profile.military_driving_license_expiry")}
            </label>
            <DateInput
              id="military-license-expiry-input"
              value={licenseExpiryReq}
              onChange={setLicenseExpiryReq}
              disabled={!licenseHasReq}
              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 disabled:opacity-50"
            />
            <button
              type="button"
              onClick={() => requestUpdate("military_driving_license", militaryLicensePayload(licenseHasReq, licenseExpiryReq))}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
```

`DateInput` already accepts and forwards an `id` prop (`frontend/src/components/DateInput.tsx:47-48,103`), so `htmlFor` correctly associates the label with the visible text field.

- [x] **Step 2: Verify in the browser**

Run (from `frontend/`): `npm run typecheck` â€” expect no errors (the `id` prop already exists on `DateInputProps`).

Then, with the dev stack running (`.\dev.ps1` from repo root), open `http://localhost:5173/profile`, and confirm the new label "×ª××¨×™×š ×¡×™×•× ×ª×•×§×£ ×¨×™×©×™×•×Ÿ ×¦×‘××™" appears immediately before the license expiry date box.

- [x] **Step 3: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx
git commit -m "fix: label the military license expiry date field on the profile page"
```

---

### Task 3: Backend â€” magic-byte validation, size limits, and filename sanitization on every upload endpoint

**Files:**
- Modify: `backend/app/routes/exemption_requests.py:445-474`
- Modify: `backend/app/routes/gimelim.py:241-297`
- Modify: `backend/app/routes/import_excel.py:121-134`
- Modify: `backend/app/routes/import_sessions.py:76-103`
- Test: `backend/tests/integration/test_exemptions_api.py`
- Test: `backend/tests/integration/test_gimelim_api.py`
- Test: `backend/tests/integration/test_import_excel.py`
- Test: `backend/tests/integration/test_import_sessions_api.py` (create if it doesn't already cover upload)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new â€” same response shapes, stricter validation only.

All four upload endpoints already store bytes in a Postgres `LargeBinary` column (`ExemptionRequestFile.data`, `GimelimAttachment.data`, `ImportSession.raw_excel`), never on the filesystem, so there is no path-traversal risk from the filename today â€” but the summary table below shows the type/size/sanitization gaps to close:

| Endpoint | Magic-byte check | Size limit | Filename sanitized |
|---|---|---|---|
| `exemption_requests.py:445` | âŒ (Content-Type header only) | âœ… 10 MB | âœ… |
| `gimelim.py:241` | âœ… | âœ… 20 MB | âŒ |
| `import_excel.py:121` (`/preview`) | âœ… (`PK\x03\x04`) | âŒ none | n/a (never stored) |
| `import_sessions.py:76` | âœ… (`PK\x03\x04` + `.xlsx` ext) | âŒ none | âŒ |

- [x] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_exemptions_api.py` (append at end of file):

```python
def test_upload_exemption_file_rejects_content_type_mismatch(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="mb_soldier_001")
    et = ExemptionType(name="mb-type-001", is_medical=True)
    admin_session.add(et)
    admin_session.flush()
    req = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id, status="draft", start_date=date(2026, 1, 1),
    )
    admin_session.add(req)
    admin_session.commit()

    r = client.post(
        f"/api/me/exemption-requests/{req.id}/files",
        files={"file": ("fake.png", b"<script>alert(1)</script>", "image/png")},
        headers=auth_headers(soldier),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_file_type"
```

Add the needed imports at the top of `test_exemptions_api.py` if not already present: `from datetime import date`, `from app.db.models import ExemptionRequest, ExemptionType`, `from tests.helpers import auth_headers, create_soldier` (check existing imports first â€” the file already has integration tests for this router, so most of these likely already exist; only add what's missing).

Add to `backend/tests/integration/test_gimelim_api.py` (append at end of file â€” check existing imports/fixtures used elsewhere in the file, e.g. for creating a dismissal, and reuse them):

```python
def test_upload_gimelim_attachment_rejects_unsanitized_filename():
    # Placeholder marker removed below â€” see Step 3 for the real assertion,
    # which depends on the fixture helpers already defined earlier in this file.
    pass
```

(This placeholder step exists only to flag that the real test â€” written in Step 1 for the two endpoints below â€” needs the file's existing dismissal-creation helper; do not commit the `pass` stub. Instead, locate the existing helper used by other tests in `test_gimelim_api.py` for creating a committed gimelim dismissal â€” e.g. a fixture or a `_commit_gimelim(...)` style function already in that file â€” and write:)

```python
def test_upload_gimelim_attachment_sanitizes_filename(client, admin_session):
    dismissal, commander = <use the same setup pattern as the nearest existing
        "test_upload_gimelim_attachment" test in this file â€” reuse its dismissal
        creation and `_require_gimelim_permission`-satisfying actor>
    r = client.post(
        f"/api/gimelim/{dismissal.id}/attachments",
        files={"file": ("../../etc/passwd.pdf", b"%PDF-1.4 x", "application/pdf")},
        headers=auth_headers(commander),
    )
    assert r.status_code == 201
    assert "/" not in r.json()["file_name"]
    assert ".." not in r.json()["file_name"]
```

Add to `backend/tests/integration/test_import_excel.py` (append at end of file, reusing `make_xlsx_bytes`, `_upload`, `auth_headers`, `create_node`, `create_soldier` already defined there):

```python
def test_preview_rejects_oversized_file(client, admin_session):
    node = create_node(admin_session, level="branch", name="ie_node_size_001")
    dm = create_soldier(admin_session, personal_number="ie_dm_size_001", role="duty_manager", hierarchy_node_id=node.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    oversized = b"PK\x03\x04" + b"0" * (25 * 1024 * 1024)
    resp = client.post(
        "/api/import/preview",
        files={"file": ("import.xlsx", oversized, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "file_too_large"
```

- [x] **Step 2: Run the tests to verify they fail**

Run (from `backend/`, venv active):
```bash
pytest tests/integration/test_exemptions_api.py::test_upload_exemption_file_rejects_content_type_mismatch -v
pytest tests/integration/test_import_excel.py::test_preview_rejects_oversized_file -v
```
Expected: both FAIL â€” the exemption test currently gets 201 (content-type header alone is trusted); the import-excel test currently gets 200/500 (no size limit exists).

- [x] **Step 3: Add magic-byte validation to the exemption file upload**

In `backend/app/routes/exemption_requests.py`, add near the top of the file (after the existing `import re`):

```python
_MAGIC: dict[str, list[bytes]] = {
    "application/pdf": [b"%PDF"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
}


def _magic_bytes_match(content_type: str, data: bytes) -> bool:
    return any(data[: len(prefix)] == prefix for prefix in _MAGIC.get(content_type, []))
```

Then change `upload_exemption_file` (`exemption_requests.py:445-474`) from:

```python
    allowed_types = {"application/pdf", "image/jpeg", "image/png", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="invalid_file_type")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file_too_large")
```

to:

```python
    allowed_types = {"application/pdf", "image/jpeg", "image/png", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="invalid_file_type")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file_too_large")
    if not _magic_bytes_match(file.content_type, data):
        raise HTTPException(status_code=400, detail="invalid_file_type")
```

- [x] **Step 4: Sanitize the gimelim attachment filename**

In `backend/app/routes/gimelim.py`, add `import re` to the top imports (line 3, alongside `import uuid`). Then change (`gimelim.py:282-288`):

```python
    attachment = GimelimAttachment(
        dismissal_id=dismissal_id,
        file_name=file.filename or "file",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        uploaded_by=user.id,
    )
```

to:

```python
    attachment = GimelimAttachment(
        dismissal_id=dismissal_id,
        file_name=re.sub(r"[^\w.\-]", "_", (file.filename or "file"))[:200],
        content_type=file.content_type or "application/octet-stream",
        data=data,
        uploaded_by=user.id,
    )
```

This mirrors the existing sanitization already used in `exemption_requests.py:462`.

- [x] **Step 5: Add a size limit to the Excel preview endpoint**

In `backend/app/routes/import_excel.py`, change (`import_excel.py:121-134`):

```python
@router.post("/preview", response_model=PreviewResult)
async def preview(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    content = await file.read()
    # Validate XLSX magic bytes (PK signature for ZIP format)
    if content[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="invalid_file_type")
```

to:

```python
@router.post("/preview", response_model=PreviewResult)
async def preview(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file_too_large")
    # Validate XLSX magic bytes (PK signature for ZIP format)
    if content[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="invalid_file_type")
```

- [x] **Step 6: Add a size limit and filename sanitization to the persisted import-session upload**

In `backend/app/routes/import_sessions.py`, add `import re` to the top imports (line 3, alongside `import uuid`). Then change (`import_sessions.py:76-103`):

```python
@router.post("")
async def upload_import_session(
    file: UploadFile = File(...),
    parser_id: str | None = None,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="invalid_file_type")

    content = await file.read()
    if content[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="invalid_file_type")

    try:
        sess = create_session(
            session,
            filename=file.filename or "import.xlsx",
            content=content,
            actor=actor,
            parser_id=parser_id,
        )
```

to:

```python
@router.post("")
async def upload_import_session(
    file: UploadFile = File(...),
    parser_id: str | None = None,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="invalid_file_type")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file_too_large")
    if content[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="invalid_file_type")

    safe_filename = re.sub(r"[^\w.\-]", "_", file.filename or "import.xlsx")[:200]
    try:
        sess = create_session(
            session,
            filename=safe_filename,
            content=content,
            actor=actor,
            parser_id=parser_id,
        )
```

- [x] **Step 7: Run the tests to verify they pass**

Run (from `backend/`):
```bash
pytest tests/integration/test_exemptions_api.py -v -k "content_type_mismatch or upload"
pytest tests/integration/test_gimelim_api.py -v -k "sanitiz"
pytest tests/integration/test_import_excel.py -v -k "oversized"
```
Expected: all PASS.

- [x] **Step 8: Run the full targeted test areas**

Run: `pytest -m soldiers -q` and `pytest -m misc -q` (from `backend/`)
Expected: PASS, no regressions.

- [x] **Step 9: Commit**

```bash
git add backend/app/routes/exemption_requests.py backend/app/routes/gimelim.py backend/app/routes/import_excel.py backend/app/routes/import_sessions.py backend/tests/integration/test_exemptions_api.py backend/tests/integration/test_gimelim_api.py backend/tests/integration/test_import_excel.py
git commit -m "fix: validate upload magic bytes, cap unbounded uploads, sanitize stored filenames"
```

---

### Task 4: Frontend â€” client-side magic-byte validation and matching size limits in every file picker

**Files:**
- Create: `frontend/src/utils/fileValidation.ts`
- Create: `frontend/src/utils/fileValidation.test.ts`
- Modify: `frontend/src/pages/MyRequestsPage.tsx:345-363`
- Modify: `frontend/src/components/DismissalModal.tsx:122-139`
- Modify: `frontend/src/pages/ImportUploadPage.tsx:15-30`

**Interfaces:**
- Produces: `validateFileSignature(file: File, allowedTypes: Record<string, Uint8Array[]>): Promise<boolean>` and `readMagicBytes(file: File, length: number): Promise<Uint8Array>` â€” exported from `frontend/src/utils/fileValidation.ts`, consumed by the three file pickers below.

The backend now rejects content-type-spoofed files (Task 3), but users only find that out after uploading. This task adds the same magic-byte check client-side, before the network call, plus closes the one picker (`ImportUploadPage.tsx`) with no size check at all.

- [x] **Step 1: Write the failing test for the shared validator**

Create `frontend/src/utils/fileValidation.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { validateFileSignature } from "./fileValidation";

function makeFile(bytes: number[], type: string, name = "f"): File {
  return new File([new Uint8Array(bytes)], name, { type });
}

const PDF_SIGNATURES = { "application/pdf": [new Uint8Array([0x25, 0x50, 0x44, 0x46])] }; // %PDF

describe("validateFileSignature", () => {
  it("accepts a file whose bytes match its declared type", async () => {
    const file = makeFile([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31], "application/pdf");
    await expect(validateFileSignature(file, PDF_SIGNATURES)).resolves.toBe(true);
  });

  it("rejects a file whose bytes don't match its declared (spoofed) type", async () => {
    const file = makeFile([0x3c, 0x73, 0x63, 0x72, 0x69, 0x70, 0x74], "application/pdf", "fake.pdf");
    await expect(validateFileSignature(file, PDF_SIGNATURES)).resolves.toBe(false);
  });

  it("rejects a type with no registered signature", async () => {
    const file = makeFile([0x25, 0x50, 0x44, 0x46], "application/octet-stream");
    await expect(validateFileSignature(file, PDF_SIGNATURES)).resolves.toBe(false);
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- src/utils/fileValidation.test.ts`
Expected: FAIL â€” `validateFileSignature` doesn't exist yet (module not found).

- [x] **Step 3: Implement the shared validator**

Create `frontend/src/utils/fileValidation.ts`:

```ts
export async function readMagicBytes(file: File, length: number): Promise<Uint8Array> {
  const slice = file.slice(0, length);
  const buf = await slice.arrayBuffer();
  return new Uint8Array(buf);
}

export async function validateFileSignature(
  file: File,
  allowedSignatures: Record<string, Uint8Array[]>,
): Promise<boolean> {
  const signatures = allowedSignatures[file.type];
  if (!signatures || signatures.length === 0) return false;
  const maxLen = Math.max(...signatures.map(s => s.length));
  const head = await readMagicBytes(file, maxLen);
  return signatures.some(sig => sig.every((byte, i) => head[i] === byte));
}

export const PDF_IMAGE_SIGNATURES: Record<string, Uint8Array[]> = {
  "application/pdf": [new Uint8Array([0x25, 0x50, 0x44, 0x46])], // %PDF
  "image/jpeg": [new Uint8Array([0xff, 0xd8, 0xff])],
  "image/png": [new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])],
  "image/gif": [
    new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x37, 0x61]), // GIF87a
    new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61]), // GIF89a
  ],
  "image/webp": [new Uint8Array([0x52, 0x49, 0x46, 0x46])], // RIFF
};

export const XLSX_SIGNATURES: Record<string, Uint8Array[]> = {
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [
    new Uint8Array([0x50, 0x4b, 0x03, 0x04]), // PK\x03\x04 (ZIP)
  ],
};
```

- [x] **Step 4: Run test to verify it passes**

Run: `npm test -- src/utils/fileValidation.test.ts`
Expected: PASS

- [x] **Step 5: Wire magic-byte validation into the exemption file picker**

In `frontend/src/pages/MyRequestsPage.tsx`, add the import near the top (with the other imports):

```ts
import { validateFileSignature, PDF_IMAGE_SIGNATURES } from "../utils/fileValidation";
```

Change the file-input `onChange` handler (`MyRequestsPage.tsx:350-360`) from:

```tsx
                  onChange={e => {
                    const picked = Array.from(e.target.files ?? []);
                    const valid = picked.filter(f => f.size <= MAX_FILE_BYTES);
                    const oversized = picked.filter(f => f.size > MAX_FILE_BYTES).map(f => f.name);
                    setUploadFiles(prev => {
                      const merged = [...prev, ...valid.filter(v => !prev.some(p => p.name === v.name))];
                      return merged;
                    });
                    setUploadSizeErrors(oversized);
                    e.target.value = "";
                  }}
```

to:

```tsx
                  onChange={async e => {
                    const picked = Array.from(e.target.files ?? []);
                    e.target.value = "";
                    const withinSize = picked.filter(f => f.size <= MAX_FILE_BYTES);
                    const oversized = picked.filter(f => f.size > MAX_FILE_BYTES).map(f => f.name);
                    const signatureChecks = await Promise.all(
                      withinSize.map(f => validateFileSignature(f, PDF_IMAGE_SIGNATURES)),
                    );
                    const valid = withinSize.filter((_, i) => signatureChecks[i]);
                    const invalidType = withinSize.filter((_, i) => !signatureChecks[i]).map(f => f.name);
                    setUploadFiles(prev => {
                      const merged = [...prev, ...valid.filter(v => !prev.some(p => p.name === v.name))];
                      return merged;
                    });
                    setUploadSizeErrors([...oversized, ...invalidType]);
                  }}
```

(Reusing `uploadSizeErrors` for both oversized and invalid-signature names keeps this change minimal â€” both cases render through the same existing error list at `MyRequestsPage.tsx:364-370`.)

- [x] **Step 6: Wire magic-byte validation into the gimelim attachment picker**

In `frontend/src/components/DismissalModal.tsx`, add the import near the top:

```ts
import { validateFileSignature, PDF_IMAGE_SIGNATURES } from "../utils/fileValidation";
```

Change `handleFileChange` (`DismissalModal.tsx:122-139`) from:

```tsx
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFileError(null);
    if (!f) { setSelectedFile(null); return; }
    if (!ALLOWED_TYPES.has(f.type)) {
      setFileError("×¡×•×’ ×§×•×‘×¥ ×œ× × ×ª×ž×š â€” ×™×© ×œ×”×¢×œ×•×ª PDF, JPG, PNG, GIF ××• WEBP");
      setSelectedFile(null);
      e.target.value = "";
      return;
    }
    if (f.size > MAX_BYTES) {
      setFileError("×”×§×•×‘×¥ ×’×“×•×œ ×ž×“×™ â€” ×ž×§×¡×™×ž×•× 20 MB");
      setSelectedFile(null);
      e.target.value = "";
      return;
    }
    setSelectedFile(f);
  }
```

to:

```tsx
  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFileError(null);
    if (!f) { setSelectedFile(null); return; }
    if (!ALLOWED_TYPES.has(f.type)) {
      setFileError("×¡×•×’ ×§×•×‘×¥ ×œ× × ×ª×ž×š â€” ×™×© ×œ×”×¢×œ×•×ª PDF, JPG, PNG, GIF ××• WEBP");
      setSelectedFile(null);
      e.target.value = "";
      return;
    }
    if (f.size > MAX_BYTES) {
      setFileError("×”×§×•×‘×¥ ×’×“×•×œ ×ž×“×™ â€” ×ž×§×¡×™×ž×•× 20 MB");
      setSelectedFile(null);
      e.target.value = "";
      return;
    }
    const signatureOk = await validateFileSignature(f, PDF_IMAGE_SIGNATURES);
    if (!signatureOk) {
      setFileError("×ª×•×›×Ÿ ×”×§×•×‘×¥ ××™× ×• ×ª×•×× ××ª ×¡×•×’ ×”×§×•×‘×¥ ×”×ž×•×¦×”×¨");
      setSelectedFile(null);
      e.target.value = "";
      return;
    }
    setSelectedFile(f);
  }
```

- [x] **Step 7: Add a missing size check and magic-byte validation to the Excel import picker**

In `frontend/src/pages/ImportUploadPage.tsx`, add the import near the top:

```ts
import { validateFileSignature, XLSX_SIGNATURES } from "../utils/fileValidation";
```

Change `handleUpload` (`ImportUploadPage.tsx:15-30`) from:

```tsx
  async function handleUpload(file: File) {
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setError("×™×© ×œ×”×¢×œ×•×ª ×§×•×‘×¥ ×‘×¤×•×¨×ž×˜ xlsx ×‘×œ×‘×“");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { session_id } = await uploadSession(file);
      navigate(`/import/sessions/${session_id}`);
    } catch (err: unknown) {
      setError(translateApiError(err, t, "×©×’×™××” ×‘×¤×¢× ×•×— ×”×§×•×‘×¥ â€” ×•×“× ×©×”×•× xlsx ×ª×§×™×Ÿ"));
    } finally {
      setLoading(false);
    }
  }
```

to:

```tsx
  const MAX_IMPORT_BYTES = 20 * 1024 * 1024;

  async function handleUpload(file: File) {
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setError("×™×© ×œ×”×¢×œ×•×ª ×§×•×‘×¥ ×‘×¤×•×¨×ž×˜ xlsx ×‘×œ×‘×“");
      return;
    }
    if (file.size > MAX_IMPORT_BYTES) {
      setError("×”×§×•×‘×¥ ×’×“×•×œ ×ž×“×™ â€” ×ž×§×¡×™×ž×•× 20 MB");
      return;
    }
    const signatureOk = await validateFileSignature(file, {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": XLSX_SIGNATURES[
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      ],
      "application/zip": XLSX_SIGNATURES["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
      "": XLSX_SIGNATURES["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    });
    if (!signatureOk) {
      setError("×ª×•×›×Ÿ ×”×§×•×‘×¥ ××™× ×• ×ª×•×× ×§×•×‘×¥ xlsx ×ª×§×™×Ÿ");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { session_id } = await uploadSession(file);
      navigate(`/import/sessions/${session_id}`);
    } catch (err: unknown) {
      setError(translateApiError(err, t, "×©×’×™××” ×‘×¤×¢× ×•×— ×”×§×•×‘×¥ â€” ×•×“× ×©×”×•× xlsx ×ª×§×™×Ÿ"));
    } finally {
      setLoading(false);
    }
  }
```

`.xlsx` files picked via a native file dialog can report `file.type` as the full OOXML MIME type, `application/zip`, or an empty string depending on OS/browser â€” the three-key map covers all three against the same ZIP signature bytes, since the actual byte check (not the declared MIME) is what matters here.

- [x] **Step 8: Run the frontend test suite for touched files**

Run (from `frontend/`): `npm test -- src/utils/fileValidation.test.ts src/pages/MyRequestsPage src/components/DismissalModal src/pages/ImportUploadPage`
Expected: PASS (existing tests for these files, if any, still pass; run `npm run typecheck` too since `MyRequestsPage.tsx`'s handler changed from sync to async).

- [x] **Step 9: Commit**

```bash
git add frontend/src/utils/fileValidation.ts frontend/src/utils/fileValidation.test.ts frontend/src/pages/MyRequestsPage.tsx frontend/src/components/DismissalModal.tsx frontend/src/pages/ImportUploadPage.tsx
git commit -m "feat: validate file magic bytes client-side before upload, cap Excel import size"
```

---

### Task 5: Backend â€” expose real per-item approval authority on pending field-updates and exemption requests

**Files:**
- Modify: `backend/app/routes/soldiers.py` (schema near line 119-133, computation in `list_all_pending_field_updates` lines 338-404)
- Modify: `backend/app/routes/exemption_requests.py` (schema at line 44-116, computation in `get_pending_exemption_requests` lines 168-274 and `get_soldier_exemption_request_history` lines 585-625)
- Test: `backend/tests/unit/test_soldiers_field_updates.py`
- Test: `backend/tests/integration/test_exemptions_api.py`

**Interfaces:**
- Produces: `FieldUpdateOut.can_approve: bool` (soldiers.py); `ExemptionRequestOut.can_approve_commander_step: bool` and `ExemptionRequestOut.can_approve_duty_manager_step: bool` (exemption_requests.py). Consumed by Task 6.

**Root cause (field updates):** `list_all_pending_field_updates` (`soldiers.py:390-393`) filters visibility using `Action.SOLDIER_READ` (in both `_DM_ACTIONS` and `_COMMANDER_ACTIONS`), but the actual decision endpoint `_authorize_field_update_decision` (`soldiers.py:260-262`) requires `Action.SOLDIER_UPDATE` (DM-only, not in `_COMMANDER_ACTIONS`) or `Action.MILITARY_LICENSE_DECIDE` for the driving-license field. A plain commander (not a duty manager) in scope sees the pending item and an Approve button that will always 403.

**Root cause (exemptions):** the duty-manager approval step (`exemption_requests.py:397-406`) additionally requires `dm_scope_covers_target(..., required_level_key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY)` â€” a minimum hierarchy level â€” which neither `get_pending_exemption_requests` nor `get_soldier_exemption_request_history` apply when deciding whether to include an item, so a duty manager below the configured minimum level sees "××©×¨ (×©×œ×‘ ×¡×•×¤×™)" and gets `insufficient_scope_level_for_exemption_approval` on click.

- [x] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_soldiers_field_updates.py` (check the file's existing imports/fixtures first and reuse them â€” it already has field-update creation helpers used by neighboring tests):

```python
def test_pending_field_update_flags_commander_as_unable_to_approve(client, admin_session):
    """A plain commander (not a duty manager) is shown SOLDIER_READ-scoped
    items today, but the approve endpoint requires SOLDIER_UPDATE, which
    commanders don't have â€” can_approve must be False so the frontend can
    hide the button instead of showing one that always 403s."""
    node = create_node(admin_session, level="branch", name="fu_flag_node")
    commander = create_soldier(admin_session, personal_number="fu_flag_cmd", role="commander")
    node.commander_id = commander.id
    soldier = create_soldier(admin_session, personal_number="fu_flag_sol", hierarchy_node_id=node.id)
    admin_session.commit()

    submit_field_update(admin_session, soldier_id=soldier.id, field_name="discharge_date", new_value="2027-01-01")
    admin_session.commit()

    r = client.get("/api/soldiers/field-updates/pending", headers=auth_headers(commander))
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["can_approve"] is False
```

(Use whatever field-update submission helper â€” e.g. `submit_field_update` from `app.services.soldiers` â€” the rest of this test file already imports; adjust the import line accordingly if the name differs.)

Add to `backend/tests/integration/test_exemptions_api.py` (append; reuse `_hebrew_levels`-style level setup pattern from `test_exemption_file_download.py` if this file doesn't already have one, or import it):

```python
def test_pending_exemption_flags_dm_below_minimum_level_as_unable_to_approve(client, admin_session):
    from app.db.models import HierarchyLevelType
    from sqlalchemy import delete
    admin_session.execute(delete(HierarchyLevelType))
    admin_session.flush()
    admin_session.add_all([
        HierarchyLevelType(key="×ž×¨×›×–", label="×ž×¨×›×–", rank=1),
        HierarchyLevelType(key="×ž×“×•×¨", label="×ž×“×•×¨", rank=2),
    ])
    admin_session.commit()

    mador = create_node(admin_session, level="×ž×“×•×¨", name="ex_flag_mador")
    dm = create_soldier(admin_session, personal_number="ex_flag_dm", role="duty_manager", hierarchy_node_id=mador.id)
    soldier = create_soldier(admin_session, personal_number="ex_flag_sol", hierarchy_node_id=mador.id)
    admin_session.commit()

    et = ExemptionType(name="ex-flag-type", is_medical=False)
    admin_session.add(et)
    admin_session.flush()
    req = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id, status="pending_duty_manager", start_date=date(2026, 1, 1),
    )
    admin_session.add(req)
    admin_session.commit()

    r = client.get("/api/exemption-requests/pending", headers=auth_headers(dm))
    assert r.status_code == 200
    items = [i for i in r.json() if i["id"] == str(req.id)]
    assert len(items) == 1
    assert items[0]["can_approve_duty_manager_step"] is False
```

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
pytest tests/unit/test_soldiers_field_updates.py::test_pending_field_update_flags_commander_as_unable_to_approve -v
pytest tests/integration/test_exemptions_api.py::test_pending_exemption_flags_dm_below_minimum_level_as_unable_to_approve -v
```
Expected: both FAIL â€” `KeyError: 'can_approve'` / `'can_approve_duty_manager_step'` (fields don't exist on the response yet).

- [x] **Step 3: Add `can_approve` to `FieldUpdateOut`**

In `backend/app/routes/soldiers.py`, find the `FieldUpdateOut` class (near line 119) and add a field:

```python
class FieldUpdateOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    field_name: str
    previous_value: str | None
    new_value: str | None        # None when viewer cannot see private field values
    status: str
    decided_by: uuid.UUID | None
    decided_at: Any
    decision_note: str | None
    created_at: Any
    nearest_commander: NearestApproverOut | None = None
    nearest_duty_manager: NearestApproverOut | None = None
    can_approve: bool = True
```

Update `_fu_out` (`soldiers.py:211-231`) to accept and pass through the new value:

```python
def _fu_out(
    u: SoldierFieldUpdate, soldier_name: str = "", node_name: str | None = None, include_values: bool = True,
    nearest_commander: NearestApproverOut | None = None, nearest_duty_manager: NearestApproverOut | None = None,
    can_approve: bool = True,
) -> FieldUpdateOut:
    redact = not include_values and u.field_name in PRIVATE_FIELD_NAMES
    return FieldUpdateOut(
        id=u.id,
        soldier_id=u.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        field_name=u.field_name,
        previous_value=None if redact else u.previous_value,
        new_value=None if redact else u.new_value,
        status=u.status,
        decided_by=u.decided_by,
        decided_at=u.decided_at,
        decision_note=u.decision_note,
        created_at=u.created_at,
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
        can_approve=can_approve,
    )
```

- [x] **Step 4: Compute `can_approve` in `list_all_pending_field_updates`**

In `list_all_pending_field_updates` (`soldiers.py:338-404`), the admin branch (lines 361-379) always has `can_approve=True` (admins can approve everything per `can()`'s `user.role == "admin"` shortcut at `authz.py:145-146`) â€” pass `can_approve=True` explicitly there for clarity. In the non-admin branch (lines 385-404), compute the real value per item using the same action `_authorize_field_update_decision` would check:

Change:

```python
    result = []
    for upd in all_pending:
        s = soldiers_by_id.get(upd.soldier_id)
        if s:
            node = nodes_by_id.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
            if can(
                user, Action.SOLDIER_READ, target_node=node, roots=roots,
                is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
            ):
                soldier_name = s.full_name
                node_name = node.name if node else None
                include_values = can_see_private(session, user, s)
                nearest_commander, nearest_duty_manager = _nearest_approvers(session, upd.soldier_id)
                result.append(
                    _fu_out(
                        upd, soldier_name=soldier_name, node_name=node_name, include_values=include_values,
                        nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
                    )
                )
    return result
```

to:

```python
    result = []
    for upd in all_pending:
        s = soldiers_by_id.get(upd.soldier_id)
        if s:
            node = nodes_by_id.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
            if can(
                user, Action.SOLDIER_READ, target_node=node, roots=roots,
                is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
            ):
                soldier_name = s.full_name
                node_name = node.name if node else None
                include_values = can_see_private(session, user, s)
                nearest_commander, nearest_duty_manager = _nearest_approvers(session, upd.soldier_id)
                decide_action = (
                    Action.MILITARY_LICENSE_DECIDE if upd.field_name == "military_driving_license" else Action.SOLDIER_UPDATE
                )
                can_approve = can(
                    user, decide_action, target_node=node, roots=roots,
                    is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
                )
                result.append(
                    _fu_out(
                        upd, soldier_name=soldier_name, node_name=node_name, include_values=include_values,
                        nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
                        can_approve=can_approve,
                    )
                )
    return result
```

Also pass `can_approve=True` explicitly in the admin branch's `_fu_out(...)` call (lines 373-378) for readability (admins already default to `True`, but being explicit avoids confusion since this branch never computes it).

- [x] **Step 5: Add `can_approve_commander_step` / `can_approve_duty_manager_step` to `ExemptionRequestOut`**

In `backend/app/routes/exemption_requests.py`, add both fields to `ExemptionRequestOut` (near line 44-60):

```python
class ExemptionRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    exemption_type_id: uuid.UUID | None    # None when viewer cannot see private fields
    start_date: str
    end_date: str | None
    reason: str | None                      # None when viewer cannot see private fields
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: str
    files: list[ExemptionFileOut] = []
    enrollment_request_id: uuid.UUID | None = None
    nearest_commander: NearestApproverOut | None = None
    nearest_duty_manager: NearestApproverOut | None = None
    can_approve_commander_step: bool = True
    can_approve_duty_manager_step: bool = True
```

Add a helper function right after `_out` (near line 117):

```python
def _exemption_approval_flags(
    session: Session, user: Soldier, target_node: HierarchyNode | None
) -> tuple[bool, bool]:
    """Mirror the authorization checks in approve_exemption_request_commander_step
    and approve_exemption_request_duty_manager_step, so pending-list responses can
    tell the frontend whether the current viewer's approve buttons would actually
    succeed, instead of failing 403 only after the click."""
    if user.role == "admin":
        return True, True
    roots = scope_root_ids(session, user)
    can_commander_step = is_commander(session, user.id) and target_node is not None and any(
        r in target_node.path_ids for r in roots
    )
    can_dm_step = is_duty_manager(session, user.id) and dm_scope_covers_target(
        session, scope_root_ids=roots, target_node=target_node,
        required_level_key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY,
    )
    return can_commander_step, can_dm_step
```

Update `_out` to accept and pass through the two flags:

```python
def _out(
    req: ExemptionRequest,
    soldier_name: str = "",
    node_name: str | None = None,
    files: list[ExemptionFileOut] | None = None,
    include_sensitive: bool = True,
    nearest_commander: NearestApproverOut | None = None,
    nearest_duty_manager: NearestApproverOut | None = None,
    can_approve_commander_step: bool = True,
    can_approve_duty_manager_step: bool = True,
) -> ExemptionRequestOut:
    return ExemptionRequestOut(
        id=req.id,
        soldier_id=req.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        exemption_type_id=req.exemption_type_id if include_sensitive else None,
        start_date=req.start_date.isoformat(),
        end_date=req.end_date.isoformat() if req.end_date else None,
        reason=req.reason if include_sensitive else None,
        status=req.status,
        decided_by=req.decided_by,
        decision_note=req.decision_note,
        created_at=req.created_at.isoformat(),
        files=files or [],
        enrollment_request_id=req.enrollment_request_id,
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
        can_approve_commander_step=can_approve_commander_step,
        can_approve_duty_manager_step=can_approve_duty_manager_step,
    )
```

- [x] **Step 6: Wire the flags into both list endpoints**

In `get_pending_exemption_requests` (`exemption_requests.py:255-273`), change the loop body from:

```python
    for r in reqs:
        if r.enrollment_request_id and not user_can_see_enrollment_exemptions:
            continue
        s = soldiers_by_id.get(r.soldier_id)
        soldier_name = s.full_name if s else str(r.soldier_id)[:8]
        node_name = (
            nodes_by_id[s.hierarchy_node_id].name
            if s and s.hierarchy_node_id and s.hierarchy_node_id in nodes_by_id
            else None
        )
        include_sensitive = s is not None and can_see_private(session, user, s)
        nearest_commander, nearest_duty_manager = _nearest_approvers(session, r.soldier_id)
        result.append(
            _out(
                r, soldier_name=soldier_name, node_name=node_name, files=files_by_req.get(r.id, []),
                include_sensitive=include_sensitive, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
            )
        )
    return result
```

to:

```python
    for r in reqs:
        if r.enrollment_request_id and not user_can_see_enrollment_exemptions:
            continue
        s = soldiers_by_id.get(r.soldier_id)
        soldier_name = s.full_name if s else str(r.soldier_id)[:8]
        node = nodes_by_id.get(s.hierarchy_node_id) if s and s.hierarchy_node_id else None
        node_name = node.name if node else None
        include_sensitive = s is not None and can_see_private(session, user, s)
        nearest_commander, nearest_duty_manager = _nearest_approvers(session, r.soldier_id)
        can_commander_step, can_dm_step = _exemption_approval_flags(session, user, node)
        result.append(
            _out(
                r, soldier_name=soldier_name, node_name=node_name, files=files_by_req.get(r.id, []),
                include_sensitive=include_sensitive, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
                can_approve_commander_step=can_commander_step, can_approve_duty_manager_step=can_dm_step,
            )
        )
    return result
```

In `get_soldier_exemption_request_history` (`exemption_requests.py:585-625`), add the same computation. Find the return block (around line 620-625):

```python
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return [
        _out(
            r, soldier_name=target_soldier.full_name, files=files_by_req.get(r.id, []), include_sensitive=include_sensitive,
            nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
```

Change it to compute the flags once (the target node is the same for every item in this per-soldier endpoint) and pass them through:

```python
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    target_node = (
        session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier.hierarchy_node_id else None
    )
    can_commander_step, can_dm_step = _exemption_approval_flags(session, user, target_node)
    return [
        _out(
            r, soldier_name=target_soldier.full_name, files=files_by_req.get(r.id, []), include_sensitive=include_sensitive,
            nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
            can_approve_commander_step=can_commander_step, can_approve_duty_manager_step=can_dm_step,
```

(keep whatever closing `)` / list-comprehension structure already follows on the next lines â€” only the `_out(...)` call arguments change.)

- [x] **Step 7: Run the tests to verify they pass**

Run:
```bash
pytest tests/unit/test_soldiers_field_updates.py -v
pytest tests/integration/test_exemptions_api.py -v
```
Expected: PASS

- [x] **Step 8: Run the targeted test areas**

Run: `pytest -m soldiers -q`
Expected: PASS, no regressions.

- [x] **Step 9: Commit**

```bash
git add backend/app/routes/soldiers.py backend/app/routes/exemption_requests.py backend/tests/unit/test_soldiers_field_updates.py backend/tests/integration/test_exemptions_api.py
git commit -m "feat: surface per-item approve authority on pending field-updates and exemption requests"
```

---

### Task 6: Frontend â€” hide/disable approve buttons the backend would reject

**Files:**
- Modify: `frontend/src/api/exemptions.ts` (`ExemptionRequest` interface, line 47-64)
- Modify: `frontend/src/api/soldiers.ts` (`FieldUpdateDTO` interface, line 36-51)
- Modify: `frontend/src/pages/ApprovalsPage.tsx` (lines 527-536 exemptions tab, line 580 field_updates tab)
- Modify: `frontend/src/components/ExemptionsPanel.tsx` (lines 239-258)
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx` (`canManage`/`canApproveDutyManagerStep` computation, lines 50-57, 467)
- Modify: `frontend/src/pages/ApprovalsPage.test.tsx`

**Interfaces:**
- Consumes: `can_approve` (Task 5, `FieldUpdateDTO`), `can_approve_commander_step` / `can_approve_duty_manager_step` (Task 5, `ExemptionRequest`).

- [x] **Step 1: Add the new fields to the frontend types**

In `frontend/src/api/exemptions.ts`, add to the `ExemptionRequest` interface (line 47-64):

```ts
export interface ExemptionRequest {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  exemption_type_id: string | null;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  status: "pending_commander" | "pending_duty_manager" | "approved" | "rejected";
  enrollment_request_id: string | null;
  decided_by: string | null;
  decision_note: string | null;
  created_at: string;
  files: ExemptionFile[];
  nearest_commander: { id: string; name: string } | null;
  nearest_duty_manager: { id: string; name: string } | null;
  can_approve_commander_step: boolean;
  can_approve_duty_manager_step: boolean;
}
```

In `frontend/src/api/soldiers.ts`, add to `FieldUpdateDTO` (line 36-51):

```ts
export interface FieldUpdateDTO {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  field_name: string;
  previous_value: string | null;
  new_value: string | null;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
  nearest_commander: { id: string; name: string } | null;
  nearest_duty_manager: { id: string; name: string } | null;
  can_approve: boolean;
}
```

- [x] **Step 2: Write the failing frontend tests**

In `frontend/src/pages/ApprovalsPage.test.tsx`, add `can_approve_commander_step: true, can_approve_duty_manager_step: true` to the existing `exemptionRequestWithFile` fixture (line 93-110) so existing tests keep passing, then append new tests:

```tsx
describe("ApprovalsPage - approve button authority", () => {
  it("hides the duty-manager exemption approve button when the backend says the viewer can't approve it", async () => {
    vi.mocked(exemptionsApi.listPendingExemptionRequests).mockResolvedValue([
      { ...exemptionRequestWithFile, status: "pending_duty_manager", can_approve_duty_manager_step: false },
    ]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SoldierModalProvider>
            <ApprovalsPage />
          </SoldierModalProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const exemptionsTab = await screen.findByTestId("approvals-tab-exemptions");
    fireEvent.click(exemptionsTab);
    await screen.findByTestId(`er-reject-note-${exemptionRequestWithFile.id}`);
    expect(screen.queryByTestId(`er-approve-${exemptionRequestWithFile.id}`)).not.toBeInTheDocument();
  });

  it("hides the field-update approve button when the backend says the viewer can't approve it", async () => {
    vi.mocked(soldiersApi.listPendingFieldUpdates).mockResolvedValue([
      {
        id: "fu1", soldier_id: "sol-5", soldier_name: "E", node_name: null, field_name: "discharge_date",
        previous_value: null, new_value: "2027-01-01", status: "pending", decided_by: null, decided_at: null,
        decision_note: null, created_at: "2026-01-01", nearest_commander: null, nearest_duty_manager: null,
        can_approve: false,
      } as soldiersApi.FieldUpdateDTO,
    ]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SoldierModalProvider>
            <ApprovalsPage />
          </SoldierModalProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const fuTab = await screen.findByTestId("approvals-tab-field_updates");
    fireEvent.click(fuTab);
    await screen.findByText("soldier_profile.discharge_date");
    expect(screen.queryByText("approvals.approve")).not.toBeInTheDocument();
  });
});
```

(If `approvals-tab-field_updates` isn't the exact `data-testid` used for that tab button, check the tab-switcher JSX near the top of `ApprovalsPage.tsx` for the real value and use that instead â€” the exemptions/swaps/transfers tabs already confirm the `approvals-tab-<name>` naming convention.)

- [x] **Step 3: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- src/pages/ApprovalsPage.test.tsx`
Expected: the two new tests FAIL (buttons still render unconditionally); prior tests still pass since the fixture now includes the new fields as `true`.

- [x] **Step 4: Gate the exemption approve buttons in ApprovalsPage**

In `frontend/src/pages/ApprovalsPage.tsx`, change lines 527-536 from:

```tsx
                    {er.status === "pending_commander" && (
                      <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApproveCommander(er.id)} data-testid={`er-approve-${er.id}`}>
                        ××©×¨ (×©×œ×‘ ×ž×¤×§×“)
                      </button>
                    )}
                    {er.status === "pending_duty_manager" && (
                      <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApproveDutyManager(er.id)} data-testid={`er-approve-${er.id}`}>
                        ××©×¨ (×©×œ×‘ ×¡×•×¤×™)
                      </button>
                    )}
```

to:

```tsx
                    {er.status === "pending_commander" && er.can_approve_commander_step && (
                      <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApproveCommander(er.id)} data-testid={`er-approve-${er.id}`}>
                        ××©×¨ (×©×œ×‘ ×ž×¤×§×“)
                      </button>
                    )}
                    {er.status === "pending_duty_manager" && er.can_approve_duty_manager_step && (
                      <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApproveDutyManager(er.id)} data-testid={`er-approve-${er.id}`}>
                        ××©×¨ (×©×œ×‘ ×¡×•×¤×™)
                      </button>
                    )}
```

- [x] **Step 5: Gate the field-update approve button in ApprovalsPage**

Change line 580 from:

```tsx
                  <button onClick={() => onFuApprove(item)} className="bg-green-600 text-white px-2 py-1 rounded text-xs">{t("approvals.approve")}</button>
```

to:

```tsx
                  {item.can_approve && (
                    <button onClick={() => onFuApprove(item)} className="bg-green-600 text-white px-2 py-1 rounded text-xs">{t("approvals.approve")}</button>
                  )}
```

- [x] **Step 6: Gate the exemption approve buttons in ExemptionsPanel (soldier-profile modal)**

In `frontend/src/components/ExemptionsPanel.tsx`, change lines 239-258 from:

```tsx
                {canManage && (req.status === "pending_commander" || req.status === "pending_duty_manager") && (
                  <div className="flex items-center gap-2">
                    {req.status === "pending_commander" && (
                      <button
                        className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                        onClick={() => void onApproveCommanderStep(req.id)}
                        data-testid={`exemption-request-approve-${req.id}`}
                      >
                        {t("exemptions.approve_commander_step")}
                      </button>
                    )}
                    {req.status === "pending_duty_manager" && canApproveDutyManagerStep && (
                      <button
                        className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                        onClick={() => void onApproveDutyManagerStep(req.id)}
                        data-testid={`exemption-request-approve-${req.id}`}
                      >
                        {t("exemptions.approve_duty_manager_step")}
                      </button>
                    )}
```

to:

```tsx
                {canManage && (req.status === "pending_commander" || req.status === "pending_duty_manager") && (
                  <div className="flex items-center gap-2">
                    {req.status === "pending_commander" && req.can_approve_commander_step && (
                      <button
                        className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                        onClick={() => void onApproveCommanderStep(req.id)}
                        data-testid={`exemption-request-approve-${req.id}`}
                      >
                        {t("exemptions.approve_commander_step")}
                      </button>
                    )}
                    {req.status === "pending_duty_manager" && canApproveDutyManagerStep && req.can_approve_duty_manager_step && (
                      <button
                        className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                        onClick={() => void onApproveDutyManagerStep(req.id)}
                        data-testid={`exemption-request-approve-${req.id}`}
                      >
                        {t("exemptions.approve_duty_manager_step")}
                      </button>
                    )}
```

This keeps the existing `canManage`/`canApproveDutyManagerStep` props (they still gate whether the whole action row renders at all) and layers the new per-item, scope-and-level-accurate flags from Task 5 on top â€” closing the gap where `UnifiedSoldierModal`'s coarse global `isCommander`/`isDutyManager` booleans (no scope or level check) let a commander/DM see enabled buttons for a soldier outside their actual scope.

- [x] **Step 7: Run the tests to verify they pass**

Run: `npm test -- src/pages/ApprovalsPage.test.tsx`
Expected: PASS (all tests, including the two new ones)

Run: `npm run typecheck`
Expected: no errors.

- [x] **Step 8: Commit**

```bash
git add frontend/src/api/exemptions.ts frontend/src/api/soldiers.ts frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/ApprovalsPage.test.tsx frontend/src/components/ExemptionsPanel.tsx
git commit -m "fix: hide approve buttons for requests the current user cannot actually approve"
```

---

### Task 7: Backend â€” let plain soldiers view another soldier's basic (redacted) profile

**Files:**
- Modify: `backend/app/routes/soldiers.py:531-552`
- Test: `backend/tests/integration/test_soldiers_api.py`

**Interfaces:**
- Consumes: existing `can_see_private` (already used by `get_soldier` to decide field redaction).
- Produces: nothing new â€” same `SoldierOut` shape, just reachable for a wider set of viewers.

**Root cause:** `get_soldier` (`soldiers.py:531-539`) unconditionally calls `authorize(session, user, Action.SOLDIER_READ, ...)` for any non-self target. `Action.SOLDIER_READ` is only granted to commanders/duty-managers in scope (`authz.py:83-99`), so a plain `"soldier"` role gets a 403 for literally any other soldier's profile. The frontend (`SoldierModalContext.tsx:46-49`) treats any rejected `getSoldier` call as fatal and never opens the modal, alerting `"×œ× × ×™×ª×Ÿ ×œ×˜×¢×•×Ÿ ××ª ×¤×¨×˜×™ ×”×—×™×™×œ"`.

The sibling endpoint `get_soldier_duty_history` (`soldiers.py:490-513`) already handles this correctly: it skips `authorize()` for `is_plain_soldier`, then relies on `can_see_private` / an explicit event-type filter to redact anything sensitive. `get_soldier` already calls `can_see_private(session, user, s)` to decide `include_private` (`soldiers.py:549`) â€” that machinery already redacts `phone`/`gender`/`email` to `None` for an out-of-scope viewer (`_out`, `soldiers.py:174-208`) â€” so the fix is only to stop blocking the request before it reaches that logic.

Frontend edit controls in `UnifiedSoldierModal.tsx` are already correctly gated by `canManage`/`isSelf` (confirmed: edit pencil at line 173, tab visibility at lines 58-63, profile-save button at line 457) â€” no frontend change is needed there.

- [x] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_soldiers_api.py` (append at end of file; the file already imports `auth_headers`, `create_node`, `create_soldier`):

```python
def test_plain_soldier_can_view_another_soldiers_basic_profile(client: TestClient, admin_session: Session):
    """A plain soldier clicking another soldier's name should see a
    read-only, redacted profile â€” not a 403."""
    node = create_node(admin_session, level="branch", name="view_node")
    viewer = create_soldier(admin_session, personal_number="view_plain_001", hierarchy_node_id=node.id)
    other_node = create_node(admin_session, level="branch", name="view_other_node")
    target = create_soldier(
        admin_session, personal_number="view_target_001", hierarchy_node_id=other_node.id,
        phone="0501234567", gender="male",
    )
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(viewer))
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == target.full_name
    assert body["phone"] is None
    assert body["gender"] is None
```

(Adjust `create_soldier(..., phone=..., gender=...)` kwargs to whatever the helper in `tests/helpers.py` actually accepts â€” check its signature first; if it doesn't take those directly, set `target.phone`/`target.gender` on the model after creation and `admin_session.commit()` again before the request.)

- [x] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/integration/test_soldiers_api.py::test_plain_soldier_can_view_another_soldiers_basic_profile -v`
Expected: FAIL â€” 403 instead of 200.

- [x] **Step 3: Fix `get_soldier`**

In `backend/app/routes/soldiers.py`, change (`soldiers.py:531-539`):

```python
@router.get("/{soldier_id}", response_model=SoldierOut)
def get_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
```

to:

```python
@router.get("/{soldier_id}", response_model=SoldierOut)
def get_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    is_self = s.id == user.id
    is_plain_soldier = user.role == "soldier"
    if not is_self and not is_plain_soldier:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
```

This mirrors `get_soldier_duty_history`'s existing pattern exactly (`soldiers.py:497-502`). The rest of the function is unchanged â€” `include_private=can_see_private(session, user, s)` (line 549) already evaluates to `False` for a plain soldier viewing someone outside their scope, redacting `phone`/`gender`/`email`.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_soldiers_api.py::test_plain_soldier_can_view_another_soldiers_basic_profile -v`
Expected: PASS

- [x] **Step 5: Run the targeted test area to check for regressions**

Run: `pytest -m soldiers -q`
Expected: PASS â€” in particular, re-check `test_duty_manager_can_only_onboard_in_scope` and any existing `get_soldier` 403 tests still pass (this change only affects the plain-`"soldier"`-role branch; commanders/duty-managers/admins go through the same `authorize()` call as before).

- [x] **Step 6: Commit**

```bash
git add backend/app/routes/soldiers.py backend/tests/integration/test_soldiers_api.py
git commit -m "fix: let a plain soldier view another soldier's basic redacted profile instead of 403"
```

---

## Self-Review Notes

- **Spec coverage:** all 6 in-scope items covered â€” (1) exemption file 404 â†’ Task 1; (2) profile license-date label â†’ Task 2; (3) magic-byte + upload-abuse hardening client+server â†’ Tasks 3â€“4; (4) approve buttons shown to unauthorized users â†’ Tasks 5â€“6; (5) plain-soldier detail-view 403 â†’ Task 7. The originally-reported DateInput picker bug is explicitly out of scope (confirmed no longer reproducible).
- **Placeholder scan:** Task 3 Step 1 contains one intentionally-flagged non-final snippet (the `test_upload_gimelim_attachment_rejects_unsanitized_filename` `pass` stub) with an explicit instruction not to commit it and a real replacement test immediately below â€” this is a known gap where the exact fixture helper name in `test_gimelim_api.py` couldn't be determined without reading that file's full body during planning; the implementer must open that file first and adapt the real test to its existing helper.
- **Type consistency:** `can_approve` / `can_approve_commander_step` / `can_approve_duty_manager_step` names match exactly between backend Pydantic models (Task 5) and frontend TypeScript interfaces + JSX usage (Task 6).
