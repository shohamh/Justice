# Range Eligibility Guidance and Calendar Warnings

## Goal

Make weapon-range eligibility visible and actionable as information for planners and commanders across the ranges page, commander dashboard, unit calendars, upcoming duties, and shift details, while removing the redundant standalone ineligibility navigation item.

## Confirmed eligibility rule

All user-facing warnings and counts use the same rule as `backend/app/services/weapon_eligibility.py`:

- A duty with no `required_range_type` has no weapon-eligibility warning.
- Qualification tiers are hierarchical: אל״ל covers אל״ל, מטווח חי, and מטווח לייזר; מטווח חי covers מטווח חי and מטווח לייזר; מטווח לייזר covers only מטווח לייזר.
- Evaluate eligibility on the duty's scheduled date, not only on today's date.
- An existing qualification qualifies when its `valid_until` covers the duty date.
- A future planned main assignment qualifies when it is non-reserve, non-draft, not disqualified by a pending excusal under the current setting, has a sufficient range tier, and its projected validity window (assignment date through assignment date plus configured validity days) covers the duty date.
- System toggles for the ranges module, weapon-eligibility enforcement, and pending-excusal handling remain authoritative.

The feature is informational. It must not assign ranges, change qualifications, or alter duty assignment decisions.

## User-facing behavior

### Navigation

- Remove the standalone `nav-weapon-ineligible` item for all roles.
- Keep the red warning badge on the existing מטווחים destination.
- Show a red warning-icon badge on תכנון as the aggregate of its child items.
- Aggregate child badge counts on parent navigation items throughout the nav tree. Counts are sums of child counts; the displayed color is the worst child color ordered red > orange > blue > green.
- Do not create a new חוסר כשירות destination.

### Shared hierarchy table

The מטווחים page's כשירות מטווחים tab and the commander dashboard use the same expandable hierarchy table and the same explanation formatter. Columns are sortable, including hierarchy, soldier, qualification, and future context. Rows remain read-only.

The exact core copy is:

- `אין מטווחים בתוקף`
- `טרם שובץ לתורנות שדורשת נשק`
- `משובץ לתורנות <סוג תורנות> שדורשת לפחות מטווח מסוג <סוג מטווח> בתאריך dd.mm.yyyy`

When a planned main range makes the soldier eligible on the duty date, show that range and its projected validity rather than presenting the soldier as currently uncovered. The table explains what must be true by the duty date so planners and commanders can avoid creating an ineligible assignment.

The commander dashboard must use the hierarchy table, not the existing large-card presentation. Scope remains recursively limited to the commander’s authorized subtree; planning scope remains recursively limited to the duty manager’s authorized roots; overlapping roots are deduplicated server-side.

### Calendar badges and details

- UnitCalendar, homepage calendars, and commander calendars show a red warning-icon badge with the number of unique visible soldiers who have at least one weapon-required duty in the displayed calendar scope for which the confirmed eligibility rule is false.
- Opening a shift shows the required range tier prominently in the detail header.
- Each soldier in shift details receives a red warning-icon badge when that soldier is ineligible for that duty on its scheduled date. The badge is informational and uses the shared explanation.
- On desktop, clickable calendar events have a pointer cursor and a clear hover highlight in both light and dark themes.
- The homepage calendar always renders the duty-type filter, even when the current user has no assigned duty.

### Upcoming duties and system setting

- In the commander dashboard’s upcoming-duty soldier interaction, hide שחרור פיקודי when `forced_callup.enabled` is off.
- Show a `צפה בפרטי התורנות` button that opens the existing duty-detail view with the duty’s relevant details.

## Architecture and data flow

Create one backend projection service that accepts a scope and a set of duties or calendar date range, reuses the existing tier and projected-window logic, and returns per-soldier/per-duty eligibility facts. Extend existing calendar, shift-detail, and upcoming-duty responses only where needed to carry these facts; do not duplicate eligibility calculations in frontend components.

Create one frontend explanation/formatting module and one shared hierarchy-table component. The ranges page and commander dashboard provide different scoped query results to the same table. Calendar badges consume aggregated unique-soldier counts; shift details consume per-soldier facts for one duty.

All new user-facing strings belong in `frontend/src/i18n/he.json`. Existing role and system-setting gates remain enforced by the backend as well as the UI.

## Error and empty states

Eligibility failures must not prevent unrelated calendar, dashboard, or shift data from rendering. Badges hide on loading or failed count requests. Tables show existing loading, error, and empty states. A missing eligibility fact must not be interpreted as eligible; the detail view should show a neutral unavailable state if it cannot calculate the warning.

## Testing requirements

- Backend unit tests cover tier inheritance, duty-date validity, future main-range projected windows, reserve/draft exclusion, pending excusal behavior, system toggles, per-duty facts, unique scope counts, and recursive role scope.
- Frontend tests cover removal of the standalone nav item, parent badge aggregation and worst-color selection, sortable shared table behavior, exact Hebrew explanations, dashboard reuse of the table, calendar badge and hover states, always-visible duty filter, forced-callup setting gating, duty-detail navigation, and shift-detail warning badges.
- Run focused suites after each task, then the broader frontend and backend suites before handoff.
