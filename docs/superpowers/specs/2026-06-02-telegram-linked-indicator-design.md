# Telegram Linked Indicator — Design Spec

**Date:** 2026-06-02

## Overview

Expose a public `telegram_linked` boolean on every soldier response, and display a Telegram logo + checkbox indicator in the soldiers table and hierarchy tree so commanders can see at a glance who has linked their Telegram account.

The Telegram username and chat ID remain private — only the verified/not-verified boolean is surfaced.

---

## Backend

### `SoldierOut` — new field

```python
telegram_linked: bool = False
```

### `_out()` helper

Accepts an optional `telegram_linked: bool` parameter (default `False`). All callers that only have a single soldier pass `False` unless they separately look up the telegram link. List endpoints compute linked status in bulk.

### Bulk lookup pattern (no N+1)

In `list_soldiers` (and any other endpoint that returns a list), run one extra query upfront:

```python
linked_ids: set[uuid.UUID] = {
    row for (row,) in session.execute(
        select(TelegramLink.soldier_id).where(TelegramLink.is_verified == True)
    ).all()
}
```

Then pass `telegram_linked=s.id in linked_ids` to each `_out()` call.

### Single-soldier endpoints (`GET /soldiers/{id}`, `PATCH`, etc.)

Run a single lookup:

```python
link = session.execute(
    select(TelegramLink).where(
        TelegramLink.soldier_id == soldier.id,
        TelegramLink.is_verified == True,
    )
).scalar_one_or_none()
telegram_linked = link is not None
```

---

## Frontend

### `SoldierDTO`

Add `telegram_linked: boolean` to the interface.

### Telegram indicator component

A small inline component used in both locations:

```tsx
// shows Telegram paper-plane logo (SVG) + a read-only checkbox
<TelegramBadge linked={s.telegram_linked} />
```

- **Linked:** blue Telegram logo + checked checkbox
- **Not linked:** grey Telegram logo + unchecked checkbox

Use the official Telegram colour `#229ED9` for the linked state.

### Soldiers table (`TeamHierarchyPage`)

New `ColDef` column after "role":

| Header | טלגרם |
|---|---|
| Cell | `<TelegramBadge linked={s.telegram_linked} />` |
| Sort | `telegram_linked ? 0 : 1` (linked first) |

### Hierarchy tree (`HierarchyTree`)

Next to each soldier's name row, after the personal number span, add `<TelegramBadge linked={s.telegram_linked} />`.

---

## Scope

- No new API endpoints — `telegram_linked` rides on existing `/soldiers` and `/soldiers/{id}`.
- Telegram username, chat ID, and verification code are never included in `SoldierOut`.
- The indicator is read-only; clicking it does nothing.
- No migration needed — `telegram_links` table already exists.
