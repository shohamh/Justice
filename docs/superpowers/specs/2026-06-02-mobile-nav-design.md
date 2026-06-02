# Mobile Navigation & Responsive Layout

**Date:** 2026-06-02  
**Status:** Approved

## Goal

Make the app fully usable on phones (320–430px) and tablets (~768px), with a unified navigation experience across all screen sizes. Replace the fixed-width text sidebar with a compact icon+label nav that renders as a bottom bar on mobile and a narrow vertical sidebar on desktop.

## Tab Structure

### Soldier (no elevated role)

| Tab | Icon (lucide-react) | Route |
|-----|---------------------|-------|
| בית | `House` | `/` |
| תורנויות | `Shield` | `/my-duties` |
| בקשות | `FileText` | `/my-requests` |
| החלפות | `ArrowLeftRight` | `/swaps` |
| פרופיל | `CircleUser` | `/profile` |

### Manager / Commander / Admin

| Tab | Icon (lucide-react) | Route |
|-----|---------------------|-------|
| בית | `House` | `/` |
| תורנויות | `Shield` | `/my-duties` |
| אישורים | `ClipboardCheck` + red badge | `/approvals` |
| ניהול | `LayoutGrid` | opens ManageSheet |
| פרופיל | `CircleUser` | `/profile` |

Role detection mirrors existing Layout logic:
- `canManageTeam`: `duty_manager`, `admin`, `commander`
- `canManageDuties`: `duty_manager`, `admin`
- `canApprove`: `duty_manager`, `admin`, `commander`

Roles where `canApprove` is true use the manager tab set. All other roles use the soldier tab set.

## ManageSheet Contents

Grouped links, shown only if role has access:

**אישי (Personal)** — all roles  
My Requests, Swaps, Transparency

**צוות (Team)** — canManageTeam  
Team Hierarchy, Unit Calendar, Command Dashboard

**תכנון (Planning)** — canManageDuties  
Duty Config, Duty Management, Shifts, Shift Templates

## Layout Behavior

### Mobile (< md, below 768px)

- `UnifiedNav` renders as `fixed bottom-0 left-0 right-0`, 56px tall, white background, top border
- `safe-area-inset-bottom` padding for notched iPhones
- Main content: `pb-16` to avoid overlap with the nav bar
- Active tab: `text-indigo-600`; inactive: `text-gray-400`
- Min tap target: 44px per tab
- Icon: 20px; label: 11px below icon

### Desktop (≥ md, 768px+)

- `UnifiedNav` renders as `fixed right-0 top-0 bottom-0`, ~96px wide, white background, left border
- Icons (20px) above short labels, stacked vertically, centered
- Active tab: `text-indigo-600` with light indigo background pill
- Main content: `mr-24` right margin to avoid overlap
- Header adjusts: `mr-24`

### ManageSheet

- Slides up from bottom on mobile; slides in from right edge on desktop
- Semi-transparent backdrop closes it on tap/click outside
- Grouped link list with section headers
- Navigating to a link closes the sheet

## Components

### `UnifiedNav.tsx` (new)

- Reads `useLocation()` to determine active route
- Reads `useAuth()` for role
- Reads `useTranslation()` for labels
- Derives `tabs` array based on role
- Manages `manageSheetOpen: boolean` state
- Renders bottom bar on mobile, vertical sidebar on desktop via Tailwind breakpoint classes

### `ManageSheet.tsx` (new)

- Props: `open: boolean`, `onClose: () => void`
- Grouped link list derived from role
- Uses `useNavigate()` to navigate and call `onClose`

### `Layout.tsx` (modified)

- Remove `<aside>` sidebar entirely
- Mount `<UnifiedNav />` 
- Change `<div className="flex-1 flex flex-col">` to account for desktop right margin: add `md:mr-24`
- Change `<main>` to add `pb-16 md:pb-0`
- Header `<div>` gets `md:mr-0` (header is inside the flex-1 div, so margin is inherited)

## Dependencies

Add `lucide-react` to `frontend/package.json`. It is tree-shakeable so only imported icons are bundled.

## Notifications Badge

The pending count badge on Approvals tab mirrors current sidebar badge: red circle with count, shown when `pendingCount > 0`. The `getPendingCount` / `getPendingExemptionCount` / `getPendingFieldUpdateCount` fetch logic moves from `Layout.tsx` into `UnifiedNav.tsx`.

## Out of Scope

- Per-page layout fixes (table horizontal scroll, modal sizing) — tracked separately
- RTL icon mirroring for directional icons (ArrowLeftRight is symmetric)
- Notification bell remains in the header on both mobile and desktop
