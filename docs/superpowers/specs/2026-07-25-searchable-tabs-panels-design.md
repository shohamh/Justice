# Searchable tabs and panels — design spec

## Goal

Extend the existing global header search (Ctrl/Cmd+K) so it can find and
jump directly to specific tabs within multi-tab pages, not just whole
pages. A result for a tab shows as `"PageName > TabName"`, and selecting it
navigates straight to that tab (not just the page's default view).

## Current state

`frontend/src/searchRegistry.ts` defines three registry types today —
`PageEntry` (whole pages), `QuickActionEntry`, `HelpTopicEntry` — each
filtered by `canAccess(user)` and fuzzy-matched via Fuse.js in
`frontend/src/components/HeaderSearch.tsx`. Selecting a page entry calls
`navigate(entry.path)`; selecting a help entry calls `openHelp(entry.id)`
to open the relevant tab in the existing `HelpModal`.

Four pages already support deep-linking to an internal tab via a `?tab=`
URL search param, read on mount with `useSearchParams()` — no page code
changes are needed to make them jump-to-able, only new registry entries
that navigate to `path?tab=value`:

| Page | Path | `PageEntry` already registered as | Tab param values |
|---|---|---|---|
| Admin Settings | `/admin/settings` | `page-admin-settings` | `0`,`1`,`2`,`3` (numeric index) |
| Approvals | `/approvals` | `page-approvals` | `constraints`,`exemptions`,`field_updates`,`swaps`,`enrollment`,`transfers` |
| Swaps | `/swaps` | `page-swaps` | `mine`,`board`,`incoming`,`pending` |
| Transparency | `/transparency` | `page-transparency` | `soldiers`,`sub_units` |

One additional page (Import Session Review, `/import/sessions/:id`) has
tabs but requires a dynamic session ID in its path — there is no single
fixed destination for search to jump to, so it is explicitly out of scope.

## Scope: which tabs get a registry entry

Each page's *default* tab (the one shown with no `?tab=` param, or
`tab=0`) is already reachable via the existing `PageEntry` for that page —
adding a tab-specific entry for it would just duplicate that page entry
with a confusing `"PageName > PageName"`-shaped label. So only the
**non-default** tabs get new entries: 12 total.

| Page | Tab param | Label (reuses page's own existing i18n key) |
|---|---|---|
| Admin Settings | `1` | `nav.admin_invite_codes` |
| Admin Settings | `2` | `nav.admin_changelog` |
| Admin Settings | `3` | `nav.admin_bug_reports` |
| Approvals | `exemptions` | `approvals.tab_exemptions` |
| Approvals | `field_updates` | `soldier_profile.field_updates_tab` |
| Approvals | `swaps` | `swaps.title` |
| Approvals | `enrollment` | `enrollment.tab` |
| Approvals | `transfers` | `approvals.tab_transfers` |
| Swaps | `board` | `swaps.tab_board` |
| Swaps | `incoming` | `swaps.tab_incoming` |
| Swaps | `pending` | `swaps.tab_pending` |
| Transparency | `sub_units` | `search.tabs.transparency_sub_units` (new key — Transparency's own tab bar hardcodes the Hebrew string rather than using i18n, so this is a new key added purely for the search registry, value `"תתי יחידות"`) |

## Data model

New type in `frontend/src/searchRegistry.ts`:

```typescript
export interface TabEntry {
  id: string;
  pageLabelKey: string;   // reuses an existing search.pages.* key
  labelKey: string;       // the tab's own existing i18n key
  keywords: string[];
  path: string;           // page path, no query string
  tabParam: string;       // value to set as ?tab=
  canAccess: (user: SearchUser | null) => boolean;
}

export function getTabEntries(): TabEntry[] { /* the 12 entries above */ }
```

`canAccess` for every tab reuses its parent page's existing access
function (e.g. all Admin Settings tabs use `isAdmin`, all Approvals tabs
use `canApprove`) — a tab is never reachable by a user who couldn't reach
the page itself.

Each entry's `keywords` array is a short list of Hebrew search terms
(the tab's own label plus one or two natural synonyms), following the
same style as existing `PageEntry.keywords`.

## HeaderSearch integration

In `frontend/src/components/HeaderSearch.tsx`:

- Add `"tab"` to the `FlatResult` union: `{ kind: "tab"; key: string; entry: TabEntry }`.
- Add a `tabFuse = new Fuse(accessibleTabs, { keys: ["keywords"], threshold: 0.4 })`, mirroring `pageFuse`/`actionFuse`/`helpFuse`.
- `labelFor` for `"tab"`: `` `${t(r.entry.pageLabelKey)} > ${t(r.entry.labelKey)}` ``.
- `handleSelect` for `"tab"`: `` navigate(`${r.entry.path}?tab=${r.entry.tabParam}`) ``.
- New result group in the `groups` array: icon `📑`, title key `search.categories.tab` (new key, value `"לשונית"`).

## Help topic labeling (consistency change)

Existing help-topic results currently show just their own label (e.g.
`"🔄 החלפות"`). For consistency with the new `"PageName > TabName"`
convention, `labelFor` for the `"help"` kind changes from `t(r.entry.labelKey)`
to `` `${t("search.categories.help")} > ${t(r.entry.labelKey)}` `` — the
`search.categories.help` key already exists (value `"עזרה"`), so results
become e.g. `"עזרה > 🔄 החלפות"`. No change to `HelpModal` itself or to
`getHelpTopicEntries()`.

## i18n

New keys added to `frontend/src/i18n/he.json` under `search`:
- `categories.tab`: `"לשונית"`
- `tabs.transparency_sub_units`: `"תתי יחידות"`

All other labels reuse existing keys already present in the file (see
table above) — no other new translation strings needed.

## Testing

- `frontend/src/searchRegistry.test.ts` (existing file): add cases for
  `getTabEntries()` — correct count (12), correct `canAccess` gating per
  page's access level (e.g. Admin Settings tabs hidden from non-admins).
- `frontend/src/components/HeaderSearch.test.tsx` (existing file): add
  cases — typing a tab's keyword surfaces it under the new "לשונית" group
  with the `"PageName > TabName"` label; selecting it navigates to
  `path?tab=value`; a help-topic result now renders with the `"עזרה > "`
  prefix.

## Out of scope

- Import Session Review's tabs (no fixed URL to jump to).
- Any page not already using the `?tab=` URL param convention — no page
  is being converted to support deep-linking as part of this change, only
  existing deep-linkable tabs are indexed.
- Backend search (`backend/app/services/search.py`) — this feature is
  entirely frontend-registry-driven, no backend changes.
