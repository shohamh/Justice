# Native Browser Dialog Replacement Design

Date: 2026-08-29

## Goal

Replace native frontend `alert()`, `confirm()`, and `prompt()` calls with
the application's styled, RTL-aware modal interaction patterns. All visible
copy must come from i18n and have Hebrew translations.

## Scope

The production frontend currently contains native confirmation calls in
hierarchy, shifts, imports, duty management, deputies, templates, ranges,
algorithm actions, soldier actions, and related flows. It also contains
native alerts for operation errors and validation feedback, and prompts for
operation reasons, notes, and other short inputs. Documentation and tests that
mention browser APIs are not runtime call sites and are not changed unless
their expectations must follow the new public behavior.

## Design

Create shared modal components using the existing `EventDetailModal` and
`useModalBackClose` behavior:

1. Confirmation dialog: translated title/message, translated confirm and
   cancel buttons, optional danger styling, and an `onConfirm` callback.
2. Message dialog: translated title/message and one translated close button,
   used where code previously called `alert`.
3. Input dialog: translated title/message/label, a controlled text input or
   textarea, translated confirm/cancel buttons, and an `onConfirm(value)`
   callback. Cancellation returns no value; validation and trimming preserve
   each existing prompt's semantics.

The components will live in a shared frontend component location rather than
inside the ranges feature. The existing ranges confirmation component will be
reused or moved without changing its reason-field capability.

## Migration Rules

- Convert each synchronous native call into local modal state plus a callback
  that invokes the original operation.
- Do not mutate data until the user confirms.
- Preserve existing async loading, error handling, permission checks, and
  operation-specific danger styling.
- Replace hardcoded dialog copy with i18n keys; dynamic values remain
  interpolation parameters.
- Keep prompts that collect reasons/notes as input dialogs rather than
  confirmations.
- Replace failure/validation alerts with message dialogs without changing
  the underlying error text or translation fallback.
- Do not change backend APIs or business rules.

## Testing

Add shared-component tests for:

- confirm, cancel, close, danger styling, and keyboard/back behavior;
- message close behavior;
- prompt confirm, cancel, empty-input behavior, and submitted value.

Update representative flow tests, including hierarchy deletion, to assert
that native browser APIs are not used and that the original action only runs
after modal confirmation. Finish with a source search over runtime frontend
files proving no native `alert`, `confirm`, or `prompt` calls remain.
