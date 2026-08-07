# נראות חיילים לא כשירים לתורנות — Design Spec

## Goal

ספק #4 ([`2026-08-07-weapon-qualification-eligibility-design.md`](2026-08-07-weapon-qualification-eligibility-design.md)) מונע שיבוצים *חדשים* של חיילים לא כשירים, אך אינו מטפל בשיבוץ *קיים* שהופך ללא-כשיר בדיעבד (למשל: שובץ למטווח, ואז שובץ לתורנות הדורשת אותו מטווח, ואז ביקש/אושר לו לצאת מהמטווח). המטרה: לזהות מצב כזה, להציג אותו בבירור לכל מפקד ואחראי תורנויות (badge אדום + ⚠️ עם כמות), להודיע לחייל, למפקד הישיר שלו ולאחראי התורנויות בהיקף — ולתת לשני הצדדים דרך מסודרת לפתור את זה.

זהו הספק הרביעי (והאחרון בסדרה הנוכחית) סביב כשירות/מטווחים, ונשען ישירות על `compute_eligibility` מספק #4.

## Approved decisions

### מנגנון זיהוי — היברידי: מונע-אירועים + רשת ביטחון יומית

- **מונע-אירועים (העיקרי)**: מיד לאחר פעולות שיכולות לשנות כשירות — תיקון נוכחות (`mark_attendance`, ספק #1), הכרעת/יצירת בקשת פטור ממטווח (`decide_primary_excusal`, `request_reserve_excusal`), שינוי הגדרת המערכת `weapon_qualification.enforce_eligibility`, שינוי `DutyType.required_range_type` — מופעלת בדיקה ממוקדת לשיבוצים הרלוונטיים בלבד. זיהוי כמעט מיידי, בלי המתנה ל-polling.
- **רשת ביטחון (משנית)**: worker חדש שרץ אחת ליום (בניגוד ל-workers האחרים שרצים כל 5 דקות — כאן אין צורך בתדירות גבוהה כי המטרה רק ללכוד "דעיכת זמן טהורה", כלומר הכשרה שפג תוקפה בלי שום פעולה מפעילה), עובר על *כל* השיבוצים הפרסומים (`published`) של תורנויות הדורשות נשק ובודק את כולם.
- שני המסלולים כותבים לאותו state cache (ראה למטה) ומפעילים את אותה לוגיקת מעברי סטטוס/הודעות.

### מטמון על `DutyAssignment`

- `weapon_ineligible: bool` (דיפולט `False`).
- `weapon_ineligible_reason: str | None` — טקסט עברי קריא (למשל: "אין הכשרת נשק בתוקף לתאריך התורנות").
- `weapon_ineligible_detected_at: datetime | None`.

המטמון משרת שתי מטרות: (1) שאילתת ה-badge היא `COUNT` מהיר על עמודה מאונדקסת ולא חישוב מחדש בכל טעינת עמוד, (2) זיהוי מעבר סטטוס (False→True) לצורך שליחת הודעה פעם אחת בלבד.

### מעברי סטטוס

- **False → True** (הפך ללא כשיר): מעדכן את המטמון, שולח הודעות (ראו למטה).
- **True → False** (חזר להיות כשיר, למשל שובץ למטווח חדש): מעדכן את המטמון בשקט, **בלי** הודעה (חדשות טובות, אין צורך להודיע — אותו היגיון כמו בספק #1).

### הודעות

בכל מעבר False→True: הודעה לחייל, למפקד הישיר שלו (`commander_chain_for_soldier(...)[0]`, כמו בספק #1), ולאחראי התורנויות בהיקף (`notify_duty_managers_in_scope`), עם הנימוק הקריא.

### נראות — ארבעה מיקומים

1. **Badge מצטבר בסרגל הניווט**: badge אדום חדש (שונה מה-badge הכחול של אישורי מפקד), לפי הדפוס הקיים ב-`UnifiedNav.tsx` (`pendingCount`/`BADGE_COLOR_CLASSES`), מוצג לאחראי תורנויות ולמפקדים, מסונן לפי היקף היררכי.
2. **אינדיקטור לכל שורת תורנות ב-`ShiftsPage.tsx`**: ⚠️ ליד `fill_status` הקיים.
3. **אינדיקטור לכל שורת שיבוץ ב-`DutyManagementPage.tsx`**: ⚠️ ליד שורת השיבוץ של אותו חייל.
4. **אינדיקטור בתוך modal הצפייה בתורנות/רשימת המשובצים**: ⚠️ ליד שם החייל הספציפי הלא כשיר.

### פתרון — שני מסלולים נפרדים

- **לחייל**: כפתור/הודעה "אינך כשיר לתורנות זו — בקש החלפה" בתצוגת השיבוץ שלו, המוביל **לזרימת בקשת ההחלפה הקיימת** (`swaps.py`, `OfferSwapModal`-style) ממולאת מראש לשיבוץ הזה. אין בניית מנגנון חדש — הזרימה הקיימת כבר בודקת כשירות של המחליף.
- **לאחראי תורנויות**: כפתור "החלף" ליד ה-⚠️ מבטל (`cancel`) את השיבוץ הלא-כשיר ופותח את `ShiftAssignModal` (כבר מודע לכשירות נשק מספק #4) ממוקד לחריץ שהתפנה באותה תורנות — משתמש ברשימת המועמדים הכשירים הממוינת לפי עומס הקיימת שם ללא שינוי.

## Architecture and data flow

### מיגרציה ומודל

- שלוש עמודות חדשות על `DutyAssignment`: `weapon_ineligible` (Boolean, דיפולט `false`), `weapon_ineligible_reason` (Text, nullable), `weapon_ineligible_detected_at` (DateTime with tz, nullable). אינדקס חלקי (`WHERE weapon_ineligible = true`) לשאילתת ה-badge המהירה.

### ליבת בדיקה משותפת

מודול חדש `backend/app/services/duty_eligibility_watch.py`:

```
recheck_assignments(session: Session, assignment_ids: Sequence[uuid.UUID]) -> int
```

לכל `DutyAssignment` (מסונן ל-`status == "published"`, `duty_type.required_range_type is not None`): קורא ל-`compute_eligibility` (ספק #4) מול `as_of=assignment.start_date`. משווה לערך המטמון הקודם; במעבר False→True מעדכן ושולח הודעות; במעבר True→False מעדכן בשקט; ללא שינוי — לא נוגע. מחזיר את מספר השיבוצים שעברו למצב לא-כשיר.

### הפעלה מונעת-אירועים

נקודות שילוב (כל אחת קוראת ל-`recheck_assignments` עם רשימת `DutyAssignment` רלוונטית לחייל שהשתנה):
- `mark_attendance` (`ranges.py`, ספק #1) — לאחר תיקון נוכחות.
- `decide_primary_excusal`, `request_reserve_excusal` (`range_excusal.py`) — לאחר הכרעת/יצירת בקשת פטור.
- `set_setting`/`apply_settings` (`settings_loader.py`) — כאשר `weapon_qualification.enforce_eligibility` משתנה, מפעיל בדיקה גורפת (כל השיבוצים הרלוונטיים, לא רק לחייל ספציפי) — ריצה ברקע כדי לא לחסום את קריאת ה-API של עדכון ההגדרה.
- `update_duty_type` (`duty_config.py`) — כאשר `required_range_type` משתנה, מפעיל בדיקה לכל השיבוצים הפרסומים של אותו `duty_type_id`.

### Worker רשת ביטחון

קובץ חדש `backend/app/duty_eligibility_worker.py`, לפי אותו דפוס בדיוק כמו שאר ה-workers (`session_scope`, try/except, לוג), אך עם poll interval יומי (86400 שניות) במקום 300. קורא ל-`recheck_assignments` על כל השיבוצים הפרסומים הרלוונטיים. מחובר ב-`main.py`'s `lifespan`.

### נראות — backend

- endpoint חדש (או הרחבת קיים) שמחזיר ספירת שיבוצים לא-כשירים בהיקף היררכי של המשתמש המבקש — לצריכת ה-badge בסרגל הניווט.
- `ShiftOut`/שדה דומה ב-`shifts.py` מקבל `has_ineligible_assignment: bool` (או `ineligible_count`) לכל שורת תורנות.
- תגובת ה-roster/modal לתורנות כוללת `weapon_ineligible`/`weapon_ineligible_reason` לכל `DutyAssignment`.

### נראות — frontend

- `UnifiedNav.tsx`: badge אדום חדש (בנוסף ל-badge הכחול הקיים), מציג ספירה מצטברת.
- `ShiftsPage.tsx`: אינדיקטור ⚠️ נוסף לכל שורה עם שיבוץ לא-כשיר.
- `DutyManagementPage.tsx`: אינדיקטור ⚠️ ליד שורת השיבוץ הרלוונטית.
- modal הצפייה בתורנות: ⚠️ ליד שם החייל הלא-כשיר, עם tooltip/טקסט הנימוק.

### פתרון — backend/frontend

- כפתור חייל: פותח את `OfferSwapModal`/זרימת הבקשה הקיימת, ממולא מראש עם ה-`assignment_id` הרלוונטי.
- כפתור אחראי תורנויות ("החלף"): מבטל (`cancel`) את השיבוץ הלא-כשיר, פותח `ShiftAssignModal` ממוקד לתורנות ולחריץ שהתפנה.

## Testing requirements

- מיגרציה: שלוש העמודות נוצרות עם הדיפולטים הנכונים.
- `backend/app/services/tests/test_duty_eligibility_watch.py`: מעבר False→True מעדכן מטמון ושולח 3 הודעות (חייל/מפקד/אחראי תורנויות) עם הנימוק; מעבר True→False מעדכן בשקט בלי הודעות; שיבוץ לא-פרסום (`cancelled`/`algorithm_draft`) לא נבדק; `required_range_type=None` לא נבדק כלל.
- בדיקות אינטגרציה לכל נקודת שילוב מונעת-אירועים (תיקון נוכחות, הכרעת פטור, שינוי הגדרה, שינוי `required_range_type`) — מוודאות שהבדיקה הממוקדת מופעלת בפועל.
- בדיקת worker: קורא ל-`recheck_assignments` על כל השיבוצים הרלוונטיים, מטפל בשגיאות בלי להפיל את ה-worker.
- Frontend: badge בסרגל הניווט מציג ספירה נכונה; אינדיקטור ⚠️ מופיע בכל אחד משלושת המיקומים; כפתור "החלף" מבטל ופותח את `ShiftAssignModal` נכון; כפתור חייל פותח את זרימת ההחלפה עם ה-assignment הנכון.
- Suite קיים (backend + frontend) נשאר ירוק.
