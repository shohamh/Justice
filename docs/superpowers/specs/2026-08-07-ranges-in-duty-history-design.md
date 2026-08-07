# מטווחים בהיסטוריית תורנויות — Design Spec

## Goal

היום `get_duty_history` (`backend/app/services/duty_history.py`) בונה את ציר הזמן בפרופיל החייל מ-`DutyAssignment`, `DutyDayOverride`, `DutyDismissal`, פטורים ואילוצים בלבד — מטווחים נעדרים לגמרי. המטרה: כל מטווח שחייל היה קשור אליו יופיע בהיסטוריית התורנויות שלו — בין אם היה בו בפועל, שובץ אליו ובסוף לא היה (הוסר/פוטר), או שובץ כרזרבה (בין אם קודם בפועל למקום מלא ובין אם לא).

זהו הספק השלישי מתוך סדרת הספקים סביב כשירות/מטווחים (אחרי [`2026-08-07-weapon-qualification-eligibility-design.md`](2026-08-07-weapon-qualification-eligibility-design.md) ו-[`2026-08-07-range-attendance-auto-mark-and-corrections-design.md`](2026-08-07-range-attendance-auto-mark-and-corrections-design.md)).

## Approved decisions

- **פער קיים בנתונים**: `RangeExcusalRequest.range_assignment_id` הופך `NULL` (`ondelete="SET NULL"`) ברגע שה-`RangeAssignment` שהוא מצביע עליו נמחק (למשל אישור פטור ראשי) — כלומר לאחר המחיקה, בקשת הפטור מאבדת כל זיהוי של המטווח (תאריך, סוג, מיקום). כדי שהיסטוריה תוכל להציג "שובץ למטווח X ובסוף הוסר", מוסיפים עמודה חדשה `RangeExcusalRequest.range_event_id: uuid.UUID | None`, שנקבעת פעם אחת ביצירת הבקשה (ב-`request_primary_excusal`/`request_reserve_excusal`) ולעולם לא מתאפסת. שורות היסטוריות שכבר איבדו את הקישור (המטווח שלהן כבר נמחק לפני השינוי הזה) יישארו חסרות — לא ניתן לשחזר מידע שכבר אבד.
- **הסרה ידנית (ללא זרימת פטור) מקבלת נימוק ותיעוד**: `remove_range_assignment` (`backend/app/services/ranges.py:393-407`) היום מוחקת שורת `RangeAssignment` לצמיתות בלי שום נימוק או רישום ביקורת. משתנה לדרוש `reason: str` (חובה), וכותבת שורת `AuditLog` (`action="range_assignment.remove"`, `before` עם פרטי השיבוץ שנמחק, `context={"reason": ..., "range_event_id": ..., "range_type": ...}`) *לפני* המחיקה — כך שגם הסרה ידנית ישירה נשמרת בהיסטוריה, לא רק הסרה דרך זרימת פטור.
- **שני מקורות היסטוריה מתאחדים לאירוע אחיד**: הן `RangeExcusalRequest` (מאושר, עם `range_event_id`) והן שורות `AuditLog` חדשות (מהסרה ידנית) הופכות לאותו סוג אירוע ("הוסר ממטווח") בציר הזמן, עם אותה צורת metadata (סוג מטווח, מיקום, תאריך, נימוק, מי הסיר/אישר, מתי).
- **אירוע שיבוץ נוכחי**: לכל `RangeAssignment` קיים של החייל (עדיין לא נמחק) — כולל רזרבה שלא הופעלה — מופיע אירוע בהיסטוריה, עם `attendance_status` נוכחי וסימון האם קודם מרזרבה למקום ראשי (`RangeExcusalRequest.promoted_assignment_id == assignment.id`).
- **סינון וסגנון בפרונט**: `FilterType` ב-`DutyHistoryPanel.tsx` מקבל ערך חדש `"range"`; טיפוסי האירועים החדשים (`range_assignment`, `range_removed`) מקבלים צבעים/סגנון ייחודיים באותו דפוס כמו הסוגים הקיימים.

## Architecture and data flow

### מיגרציה ומודל

- `RangeExcusalRequest.range_event_id: uuid.UUID | None` (nullable FK ל-`range_events.id`, `ondelete="SET NULL"` — כדי שלא תיחסם מחיקת מטווח ישן).
- `request_primary_excusal`/`request_reserve_excusal` (`backend/app/services/range_excusal.py`) מוסיפות `range_event_id=assignment.range_event_id` בבניית ה-`RangeExcusalRequest`.
- `remove_range_assignment` מקבלת `reason: str` (פרמטר חובה חדש), וכותבת `write_audit(session, actor_id=actor_id, action="range_assignment.remove", entity_type="range_assignment", entity_id=assignment.id, before={"soldier_id": str(assignment.soldier_id), "range_event_id": str(assignment.range_event_id), "is_reserve": assignment.is_reserve}, context={"reason": reason})` לפני `session.delete(assignment)`.
- ה-route (`DELETE /ranges/{event_id}/assignments/{assignment_id}`) מקבל `reason` דרך גוף בקשה (Pydantic body model, כמו ב-`MarkAttendanceBody`) — FastAPI תומך ב-body על DELETE. ה-frontend (`RangeEditAssignmentsModal.tsx`'s `remove()`) מבקש נימוק (prompt) לפני הקריאה; `RangesPage.tsx`'s `bulkClear()` מבקש נימוק משותף אחד לכל הפעולה המרוכזת.

### `get_duty_history` — שני מקורות חדשים

ב-`backend/app/services/duty_history.py::get_duty_history`, בנוסף לאוספים הקיימים:

**1. `range_assignment` — שיבוצי מטווח נוכחיים:**
- שולף את כל `RangeAssignment` של החייל (join ל-`RangeEvent` לתאריך/סוג/מיקום).
- לכל שיבוץ, בודק אם קיימת `RangeExcusalRequest` עם `promoted_assignment_id == assignment.id` (מציין קידום מרזרבה).
- `TimelineEvent`: `date=event.date`, `title="מטווח {range_type} ב{location}"`, `status=attendance_status`, `metadata={range_type, location_name, is_reserve, was_promoted_from_reserve, note, range_event_id}`.

**2. `range_removed` — הסרות (משני המקורות, מאוחדות):**
- מקור א': `RangeExcusalRequest` עם `requested_by == soldier_id`, `status == approved`, `range_assignment_id IS NULL` (כלומר השיבוץ כבר נמחק), `range_event_id IS NOT NULL`.
- מקור ב': `AuditLog` עם `action == "range_assignment.remove"` ו-`before["soldier_id"] == str(soldier_id)`.
- שני המקורות ממופים לאותה צורת `TimelineEvent`: `date` = תאריך המטווח (משליפת ה-`RangeEvent` דרך `range_event_id`), `title="הוסר ממטווח {range_type} ב{location}"`, `description` = הנימוק (`reason`/`decision_note`), `metadata={range_type, location_name, removed_by_name, source: "excusal" | "manual_removal"}`.

### פרונט — `DutyHistoryPanel.tsx`

- `FilterType` מקבל `"range"`.
- `FILTER_KEYS` מקבל `{ type: "range", i18nKey: "duty_history.filter_ranges" }`.
- `TYPE_COLORS`/`DOT_COLORS` מקבלים ערכים ל-`range_assignment` (למשל גוון ציאן) ול-`range_removed` (גוון אפור/מקווקו, כדי להבדיל חזותית מהצלחה).
- רינדור `range_assignment`: badge לפי `attendance_status` (✓ נכח / ✗ לא נכח עם ה-note / ⏳ רזרבה לא הופעלה), ותג נוסף "קודם מרזרבה" כש-`was_promoted_from_reserve`.
- רינדור `range_removed`: מציג את פרטי המטווח שממנו הוסר + הנימוק.

## Testing requirements

- מיגרציה: `RangeExcusalRequest.range_event_id` נוצר, `NULL` דיפולטית לשורות קיימות.
- `backend/app/services/tests/test_range_excusal.py` (או קובץ מקביל): `request_primary_excusal`/`request_reserve_excusal` שומרות `range_event_id`; לאחר אישור ומחיקת השיבוץ, `range_event_id` עדיין נגיש (`range_assignment_id` הוא `NULL` אך `range_event_id` לא).
- `backend/app/services/tests/test_ranges_service.py`: `remove_range_assignment` בלי `reason` נכשל; עם `reason` כותב `AuditLog` עם הפרטים הנכונים ומוחק את השיבוץ.
- `backend/app/services/tests/test_duty_history.py` (או שם מקביל קיים): שיבוץ נוכחי מופיע כ-`range_assignment` עם הסטטוס הנכון; רזרבה שלא הופעלה מופיעה; רזרבה שקודמה מופיעה עם `was_promoted_from_reserve=True`; הסרה דרך פטור מופיעה כ-`range_removed` עם פרטי המטווח; הסרה ידנית (עם reason) מופיעה כ-`range_removed` דרך ה-audit log; מטווח שהוסר *לפני* השינוי הזה (ללא `range_event_id`) לא גורם לשגיאה — פשוט מדולג או מוצג חלקי.
- Frontend: `DutyHistoryPanel.test.tsx` (אם קיים, אחרת קובץ חדש) — פילטר `"range"` מסנן נכון; באדג'ים מוצגים לפי `attendance_status`/`was_promoted_from_reserve`; אירוע `range_removed` מוצג בסגנון נפרד.
- Suite קיים (backend + frontend) נשאר ירוק.
