# נוכחות מטווחים: סימון אוטומטי ותיקון בדיעבד — Design Spec

## Goal

היום נוכחות במטווח (`RangeAssignment.attendance_status`) נשארת `pending` לצמיתות עד שאחראי תורנויות מסמן ידנית כל חייל בנפרד — אין שום מנגנון שמסמן אוטומטית מי היה במטווח. המטרה: אחרי שתאריך המטווח עבר, כל מי ששובץ בפועל (לא רזרבה, לא טיוטה) יסומן אוטומטית כ"נכח", כך שאחראי תורנויות רק צריך להתערב בחריגים (מי שבאמת לא הגיע). בנוסף, כל תיקון בדיעבד של נוכחות — לשני הכיוונים — ידרוש נימוק כתוב ויודיע גם לחייל וגם למפקד הישיר שלו.

זהו הספק השני מתוך סדרת הספקים סביב כשירות/מטווחים (אחרי [`2026-08-07-weapon-qualification-eligibility-design.md`](2026-08-07-weapon-qualification-eligibility-design.md)).

## Approved decisions

- **סימון אוטומטי מבוסס-זמן**: עבודת רקע (worker) שרצה כל 5 דקות, באותו דפוס בדיוק כמו `range_reminder_worker.py`, מוצאת מטווחים (`RangeEvent`) שתאריכם עבר (`date < today`) ושאינם מבוטלים, ומסמנת אוטומטית `present` לכל שיבוץ (`RangeAssignment`) שעדיין `pending`, שאינו רזרבה ואינו טיוטה. הפעולה מכבדת את כל תופעות הלוואי הקיימות של סימון נוכחות (הענקת `SoldierRangeQualification`), כי היא קוראת לאותה פונקציית שירות קיימת (`mark_attendance`) ולא כותבת ישירות ל-DB. מוגבלת ב-`mitvachim.enabled`, כמו כל שאר תת-המערכת.
- **אידמפוטנטיות**: הסימון האוטומטי מטפל רק בשיבוצים שעדיין `pending` — ברגע שסומנו (אוטומטית או ידנית) הם לא ייבדקו שוב על ידי ה-worker.
- **דרישת נימוק לתיקון בדיעבד — משני הכיוונים**: כיום נימוק (`note`) נדרש רק כשהסטטוס החדש הוא `no_show`. הכלל מתרחב: נימוק יידרש גם כאשר מדובר בשינוי סטטוס אמיתי על גבי שיבוץ שכבר סומן בעבר (`previous_status != pending`), ללא קשר לכיוון. כלומר: `no_show → present` ידרוש מעתה נימוק בדיוק כמו `present → no_show`. התנאי המלא: `status == no_show OR (previous_status != pending AND status != previous_status)`.
- **הודעות חדשות**:
  - `NotificationType.range_absence_reported_to_commander` — נשלחת אך ורק למפקד הישיר של החייל (`HierarchyNode.commander_id` של הצומת ההיררכי של החייל), בכל מעבר סטטוס לכיוון `no_show` (usar אותו תנאי כמו `no_show_transition` הקיים), בנוסף להודעות הקיימות לחייל (`no_show_marked`) ולאחראי התורנויות בהיקף (`range_no_show`). גוף ההודעה = הנימוק שנכתב.
  - `NotificationType.range_attendance_corrected_to_present` — נשלחת גם לחייל וגם למפקד הישיר שלו, במעבר `no_show → present` (כיום לא נשלחת שום הודעה בתיקון הזה). גוף ההודעה = הנימוק שנכתב.
  - אם לחייל אין `hierarchy_node_id`, או שלצומת שלו אין `commander_id`, הודעת המפקד מדולגת בשקט (ללא שגיאה).
- **`marked_by` הופך אופציונלי**: `mark_attendance`'s `marked_by: uuid.UUID` הופך ל-`uuid.UUID | None = None`, כדי לתמוך בקריאה מה-worker האוטומטי (שאין לו "משתמש" יוזם). העמודה כבר nullable במודל.

## Architecture and data flow

### Worker אוטומטי

קובץ חדש `backend/app/services/range_attendance_auto_mark.py`:

```
auto_mark_present_for_elapsed_events(session: Session, *, today: date | None = None) -> int
```

לוגיקה (במבנה זהה ל-`range_reminders.py::send_due_range_reminders`):
1. אם `mitvachim.enabled` כבוי — מחזיר 0 מיידית.
2. שולף `RangeEvent` עם `date < today` ו-`status != cancelled`.
3. עבור כל `RangeAssignment` בשיבוצים אלו עם `attendance_status == pending`, `is_reserve == False`, `is_draft == False` — קורא ל-`mark_attendance(session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=None, note=None)`.
4. מחזיר את מספר השיבוצים שסומנו.

קובץ חדש `backend/app/range_attendance_worker.py`, מעתיק במדויק את מבנה `range_reminder_worker.py` (polling כל 300 שניות, `session_scope()`, try/except עם לוג אזהרה). מחובר ב-`main.py`'s `lifespan` לצד שלושת ה-workers הקיימים (`email_task`, `swap_expiry_task`, `range_reminder_task`).

### `mark_attendance` — הרחבת דרישת נימוק והודעות

ב-`backend/app/services/ranges.py::mark_attendance` (שורות 467-553):

- שינוי חתימה: `marked_by: uuid.UUID | None = None`.
- שינוי תנאי הנימוק (שורה 480-481) מ-`status == no_show and not note` ל-`(status == no_show or (previous_status != pending and status != previous_status)) and not note`. (התנאי חייב להיבדק אחרי חישוב `previous_status`, כלומר יש להזיז את החישוב `previous_status = assignment.attendance_status` לפני בדיקת הנימוק.) קוד השגיאה הקיים `note_required_for_no_show` מוחלף בקוד כללי יותר `note_required_for_attendance_change`, בשני המקרים (כדי לא לשמור שני קודי שגיאה לאותה משמעות מהותית — "נדרש נימוק"). ה-frontend (`RangeAttendancePanel.tsx`) מתעדכן בהתאם לטפל בקוד החדש בכל מסלול שמציג את השגיאה.
- הוספת קריאת הודעה חדשה לענף `no_show_transition` הקיים (שורה 532-539): קריאה נוספת ל-`_range_notification` עם `type=NotificationType.range_absence_reported_to_commander`, `soldier_id=<direct commander id>` (ולא של החייל עצמו!), `body=note`. אם אין מפקד ישיר — הקריאה מדולגת.
- הוספת ענף חדש לטיפול במעבר `no_show → present` (בנוסף לענף הקיים של הענקת הכשירות בשורה 515-520): כאשר `previous_status == no_show and status == present`, שולח `NotificationType.range_attendance_corrected_to_present` הן לחייל (`assignment.soldier_id`) והן למפקד הישיר, `body=note`.
- פונקציית עזר חדשה `_direct_commander_id(session, soldier_id) -> uuid.UUID | None` שמביאה את `Soldier.hierarchy_node_id → HierarchyNode.commander_id`, ומשמשת את שני הענפים החדשים לעיל.

### הרשאות

אין שינוי בהרשאות — הסימון האוטומטי הוא קריאה פנימית מה-worker (ללא context של משתמש), ותיקון ידני ממשיך להיות מוגן ע"י `range_attendance_edit_authorized` הקיים (`authority.py:70-83`), ללא שינוי.

## Testing requirements

- `backend/app/services/tests/test_range_attendance_auto_mark.py`: מטווח שתאריכו עבר עם שיבוצים `pending` לא-רזרבה לא-טיוטה מסומן `present` אוטומטית ומעניק `SoldierRangeQualification`; רזרבה/טיוטה/שיבוצים שכבר סומנו לא נוגעים בהם; מטווח מבוטל לא מטופל; מטווח עתידי לא מטופל; `mitvachim.enabled=False` מדלג לגמרי; קריאה חוזרת (idempotency) לא יוצרת כשירות כפולה.
- `backend/tests/unit/test_range_attendance.py` (או קובץ דומה קיים — יש לבדוק תחילה): הרחבת בדיקות `mark_attendance` — `no_show → present` בלי נימוק נכשל עם `note_required_for_attendance_change`; `pending → present` עדיין לא דורש נימוק; `no_show → present` עם נימוק שולח הודעה לחייל ולמפקד; `pending/present → no_show` שולח הודעה חדשה למפקד בנוסף להודעות הקיימות; חייל ללא מפקד ישיר לא גורם לשגיאה.
- בדיקת worker: `backend/tests/unit/test_range_attendance_worker.py` (מבנה מקביל ל-`test_range_reminders.py`), מוודאת שהפונקציה נקראת ומטפלת בשגיאות בלי להפיל את ה-worker.
- Suite קיים (backend) נשאר ירוק, כולל `test_range_lifecycle_guards.py` ו-`test_ranges_service.py`.
