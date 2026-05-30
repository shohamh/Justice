# Slice 8 — Soldier Profile Expansion & DutyType Eligibility Requirements

**Date:** 2026-05-30
**Status:** Approved (brainstorm 2026-05-30).
**Depends on:** Slice 7 (master).
**Followed by:** Slice 9 (shifts), Slice 10 (algorithm integration).

## Goal

Extend the `soldiers` table with military-profile fields (gender, rank, officer status, training dates, service dates) and add a JSONB `requirements` field to `duty_types` that gates algorithm candidacy as hard constraints — ineligible soldiers are excluded from that duty type identically to exemptions.

---

## 1. Soldier profile fields (migration 0017)

### 1.1 New columns on `soldiers`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `gender` | `text` | yes | `'male'` \| `'female'` |
| `is_officer` | `boolean` | yes | true = קצין, false = חוגר |
| `rank` | `text` | yes | Value from rank enum (see 1.2) |
| `bahad1_graduate` | `boolean` | default false | Completed בהד"ל 1; academic officers have is_officer=true but bahad1_graduate=false |
| `enlistment_date` | `date` | yes | תאריך גיוס — IDF enlistment (distinct from enrolled_at) |
| `mandatory_end_date` | `date` | yes | תאריך תום שירות חובה |
| `discharge_date` | `date` | yes | תאריך שחרור — null if still serving |
| `last_mitvahim_date` | `date` | yes | Last target practice date |
| `last_alal_date` | `date` | yes | Last אל"ל date |

All columns nullable so existing soldiers remain valid and fully eligible until fields are filled.

### 1.2 Rank enum (validated at app layer, stored as text)

**Enlisted (חוגרים):** `טוראי`, `רבט`, `סמל`, `סמר`, `רסל`, `רסר`, `רסמ`, `רסב`, `רנג`

**Officers (קצינים):** `קמא`, `סגמ`, `סגן`, `קאב`, `סרן`, `רסן`, `סאל`, `אלמ`, `תאל`, `אלוף`, `רב אלוף`

### 1.3 Inferred service type

Not stored — computed at runtime from date fields:

- `mandatory_end_date` is null → unknown
- today ≤ `mandatory_end_date` → **חובה**
- today > `mandatory_end_date` AND (`discharge_date` is null OR `discharge_date` > `mandatory_end_date`) → **קבע**

Used by eligibility checks in the algorithm bridge.

### 1.4 Privacy rules

`gender` is a private field:
- Visible to: the soldier themselves, commanders in their chain of command, duty managers, admins.
- Hidden from: all other soldiers (transparency page, unit calendar, peer views).
- Backend: `GET /api/soldiers/{id}` omits `gender` unless the requester has SOLDIER_READ scope for that soldier's node or is the soldier themselves.

---

## 2. Soldier field editing & approval flow

Soldiers may submit change requests for their own **training dates** (`last_mitvahim_date`, `last_alal_date`) and **gender**. These require commander approval before the field is updated — same pattern as personal constraints.

Fields that are **DM/admin-only** (soldiers cannot request changes): `rank`, `is_officer`, `bahad1_graduate`, `enlistment_date`, `mandatory_end_date`, `discharge_date`.

### 2.1 New table `soldier_field_updates` (migration 0017)

```sql
soldier_field_updates (
  id           uuid PK DEFAULT gen_random_uuid()
  soldier_id   uuid FK soldiers ON DELETE CASCADE
  field_name   text NOT NULL        -- 'last_mitvahim_date' | 'last_alal_date' | 'gender'
  new_value    text NOT NULL        -- serialized as text
  status       text NOT NULL DEFAULT 'pending'  -- 'pending' | 'approved' | 'rejected'
  decided_by   uuid FK soldiers ON DELETE SET NULL, nullable
  decided_at   timestamptz nullable
  decision_note text nullable
  created_at   timestamptz NOT NULL DEFAULT now()
)
```

On approval: the backend applies `new_value` to the soldier's actual field and marks the request approved.

---

## 3. DutyType eligibility requirements (migration 0017)

### 3.1 New column on `duty_types`

```sql
requirements  jsonb NOT NULL DEFAULT '{}'
```

### 3.2 Schema — `DutyTypeRequirements` Pydantic model

```python
class DutyTypeRequirements(BaseModel):
    allowed_genders: list[str] = []         # empty = no restriction; values: 'male', 'female'
    requires_mitvahim: bool = False          # soldier must have last_mitvahim_date within threshold
    requires_alal: bool = False              # soldier must have last_alal_date within threshold
    allowed_ranks: list[str] = []            # empty = no restriction; values from rank enum
    allowed_service_types: list[str] = []    # empty = no restriction; values: 'חובה', 'קבע'
    officers_allowed: bool = True
    enlisted_allowed: bool = True
    requires_bahad1: bool = False
```

All requirements default to "no restriction." An empty `requirements` JSON (`{}`) means no restrictions.

### 3.3 Freshness thresholds in `system_settings`

| Key | Default | Editable by |
|---|---|---|
| `eligibility.mitvahim_months` | `6` | admin |
| `eligibility.alal_months` | `3` | admin |

---

## 4. Algorithm bridge — eligibility enforcement

In `load_soldier_inputs`, after resolving exempted duty type IDs, run an additional pass: for each `(soldier, duty_type)` pair, if the soldier fails any requirement, add `duty_type_id` to `soldier_exempt_dtype_ids`. The algorithm then treats these exactly like exemptions (no variable created for that pair).

### 4.1 Eligibility check logic

For each active duty type with a non-empty `requirements` blob:

1. **Gender**: if `allowed_genders` non-empty and `soldier.gender not in allowed_genders` → blocked. Also blocked if `soldier.gender is null` and restriction exists.
2. **Mitvahim**: if `requires_mitvahim=True` and (`soldier.last_mitvahim_date is null` OR `today - last_mitvahim_date > mitvahim_months`) → blocked.
3. **Alal**: if `requires_alal=True` and (`soldier.last_alal_date is null` OR `today - last_alal_date > alal_months`) → blocked.
4. **Rank**: if `allowed_ranks` non-empty and `soldier.rank not in allowed_ranks` → blocked. Null rank → blocked if restriction exists.
5. **Service type**: if `allowed_service_types` non-empty, compute inferred service type from dates; if not in list or unknown → blocked.
6. **Officer/enlisted**: if `officers_allowed=False` and `soldier.is_officer=True` → blocked. If `enlisted_allowed=False` and `soldier.is_officer` is False or null → blocked.
7. **Bahad1**: if `requires_bahad1=True` and not `soldier.bahad1_graduate` → blocked.

If a soldier's profile field is null and a restriction references it, the soldier is **blocked by default** (fail-safe).

---

## 5. API changes

### 5.1 Soldiers endpoints

- `GET /api/soldiers/{id}` — adds new fields; `gender` omitted unless caller has SOLDIER_READ scope or is the soldier.
- `PATCH /api/soldiers/{id}` (DM/admin) — can update all new fields directly.
- `POST /api/soldiers/{id}/field-updates` (soldier) — submit a change request for `last_mitvahim_date`, `last_alal_date`, or `gender`.
- `GET /api/soldiers/{id}/field-updates` (soldier, commander, DM) — list pending/resolved requests.
- `POST /api/soldiers/{id}/field-updates/{update_id}/approve` (commander, DM) — approve and apply.
- `POST /api/soldiers/{id}/field-updates/{update_id}/reject` (commander, DM) — reject.

### 5.2 Duty config endpoints

- `PATCH /api/duty-config/types/{id}` — add `requirements` field to request/response schema.
- `GET /api/duty-config/types` — include `requirements` in response.

### 5.3 New endpoint

- `GET /api/soldiers/ranks` — returns the rank list split into `enlisted` and `officers` arrays (used by frontend dropdowns).

---

## 6. Frontend

### 6.1 Soldier profile/edit (DM and soldier self)

New section in profile or soldier detail page: "פרטי שירות"

- **DM/admin view**: all fields editable inline. Rank shown as two-group dropdown (חוגרים / קצינים). Service dates as date pickers. Training dates as date pickers. is_officer toggle. bahad1_graduate toggle.
- **Soldier self-view**: rank, service dates, is_officer, bahad1_graduate shown as read-only. Can submit update requests for `last_mitvahim_date`, `last_alal_date`, gender. Pending request shows amber badge.
- **Gender**: visible to self, commanders in chain, DM. Hidden from other soldiers.

### 6.2 ApprovalsPage — new tab "עדכוני פרופיל"

List of pending `soldier_field_updates` for soldiers in the approver's scope. Shows soldier name, field, current value → requested value, approve/reject buttons.

### 6.3 DutyConfigPage — requirements editor

New "דרישות" section per duty type:

- Gender multi-select (זכר / נקבה)
- Rank multi-select (split into two groups in the UI)
- Service type multi-select (חובה / קבע)
- Officer/enlisted toggles
- Mitvahim checkbox
- Alal checkbox
- Bahad1 checkbox

### 6.4 System settings

Admin can edit `eligibility.mitvahim_months` and `eligibility.alal_months` in the settings page.

---

## 7. i18n keys (he.json additions)

```json
"soldier_profile": {
  "gender": "מין",
  "gender_male": "זכר",
  "gender_female": "נקבה",
  "rank": "דרגה",
  "is_officer": "קצין",
  "is_enlisted": "חוגר",
  "bahad1_graduate": "בוגר בהד\"ל 1",
  "enlistment_date": "תאריך גיוס",
  "mandatory_end_date": "תאריך תום שירות חובה",
  "discharge_date": "תאריך שחרור",
  "last_mitvahim_date": "מטווחים אחרון",
  "last_alal_date": "אל\"ל אחרון",
  "service_type_hobah": "חובה",
  "service_type_keva": "קבע",
  "service_type_unknown": "לא ידוע",
  "field_update_pending": "ממתין לאישור",
  "field_update_approved": "אושר",
  "field_update_rejected": "נדחה"
},
"eligibility": {
  "title": "דרישות כשירות",
  "allowed_genders": "מגדר מותר",
  "requires_mitvahim": "נדרש מטווחים עדכני",
  "requires_alal": "נדרש אל\"ל עדכני",
  "allowed_ranks": "דרגות מותרות",
  "allowed_service_types": "סוג שירות מותר",
  "officers_allowed": "קצינים מותרים",
  "enlisted_allowed": "חוגרים מותרים",
  "requires_bahad1": "נדרש בוגר בהד\"ל 1"
}
```

---

## 8. Testing

- **Unit tests** (`test_eligibility.py`): each eligibility check in isolation — null fields blocked, correct fields pass, threshold boundaries.
- **Integration tests** (`test_soldier_profile.py`): PATCH soldier fields, gender visibility enforcement, field update approval flow.
- **Algorithm bridge tests**: soldier with mismatched requirements excluded from duty type; soldier with null profile fields excluded when restriction applies.
