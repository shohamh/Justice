# כשירות תורנות לפי הכשרת נשק — Design Spec

## Goal

היום `eligibility.py` (בדיקת שיבוץ ידני) ו-`get_shift_candidates` (מודל השיבוץ) וגם אלגוריתם ה-CP-SAT האוטומטי לא בודקים כלל האם לחייל יש הכשרת נשק (מטווח) בתוקף עבור תורנות שדורשת נשק (`DutyType.requires_weapon`). המטרה: להוסיף מנוע כשירות משותף שבודק גם הכשרה נוכחית וגם מטווחים עתידיים מתוזמנים (בכפוף לתנאים), להפוך אותו להגדרת מערכת שניתן לכבות/להדליק (דיפולט: דלוק), ולשלב אותו הן בשיבוץ ידני (אזהרה רכה עם אפשרות עקיפה) והן באלגוריתם האוטומטי (אילוץ קשיח, עם אפשרות הרפיה גלובלית או per-run).

זהו הספק הראשון מתוך סדרת ספקים סביב כשירות/מטווחים (הבא בתור: נראות ואזהרות לחיילים לא כשירים שכבר משובצים — ⚠️ badge, notifications, UI החלפה — spec נפרד שיבנה על גבי הליבה כאן).

## Approved decisions

- הבדיקה חלה רק על `DutyType` עם `requires_weapon=True`. סוגי תורנות ללא דרישת נשק אינם מושפעים.
- כל `DutyType` עם `requires_weapon=True` מקבל שדה חדש `required_range_type` (laser/live/alal, לפי `RANGE_TYPE_RANK`) — הרמה המינימלית הנדרשת. במיגרציה, כל שורה קיימת עם `requires_weapon=True` תקבל דיפולט `laser` (הרמה המתירנית ביותר).
- הבדיקה מתבצעת מול **תאריך התורנות עצמה**, לא מול היום הנוכחי — כך תורנות עתידית יכולה להיחשב כשירה בזכות מטווח עתידי שיקדים אותה, ותורנות קרובה יכולה להיחשב לא כשירה אם ההכשרה הנוכחית תפוג לפניה.
- מטווח עתידי (מתוזמן, טרם התקיים) נספר כמעניק כשירות רק אם: החייל משובץ אליו בפועל (`is_reserve=False`), ורמת המטווח (`range_type`) גבוהה או שווה לרמה הנדרשת. תוקף מוקרן = `event.date + validity_days(range_type)` (אותו חישוב כמו ב-`services/ranges.py::_validity_days`, המשמש היום רק למטווחים שהושלמו בפועל).
- שתי הגדרות מערכת חדשות (`system_settings`, לפי הדפוס הקיים של `mitvachim.enabled`):
  - `weapon_qualification.enforce_eligibility` (bool, דיפולט **True**) — מתג ראשי לכל הפיצ'ר. כשכבוי, כל חייל נחשב כשיר לכל תורנות (המנוע עוקף לחלוטין).
  - `weapon_qualification.pending_excusal_disqualifies` (bool, דיפולט **True**) — האם בקשת פטור **ממתינה** (טרם הוכרעה) על שיבוץ למטווח עתידי כבר פוסלת אותו מלהעניק כשירות, לעומת רק בקשת פטור **מאושרת**.
- שיבוץ ידני (מודל השיבוץ / `get_shift_candidates`): חוסר כשירות הוא **אזהרה רכה עם אפשרות עקיפה** — בשונה מסיבות חסימה קיימות (`constraint`/`assignment`, שהן checkbox מנוטרל לגמרי), מועמד לא כשיר יסומן עם `blocked_reason: "weapon_qualification"` אך ה-checkbox יישאר פעיל ואחראי התורנויות יוכל לשבץ בכל זאת (עם אישור/confirm). מיון: אחרי מועמדים כשירים, כמו סיבות חסימה אחרות.
- אלגוריתם CP-SAT: **אילוץ קשיח** כברירת מחדל (לעולם לא ישבץ חייל לא כשיר לתורנות שדורשת נשק) — אין מי שיאשר "עקיפה" בזמן ריצה אוטומטית. ניתן להרפות בשתי רמות: (1) הגדרת המערכת הראשית לעיל מכבה את הבדיקה גלובלית; (2) הגדרת run חדשה באלגוריתם, `enforce_weapon_qualification`, המאפשרת להריץ ריצה בודדת בלי האילוץ מבלי לשנות את ברירת המחדל הגלובלית — באותו דפוס כמו `SolverSettings.auto_relax_node_quotas`.

## Architecture and data flow

### מודל נתונים

הוספת עמודה `DutyType.required_range_type: RangeType | None` (nullable enum). לא נדרשות טבלאות חדשות — משתמשים ב-`SoldierRangeQualification`, `RangeAssignment`, `RangeExcusalRequest` הקיימים.

### ליבת כשירות משותפת

מודול חדש `backend/app/services/weapon_eligibility.py`:

```
compute_eligibility(session, soldier_id, required_range_type, as_of_date) -> (eligible: bool, reason: str | None)
```

לוגיקה:
1. אם `weapon_qualification.enforce_eligibility` כבוי → `eligible=True` תמיד.
2. אחרת, כשיר אם קיימת `SoldierRangeQualification` שמכסה את `as_of_date` ברמה >= הנדרשת, **או** קיים שיבוץ עתידי כשיר כמתואר לעיל (לא רזרבה, לא פסול לפי `pending_excusal_disqualifies`, רמה מתאימה, ותוקף מוקרן מכסה את `as_of_date`).

פונקציה זו היא מקור האמת היחיד — משמשת גם את הנתיב הידני וגם את גשר האלגוריתם, כדי למנוע כפל לוגיקת תאריכים.

### שיבוץ ידני

`backend/app/routes/shifts.py::get_shift_candidates` — לכל מועמד לתורנות עם `required_range_type` מוגדר, קורא ל-`compute_eligibility` מול תאריך התורנות. תוצאה שלילית מוסיפה `blocked_reason="weapon_qualification"` אך **לא** מסירה את המועמד מרשימת השיבוץ האפשרי (בשונה מ-`constraint`/`assignment`). `ShiftAssignModal.tsx` מציג אינדיקציית אזהרה, checkbox פעיל, ומבקש אישור לפני שיבוץ מועמד לא כשיר.

### אלגוריתם CP-SAT

- `SolverSettings` (ב-`algorithm/types.py`) מקבל שדה חדש `enforce_weapon_qualification: bool = True`.
- `services/algorithm_bridge.py` (בעל גישת DB) מחשב מראש, לכל צירוף חייל × תאריך תורנות × רמה נדרשת, `eligible: bool` דרך `compute_eligibility`, ומעביר טבלת חיפוש פשוטה (dict/lookup) לפותר. הפותר עצמו (`solver.py`) נשאר "טיפש" וללא ידע על תאריכים/מטווחים — רק קורא בטבלה.
- כאשר `enforce_weapon_qualification=True` (בין אם דרך ברירת המחדל הגלובלית, ובין אם run הועבר עם `True` ישירות), הפותר מוסיף אילוץ קשיח: חייל לא כשיר לא יכול להיות משובץ לתורנות עם `required_range_type`.
- הגדרת ה-run מוצגת ב-UI הגדרות ריצת האלגוריתם (כמו הגדרות relax קיימות), וברירת המחדל שלה נלקחת מ-`weapon_qualification.enforce_eligibility`.

### ממשק לספק הבא (נראות אי-כשירות)

ספק זה עוצר בזיהוי/מניעת שיבוצים **חדשים** בלבד. הוא אינו מטפל בשיבוץ קיים שהופך ללא-כשיר בדיעבד (למשל אישור פטור ממטווח לאחר שהחייל כבר שובץ לתורנות) — זיהוי, badge אדום, הודעות, ו-UI החלפה הם ספק נפרד שיבנה מעל אותה `compute_eligibility`.

## Testing requirements

- מיגרציה: `DutyType.required_range_type` נוצר ומתמלא נכון (`laser` לכל שורת `requires_weapon=True` קיימת, `NULL` אחרת).
- בדיקות יחידה ל-`compute_eligibility`: הכשרה נוכחית בתוקף/פגה, מטווח עתידי כשיר/רזרבה/עם פטור ממתין/מאושר, רמת מטווח נמוכה מהנדרש, תאריך בדיקה לפני/אחרי אירוע, הגדרת מערכת כבויה.
- בדיקות API ל-`get_shift_candidates`: מועמד לא כשיר מופיע עם `blocked_reason="weapon_qualification"` ואינו מוסר; שיבוץ ידני של מועמד כזה מצליח (אין hard block בשרת).
- בדיקות אלגוריתם: ריצה עם `enforce_weapon_qualification=True` (דיפולט) לא משבצת חייל לא כשיר; ריצה עם `False` (per-run) יכולה לשבץ אותו; ריצה עם הגדרת המערכת כבויה זהה להתנהגות `False`.
- בדיקות frontend: `ShiftAssignModal` מציג אזהרה + checkbox פעיל למועמד לא כשיר, ומבקש אישור לפני שיבוץ.
- Suite קיים (backend + frontend) נשאר ירוק.
