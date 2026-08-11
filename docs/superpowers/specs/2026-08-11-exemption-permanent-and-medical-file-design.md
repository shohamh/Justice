# Exemption requests: permanent-exemption flow + mandatory medical file

Date: 2026-08-11

## Problem

Two usability/integrity gaps in the exemption-request flows (registration and
the self-service "My Requests" page):

1. **Start date is always required**, even for exemptions that will end up
   permanent. For a permanent exemption the meaningful "start date" is the
   date it's officially approved — not whatever the requester happened to
   type. It's also not obvious in the UI that the end date can be left empty.
2. **Medical exemptions don't require an attached document.** In the
   registration flow there is no file-upload UI at all. In `MyRequestsPage`
   the "file required if medical" rule exists but is enforced client-side
   only, and structurally can't easily be made atomic because today the file
   is uploaded in a second, separate call after the request already exists.

## Scope

In scope: registration (`RegisterPage.tsx` / `POST /auth/register`) and the
self-service exemption request form (`MyRequestsPage.tsx` /
`POST /me/exemption-requests`).

Out of scope: the commander-escalation exemption flow
(`CommanderEscalateRequest` / `submit_commander_escalation`), and already
-approved `SoldierExemption` records. Neither was reported as broken; both
would need their own review if the same rules should extend to them later.

## Part A — Permanent-exemption toggle

### Behavior

A "פטור קבוע" (permanent exemption) toggle sits next to the date fields, in
both the registration exemption rows and the `MyRequestsPage` request form.
Checking it:

- Disables **both** the start-date and end-date inputs (today,
  `MyRequestsPage` only disables end-date; registration disables neither).
- Clears both values. The request is submitted with `start_date: null,
  end_date: null`.

### Validation rule

No new boolean flag is introduced. Permanence is inferred the same way it
already is for approved exemptions (`SoldierExemption.end_date IS NULL` means
"no expiry"):

- If `end_date` is provided, `start_date` must also be provided
  (unchanged from today).
- If `start_date` is omitted, `end_date` must also be omitted. That
  combination *is* "permanent, start date pending approval."
- Anything else (e.g. `start_date` omitted but `end_date` given) is a 400
  `start_date_required`.

### Where start_date gets filled in

`ExemptionRequest.start_date` can now be `NULL` and stays that way through
`pending_commander` → `pending_duty_manager`. At final approval
(`approve_duty_manager_step`, `backend/app/services/exemption_requests.py`),
if `req.start_date is None`, set it to `date.today()` before copying it onto
the new `SoldierExemption`. This is "the date of official approval." No other
approval step (commander step, rejection) needs to touch it.

### Data model change

- `ExemptionRequest.start_date`: `Mapped[date]` → `Mapped[date | None]`,
  nullable in the DB. Requires an Alembic migration
  (`alembic revision -m "make exemption_requests.start_date nullable"`).
- `SoldierExemption.start_date` is unaffected — always populated by the time
  a `SoldierExemption` row is created.

### API changes

- `CreateExemptionRequest.start_date`: `str` (regex-validated) → `str | None`.
- `ExemptionRequestOut.start_date`: `str` → `str | None`.
- Registration payload: each exemption row's `start_date` becomes optional;
  `registration.register()`'s per-row validation
  (`backend/app/services/registration.py` lines 122-135) updated to the rule
  above instead of unconditionally requiring `start_date`.

### Display

A pending request with `start_date IS NULL` shows a placeholder such as
"ייקבע באישור" (will be set upon approval) instead of a blank or malformed
date, anywhere `ExemptionRequestOut.start_date` is rendered.

## Part B — Mandatory file for medical exemptions, enforced server-side

### Behavior

Request creation becomes atomic: exemption fields and any attached files are
submitted together, and the server rejects the whole submission with 400
`medical_exemption_requires_file` if the exemption type's `is_medical` is
true and no valid file was attached. Non-medical types keep file upload
optional, same dropzone UI as today.

### `POST /me/exemption-requests`

Changes from a JSON body to `multipart/form-data`:

- `payload`: JSON string, same shape as today's `CreateExemptionRequest`.
- `files`: zero or more `UploadFile` parts.

Server validates each file with the existing checks (MIME allow-list, 10MB
cap, magic-byte signature match — currently duplicated inline at
`backend/app/routes/exemption_requests.py` lines 38-47 and 501-508) via one
shared helper function, used by this endpoint and kept for the existing
standalone `POST /me/exemption-requests/{id}/files` endpoint (retained
unchanged, for admins/commanders attaching files to an existing request
later). If `is_medical` and `files` is empty after validation, the whole
request 400s and nothing is persisted (`submit_request` + file rows created
in the same DB transaction, committed together).

### `POST /auth/register`

Changes from a JSON body to `multipart/form-data`:

- `payload`: JSON string, same shape as today's `RegisterRequest`.
- Per-exemption-row files under form field names `exemption_files_{i}`,
  where `i` is the row's index in the `exemption_requests` array (a row can
  have zero, one, or many files under its own key).

The route reads `await request.form()` to collect the dynamically-named file
fields (FastAPI's static `File(...)` params can't express a variable number
of per-row keys), validates each medical row has ≥1 valid file using the
same shared helper as above, then calls `registration.register(...)` inside
one transaction — a registration with a missing required medical file fails
atomically before any DB rows (soldier, enrollment request, exemption
requests) are created.

### Frontend

- `RegisterPage.tsx` step 3: add the same file-dropzone control
  `MyRequestsPage.tsx` already has (client-side magic-byte pre-check via
  `frontend/src/utils/fileValidation.ts`, 10MB cap), one per exemption row,
  shown/required when that row's selected exemption type's `is_medical` is
  true. Step-advance button disabled client-side when a medical row has no
  files attached (fast feedback; server is the actual enforcement).
- `MyRequestsPage.tsx`: replace the current "create, then upload each file"
  two-step submit (`onErSubmit`,
  `frontend/src/pages/MyRequestsPage.tsx` lines 139-166) with a single
  multipart POST.
- `frontend/src/api/auth.ts` `register()` and `frontend/src/api/exemptions.ts`
  `submitExemptionRequest()` (or equivalent) switch to building `FormData`
  instead of a plain JSON body.

## Error handling summary

| Condition | Error |
|---|---|
| `end_date` given without `start_date` | 400 `start_date_required` |
| `start_date` < today or `end_date` < `start_date` (both given) | 400 `bad_date_range` (unchanged) |
| Medical exemption type, no valid file attached | 400 `medical_exemption_requires_file` |
| File fails MIME/size/magic-byte check | 400 `invalid_file_type` / `file_too_large` (unchanged) |

## Testing

Backend (pytest):
- Permanent request (`start_date=None, end_date=None`) → approved →
  `SoldierExemption.start_date == date.today()` at approval time.
- Non-permanent request with `end_date` but no `start_date` → 400.
- Medical exemption request/registration with no file → 400,
  no DB rows persisted.
- Medical exemption request/registration with one valid file → 201.
- Non-medical exemption without a file → still succeeds (unchanged).

Frontend (vitest):
- Permanent toggle disables and clears both date inputs, in both
  `RegisterPage` and `MyRequestsPage`.
- Medical row blocks submit/step-advance with no file attached, in both
  pages.

## Migration / rollout notes

- Alembic migration relaxes `exemption_requests.start_date` to nullable —
  backward compatible, no backfill needed (existing rows already have a
  value).
- The `/auth/register` and `/me/exemption-requests` content-type change
  (JSON → multipart) is a breaking API change; frontend and backend land
  together in the same change.
