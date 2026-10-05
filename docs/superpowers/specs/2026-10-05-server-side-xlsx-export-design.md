# Server-Side XLSX Export — Design

Date: 2026-10-05
Status: Draft for review
Audit baseline: `2e1515f7` (`dev`)

## Context

The frontend uses SheetJS (`xlsx` 0.18.5) to generate several table exports and to parse backend-generated workbooks so the planning export can merge sheets in the browser. The security audit found high-severity SheetJS advisories and no patched npm release. The frontend does not currently parse user-selected uploaded workbooks; the `XLSX.read` inputs are downloaded from Justice APIs. The backend already depends on `openpyxl` and uses it for config, import-data, potential, and other exports.

The current user-visible exports are:

- Transparency and potential table exports from `ExcelExportButton`, which honor the visible columns, localized headers, current filters, and row ordering.
- The planning export, which combines client-prepared transparency/sub-unit sheets with selected server-generated config and data sheets.

## Goals

1. Remove the vulnerable `xlsx` package from the frontend dependency graph.
2. Preserve `.xlsx` downloads, sheet names, headers, selected rows, ordering, and filters.
3. Stop parsing downloaded XLSX bytes in the browser.
4. Reuse the backend's existing `openpyxl` workbook-writing patterns and existing authorization rules.
5. Ensure user-provided string cells remain inert text and cannot become workbook formulas.

## Design

### Shared backend workbook builder

- Add a focused workbook-export service using `openpyxl`; it creates workbooks from validated rows and/or invokes existing backend sheet writers.
- Add an authenticated `POST /api/exports/xlsx` endpoint for table exports. The request contains a safe filename, sheet name, header row, and bounded primitive cell rows. It does not read or parse an XLSX upload and does not query additional data on behalf of the caller.
- Add an authenticated planning-export endpoint that accepts the selected config/data sheet keys and the already-authorized transparency/sub-unit row matrices prepared by the frontend. It creates one workbook server-side, using existing config/import sheet writers for server-backed sheets and the shared matrix writer for client-prepared sheets. Retain the role restrictions currently enforced by `/config/export` and `/import/export`.
- Apply the same response MIME type and attachment-download behavior as the current UI. Use the shared Axios client with `responseType: "blob"` so the existing in-memory Bearer token remains the API credential.

### Payload and cell safety

- Validate worksheet names, safe filename characters, row/column/cell counts, total cells, and total request size. Choose numeric limits from measured current export sizes so ordinary large exports continue to work.
- Accept only strings, finite numbers, booleans, and null values. Reject invalid XML control characters and strings exceeding Excel's cell limit.
- Write every user-provided string as a string cell, even if it begins with `=`, `+`, `-`, or `@`; do not infer formulas from client data.
- Do not persist export request data. Return a generated workbook as a response only.

### Frontend migration

- Replace `ExcelExportButton`'s local SheetJS workbook construction with a request to the table-export endpoint. Keep `exportValueOf` so the same visible values are sent.
- Change `ExportPage` to send its client-computed transparency and sub-unit matrices plus selected config/data sheet keys to the planning-export endpoint. Remove the two XLSX response parses and browser-side workbook merge.
- Replace tests that construct/inspect workbooks with assertions over the submitted matrix and download response. Validate actual workbook contents in backend tests using `openpyxl`.
- Remove `xlsx` from production and development dependencies after every frontend import has been removed.

## Scope

Expected frontend changes include `frontend/src/components/ExcelExportButton.tsx`, `frontend/src/pages/planning/ExportPage.tsx`, `frontend/src/pages/TransparencyPage.tsx`, `frontend/src/pages/planning/PotentialPage.tsx`, API wrappers, and their tests. Backend changes include a workbook-export service, request schemas, an authenticated export route, and reuse/refactoring of the existing writers in `backend/app/routes/config_export.py` and `backend/app/routes/import_excel.py`.

## Acceptance criteria

1. All existing export buttons still download `.xlsx` files with the same workbook names, worksheet names, column order, localized headers, filtered rows, and values.
2. No frontend code imports or parses SheetJS; `xlsx` is absent from the frontend dependency tree.
3. Planning exports preserve existing role filtering for config/data sheets and reject unknown sheet keys.
4. String cells such as `=1+1` are stored as text, not formulas. Invalid and oversized request payloads fail with a bounded client error.
5. Export endpoints are authenticated, do not persist the request matrix, and use the existing scope/role contracts for any server-fetched data.
6. Existing frontend/backend export tests are updated, and workbook contents are verified from generated bytes with `openpyxl`.

## Non-goals

- Changing import/upload workbook parsing, which remains server-side with `openpyxl`.
- Changing users' `.xlsx` file format or export button placement.
- Accepting arbitrary workbook files through the new export endpoints.
- Adding a new third-party JavaScript spreadsheet library.
