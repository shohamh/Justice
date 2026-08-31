# Frontend Runtime Response Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent malformed or unexpected API payloads from causing uncaught frontend render exceptions across the Justice application.

**Architecture:** Validate response shape in API adapters before values enter React state, using small endpoint-specific guards that preserve the declared DTO types. Components and hooks will still use safe fallbacks where asynchronous state is initially empty, and screens will show their existing or newly added load-error states when required data cannot be used.

**Tech Stack:** React, TypeScript, Axios, TanStack Query, Vitest, Testing Library, ESLint.

**Spec:** Approved in chat on 2026-08-30: audit frontend API/state/render boundaries, guard collections/objects/nullables, show visible errors instead of render crashes, add regression tests, and run full frontend verification.

## Global Constraints

- Do not change valid API contracts or hide required-data failures as successful empty states.
- Preserve Hebrew i18n and RTL behavior.
- Add regression tests at public API or rendered-component seams, not private helpers.
- Keep unrelated working-tree changes untouched.
- Run frontend commands from `frontend/`.

---

### Task 1: Inventory runtime response assumptions

**Files:**
- Inspect: `frontend/src/api/**/*.ts`
- Inspect: `frontend/src/hooks/**/*.{ts,tsx}`
- Inspect: `frontend/src/pages/**/*.{ts,tsx}`
- Inspect: `frontend/src/components/**/*.{ts,tsx}`
- Create: `docs/superpowers/reports/2026-08-30-frontend-runtime-response-audit.md`

**Interfaces:**
- Produces a table of each API response consumed as a collection or required object, its current runtime guard status, consumer locations, and chosen behavior for malformed data.

- [ ] **Step 1: Enumerate response consumers and collection operations**

Run:

```powershell
rg -n "api\.(get|post|put|patch|delete)|\.map\(|\.filter\(|\.reduce\(|\.find\(|Object\.keys\(|Object\.entries\(" frontend/src -g '*.{ts,tsx}'
```

- [ ] **Step 2: Classify each finding**

Record whether the value is validated in its API adapter, validated in a hook, guaranteed by a local constant, or unsafe. Mark required objects separately from optional collections.

- [ ] **Step 3: Write the audit report**

For each unsafe finding, record the exact file/line, expected shape, malformed-shape behavior, regression seam, and target fix file. Do not edit application code in this task.

- [ ] **Step 4: Review the inventory for duplicates**

Group repeated patterns by API adapter or shared hook so one fix protects all consumers. Exclude static arrays and values already narrowed by a runtime predicate.

- [ ] **Step 5: Commit the inventory**

```powershell
git add docs/superpowers/reports/2026-08-30-frontend-runtime-response-audit.md
git commit -m "docs: inventory frontend response-shape risks"
```

### Task 2: Harden collection API adapters

**Files:**
- Modify: `frontend/src/api/*.ts` identified by Task 1 as returning collections
- Test: matching `frontend/src/api/*.test.ts` files, creating focused tests where absent

**Interfaces:**
- Each collection-returning adapter returns `Promise<DTO[]>` and guarantees an array at runtime.
- Malformed optional-list responses return `[]` only where the existing screen treats an empty list as valid; required-list adapters throw a descriptive error for the hook/query to display.

- [ ] **Step 1: Write one failing test per adapter family**

Use the public adapter and mock Axios at `../api/client`:

```ts
it("does not return a non-array payload to consumers", async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });
  await expect(listTheCollection()).resolves.toEqual([]);
});
```

For required collections, assert rejection with a stable `Invalid <resource> response` error instead.

- [ ] **Step 2: Run the focused adapter tests and observe failure**

```powershell
npx vitest run src/api/<adapter>.test.ts
```

- [ ] **Step 3: Add endpoint-boundary runtime checks**

Use the narrow pattern already established by `dutyConfig.ts` and `levelTypes.ts`:

```ts
const data = (await api.get<unknown>("/resource")).data;
return Array.isArray(data) ? data as ResourceDTO[] : [];
```

Use throwing validation when silently returning `[]` would make a required screen appear valid.

- [ ] **Step 4: Run focused tests, typecheck, and lint**

```powershell
npx vitest run src/api/<adapter>.test.ts
npm run typecheck
npm run lint
```

- [ ] **Step 5: Commit the adapter slice**

```powershell
git add frontend/src/api
git commit -m "fix: validate frontend collection responses"
```

### Task 3: Harden hooks and required object responses

**Files:**
- Modify: `frontend/src/hooks/*.ts`, `frontend/src/hooks/*.tsx` identified by Task 1
- Modify: matching object-returning files under `frontend/src/api/`
- Test: matching hook/page tests under `frontend/src/`

**Interfaces:**
- Hooks never place an object, `null`, or other malformed value into state typed as a DTO or DTO array.
- Hooks expose an error/loading signal where the screen needs to distinguish “not loaded” from “failed to load”.

- [ ] **Step 1: Write a failing hook or component test for each unsafe hook**

Mock the public API function with malformed data and assert the rendered screen remains mounted and exposes an alert or existing load-error state.

- [ ] **Step 2: Run those tests and confirm the uncaught render error**

```powershell
npx vitest run src/hooks/<hook>.test.tsx src/pages/<page>.test.tsx
```

- [ ] **Step 3: Validate required object payloads before state updates**

Use explicit object predicates for required fields, keep state at its safe initial value on failure, and expose the failure to the consuming screen. Do not cast arbitrary payloads directly to DTOs.

- [ ] **Step 4: Run focused tests and static checks**

```powershell
npx vitest run src/hooks/<hook>.test.tsx src/pages/<page>.test.tsx
npm run typecheck
npm run lint
```

- [ ] **Step 5: Commit the hook/object slice**

```powershell
git add frontend/src/hooks frontend/src/api frontend/src/pages frontend/src/components
git commit -m "fix: keep malformed API objects out of frontend state"
```

### Task 4: Harden component render boundaries

**Files:**
- Modify: component/page files identified by Task 1 that directly map/filter unvalidated values
- Test: matching component/page test files

**Interfaces:**
- No render path calls collection methods on unvalidated data.
- Required-data failures render a translated alert or the screen’s established error state; optional collections render their valid empty state.

- [ ] **Step 1: Add regression tests for each remaining direct-consumer path**

For each screen, provide malformed API data through its public mocked API or hook and assert no uncaught error plus the intended visible state.

- [ ] **Step 2: Run the tests red before implementation**

```powershell
npx vitest run src/pages/<page>.test.tsx src/components/<component>.test.tsx
```

- [ ] **Step 3: Add the smallest render guard**

Prefer fixing the adapter or hook first. Add a component guard only when the component accepts external data or when it is the last boundary before rendering.

- [ ] **Step 4: Run the focused tests and static checks**

```powershell
npx vitest run src/pages/<page>.test.tsx src/components/<component>.test.tsx
npm run typecheck
npm run lint
```

- [ ] **Step 5: Commit the component slice**

```powershell
git add frontend/src/pages frontend/src/components frontend/src/hooks
git commit -m "fix: prevent malformed data render crashes"
```

### Task 5: Whole-frontend verification and handoff

**Files:**
- Inspect: all changed files and `docs/superpowers/reports/2026-08-30-frontend-runtime-response-audit.md`

**Interfaces:**
- The audit report lists every reviewed unsafe pattern, all fixes, and explicitly deferred findings.

- [ ] **Step 1: Run the complete frontend verification**

```powershell
npm run typecheck
npm run lint
npm test -- --run
```

- [ ] **Step 2: Re-run the inventory search**

```powershell
rg -n "\.map\(|\.filter\(|\.reduce\(|\.find\(" frontend/src -g '*.{ts,tsx}'
```

Review every remaining hit and document why it is safe or what remains deferred.

- [ ] **Step 3: Review the final diff for unrelated changes**

```powershell
git diff --check
git status --short
git log --oneline --decorate -8
```

- [ ] **Step 4: Merge the feature branch into `dev`**

Use the project `merge-worktree-to-dev` workflow only after tests and review pass. Do not push unless explicitly requested.

