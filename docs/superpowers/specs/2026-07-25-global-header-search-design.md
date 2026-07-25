# Global header search — design

## Summary

A fuzzy search accessible from the header: a magnifying-glass icon opens a
panel sliding down from the top of the page. It searches across pages,
soldiers, duties, units, help topics, and quick actions, with full keyboard
navigation (↑/↓ to move, Enter to open, Esc to close) and a Ctrl/Cmd+K global
shortcut.

## Goals

- One place to jump to any page, soldier profile, duty/shift, unit, help
  topic, or common create-flow, without needing to know where it lives in the
  nav.
- Fast, fuzzy matching (typo-tolerant), not exact-substring only.
- Results respect the current user's permissions — no dead links to pages
  they can't open, no soldiers/duties outside their visibility scope.
- Full keyboard operability.

## Non-goals (v1)

- No search history / recent searches.
- No full-text search over help article bodies (just tab-level topics).
- No pagination of results — capped, "top N per category" only.
- No changes to `HelpModal`'s internal content, only how it's opened.

## Architecture

### Backend: new `/search` endpoint

New file `backend/app/routes/search.py`, `GET /search?q=<text>`. For a given
query string, runs lookups for the two data-backed categories (soldiers,
duties) and returns a grouped, capped result set (e.g. top 5–8 per category).

Both lookups reuse **existing** RBAC scoping rather than introducing new
visibility rules:

- **Soldiers**: same scoping as `list_soldiers`
  (`backend/app/routes/soldiers.py:299-329`) — admins see everyone, others
  are scoped via `scope_root_ids(session, user)` against
  `hierarchy_node.path_ids`, with the same `include_private` gating. Matches
  against `full_name` / `personal_number` (fuzzy/trigram or simple
  `ILIKE`-with-normalization — implementation detail for the plan).
- **Duties/shifts**: same scoping as `calendar_shifts`
  (`backend/app/routes/calendar.py:183-209`) — `scope_root_ids` +
  `Action.HIERARCHY_READ` via `can()`. A plain soldier sees exactly the
  duties they'd already see on their calendar, no narrower and no broader.
  Matches duty type name/description text, plus flexibly parsed date
  fragments (e.g. "25/07", "2026-07-25", partial month names) against shift
  dates.
- **Units/hierarchy nodes**: matched against the hierarchy tree the user can
  already read (same `scope_root_ids` scoping). Can be served by the same
  endpoint or resolved client-side from an already-fetched scoped hierarchy
  tree — implementation detail for the plan, whichever avoids duplicate
  fetching.

Response shape: grouped by category, each entry with enough data to render a
row (label, subtitle, navigation target) and to sort by fuzzy match quality.

### Frontend: `HeaderSearch` component

New `frontend/src/components/HeaderSearch.tsx`, mounted in `Layout.tsx`'s
header (next to notifications/help icons, `Layout.tsx:34-70`).

- **Trigger**: click the icon, or press Ctrl/Cmd+K from anywhere in the app.
  Opens an overlay + panel animating down from the top; focus moves to the
  input automatically.
- **Client-side categories** (no backend round trip, filtered by what the
  current user can access before matching):
  - **Pages**: new static registry `frontend/src/searchRegistry.ts` — one
    entry per route in `App.tsx:64-112`: `{ id, labelKey, descriptionKey,
    path, requiredAction? }`. Visibility check reuses the same permission
    logic `UnifiedNav.tsx` uses to hide nav tabs.
  - **Quick actions**: entries in the same registry file, `{ id, labelKey,
    path, requiredAction? }` pointing at create/new-item flows (e.g. "Create
    duty", "Submit exemption request", "Add soldier"), gated the same way.
  - **Help topics**: one entry per `HelpModal` tab (`swaps`, `algorithm`,
    `fairness`, `deep`, `gimelim`) — `{ id, labelKey, keywords[] }`. The
    `gimelim` entry only appears when `gimelimEnabled`, mirroring
    `buildTabs()` in `HelpModal.tsx:12-23`. Clicking opens `HelpModal` with
    `initialTab` set to the matched tab id — no changes needed inside
    `HelpModal` itself, it already accepts this prop (`HelpModal.tsx:9`).
  - All three matched with `fuse.js` (already a dependency), same library
    already used in `SoldierSearchAutocomplete.tsx`.
- **Backend-provided categories** (soldiers, duties, units): a single
  debounced (~200ms) call to `GET /search?q=` as the user types. Skipped
  entirely for empty/whitespace queries.
- **Rendering**: results grouped by category, each group with a header and
  each row prefixed with a category icon:

  | Category | Icon |
  |---|---|
  | Page | 📄 |
  | Soldier | 👤 |
  | Duty | 📅 |
  | Unit | 🏛️ |
  | Quick action | ⚡ |
  | Help | ❓ |

  (Exact glyphs may be refined during implementation to match the app's
  existing emoji-icon style, e.g. as seen in `HelpModal.tsx`'s `FlowStep`.)

- **Keyboard navigation**: a single flat "roving" selection index across all
  groups in display order. ↓/↑ moves selection (wraps or clamps —
  implementation detail), Enter navigates to the selected result, Esc closes
  and clears the query. RTL (`index.html:2`, `dir="rtl"`) doesn't affect
  vertical arrow-key semantics.
- **Empty state**: nothing shown until the user types (no query = no
  results, no "recent searches" in v1).
- **No-results state**: simple "no matches" message.
- **Backend error handling**: if `/search` fails, show an inline error for
  the backend-provided groups only; client-side groups (pages, quick
  actions, help) keep working regardless — graceful degradation, no reason
  a network hiccup should break in-app navigation.

## Data flow

1. User opens panel (click icon or Ctrl/Cmd+K) → input focused, empty state.
2. User types → each keystroke (debounced) does two things in parallel:
   - Synchronous Fuse.js match over the pre-filtered (role-gated) local
     registries (pages, quick actions, help).
   - Debounced fetch to `GET /search?q=` for soldiers/duties/units.
3. Results render grouped, capped per category, each row iconed per category.
4. Keyboard or mouse selects a row → navigate to its target path (or open
   `HelpModal` with the right tab for help results) → panel closes.

## Testing

- **Backend**: unit tests on `/search` verifying it reuses `list_soldiers`
  and `calendar_shifts` RBAC scoping — a soldier's search results never
  include out-of-scope soldiers or duties, matching what those existing
  endpoints already return for the same user/query.
- **Frontend**: component tests for `HeaderSearch` covering: keyboard nav
  (↓/↑/Enter/Esc), debounce behavior, role-based filtering of the
  pages/quick-actions/help registries, and graceful degradation when
  `/search` fails.
