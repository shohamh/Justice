# Private Fields Access Control

**Date:** 2026-06-23  
**Status:** Approved

## Problem

Several personal fields in the system are sensitive — gender, contact details, constraint reasons, and exemption reasons/types — but are currently exposed without consistent access control. Admins and plain soldiers who are not in the relevant chain of command can read them.

## Access Rule

The following fields are **private** and visible only to:
1. The soldier themselves
2. Their duty manager (whose DM scope includes the soldier's node)
3. Commanders in the soldier's chain of command

Admins and plain soldiers outside these relationships **cannot** see private fields.

### Private fields by entity

| Entity | Private fields |
|--------|---------------|
| `Soldier` | `gender`, `phone`, `email` |
| `PersonalConstraint` | `reason` |
| `SoldierExemption` | `reason`, `exemption_type_id` |
| `ExemptionRequest` | `reason`, `exemption_type_id` |
| `SoldierFieldUpdate` | `new_value`, `previous_value` (when `field_name` is a private Soldier field) |

## Design

### Authorization layer (`backend/app/auth/authz.py`)

Add two exports:

```python
PRIVATE_FIELD_NAMES: frozenset[str] = frozenset({"gender", "phone", "email"})

def can_see_private(session: Session, viewer: Soldier, target: Soldier) -> bool:
    if viewer.id == target.id:
        return True
    if viewer.role == "admin":
        return False
    if viewer.role in ("duty_manager", "commander"):
        roots = scope_root_ids(session, viewer)
        node = session.get(HierarchyNode, target.hierarchy_node_id) if target.hierarchy_node_id else None
        return _node_in_scope(node, roots)
    return False
```

The existing `_can_see_private_fields()` helper in `soldiers.py` is deleted; all callers import from `authz`.

### Backend route changes

Each route file adds `include_sensitive: bool` (or `include_private` / `include_reason`) to its `_out()` helper. When `False`, private fields are set to `None` in the response. The flag is computed at the call site via `can_see_private`.

**`soldiers.py`**
- Delete `_can_see_private_fields`, import `can_see_private` + `PRIVATE_FIELD_NAMES` from `authz`
- `list_soldiers`: admin now gets `include_private=False` (previously `True`)
- `get_soldier`, `update_profile`: swap helper call
- `onboard`: actor is the creating DM/commander — keep `include_private=True`
- `_fu_out(include_values: bool)`: when `False` and `field_name in PRIVATE_FIELD_NAMES`, set `new_value=None`, `previous_value=None`
- `FieldUpdateOut.new_value` and `.previous_value` become `str | None`
- `list_all_pending_field_updates`: per-row `include_values = field_name not in PRIVATE_FIELD_NAMES or can_see_private(session, user, target_soldier)`

**`constraints.py`**
- `ConstraintOut.reason` → `str | None`
- `_out(include_reason: bool = True)`: when `False`, `reason=None`
- `list_for_soldier`: `include_reason=can_see_private(session, user, s)`
- `_attach_names(session, rows, user)`: add `user: Soldier` param; compute `include_reason=can_see_private(session, user, soldier)` per row in the loop (admin always returns False)
- `approve` / `reject` responses: caller is authorized — `include_reason=True`

**`exemptions.py`**
- `ExemptionOut.reason` → `str | None`, `.exemption_type_id` → `uuid.UUID | None`
- `_out(include_sensitive: bool = True)`: when `False`, both fields → `None`
- `list_`: `include_sensitive=can_see_private(session, user, s)`
- `grant` / `revoke`: actor is authorized — `include_sensitive=True`

**`exemption_requests.py`**
- `ExemptionRequestOut.reason` → `str | None`, `.exemption_type_id` → `uuid.UUID | None`
- `_out(include_sensitive: bool = True)`: when `False`, both → `None`
- `/me/exemption-requests`: self → `include_sensitive=True`
- `/exemption-requests/pending`: scope-gated (admin already gets `[]`); add safety net: if `user.role == "admin"` → `include_sensitive=False`
- `approve` / `reject`: caller is authorized — `include_sensitive=True`

### Frontend changes

**TypeScript type updates**
- `api/constraints.ts`: `PersonalConstraint.reason` → `string | null`
- `api/exemptions.ts`: `ExemptionRequest.reason`, `.exemption_type_id` → `string | null`; `SoldierExemption.reason`, `.exemption_type_id` → `string | null`
- `api/soldiers.ts`: `FieldUpdateDTO.new_value`, `.previous_value` → `string | null`

**Component display rules**

When a private field is `null` and the context implies the field exists (i.e. we're viewing someone else's record), display **"מידע פרטי"** inline.

| Component | Field | Display |
|-----------|-------|---------|
| `ApprovalsPage.tsx` | constraint `reason` | `reason ?? "מידע פרטי"` |
| `ApprovalsPage.tsx` | exemption request `reason` | `reason ?? "מידע פרטי"` |
| `ApprovalsPage.tsx` | exemption request `exemption_type_id` | type name lookup or `"מידע פרטי"` |
| `ApprovalsPage.tsx` | field update `new_value` / `previous_value` | `value ?? "מידע פרטי"` |
| `ExemptionsPanel.tsx` | `SoldierExemption.reason` | `reason ?? "מידע פרטי"` |
| `ExemptionsPanel.tsx` | `SoldierExemption.exemption_type_id` | type name lookup or `"מידע פרטי"` |
| `UnifiedSoldierModal.tsx` | constraint `reason` | `reason ?? "מידע פרטי"` |

## What is NOT changing

- `ExemptionType` listing endpoint — lists available types in the system, not per-soldier, not private
- `DutyDismissal.reason` — administrative field, not personal
- `ScoreAdjustment.reason` — administrative field, not personal
- `SwapRequest.reason` — visible to swap participants, not personal in the same sense
- Scoring, assignment, algorithm data — not personal

## Testing notes

- Unit tests: `can_see_private` covers all four roles × self/in-scope/out-of-scope
- Integration: each endpoint asserted for admin (expect null fields), DM in scope (expect real values), plain soldier viewing other (expect null fields)
- Frontend: snapshot or render tests for the "מידע פרטי" fallback in each component
