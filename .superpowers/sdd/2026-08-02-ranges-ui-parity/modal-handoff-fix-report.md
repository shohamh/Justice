# Modal handoff history race fix

## Change

`useModalBackClose` now keeps deferred cleanup state at module scope so a newly mounted replacement modal can cancel the previous modal's pending `history.back()` during the same handoff. Each hook-owned history entry has a unique ID; cleanup and deferred processing require that exact ID to remain current, preserving protection against newer unrelated navigation entries.

Added a regression test covering unmounting one hook and mounting its replacement before the cleanup microtask runs. The replacement remains mounted, does not receive a false `onClose`, and retains the active modal history entry.

## Verification

- Hook tests: 10/10 passed
- Relevant ranges/modal tests: 39/39 passed
- `npm run typecheck`: passed
- `npm run lint`: passed

No backend or unrelated files were changed.
