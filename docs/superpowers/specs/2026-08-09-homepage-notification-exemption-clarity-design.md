# בהירות עמוד הבית, פירוט התראות, פטור קבוע והתראות פעילות — Design Spec

## Goal

ריכוז כמה בעיות UX קטנות ובלתי-תלויות שעלו ממשוב חיילים/מפקדים:

1. בעמוד הבית לא ברור לחייל אילו תורנויות שלו הן רזרבה ואילו ראשיות, ובאיזה מצב הרזרבה נמצאת (רגילה מול הוקפצה).
2. התראות על החלטה בבקשת פטור ("בקשת הפטור נדחתה"/"אושרה") לא כוללות פרטים — איזו בקשה, איזה סוג פטור, לאילו תאריכים.
3. לא ברור בטופס בקשת פטור איך מסמנים פטור **קבוע** (ללא תאריך סיום) — היום זה נעשה על ידי השארת שדה תאריך הסיום ריק, בלי שום רמז ב-UI.
4. כפתורי ה-v/x בהתראות (בפעמון וב-`NotificationsPage`) הם תווי יוניקוד זעירים, ומייצגים היום רק "סמן כנקרא" ו"מחק את ההתראה" — לא פעולת אישור/דחייה בפועל על הבקשה שההתראה מתייחסת אליה. לחלק מסוגי ההתראות יש בפועל החלטה בינארית פשוטה שאפשר לבצע ישירות מההתראה.

המטרה: לסגור את ארבע הבעיות, כל אחת בהיקף מצומצם משלה, בלי לגעת בזרימות הקיימות (בקשות פטור, בקשות החלפה, בקשות פטור ממטווח) מעבר לנדרש.

## Approved decisions

### 1. בהירות רזרבה/ראשי בעמוד הבית

`UpcomingDutiesWidget.tsx` עובר מטבלת שורות לבלוקים (cards) לכל תורנות קרובה:

- **ראשי** (לא רזרבה): בלוק עם רקע מלא (לא שקוף), תווית "ראשי" בשורה מתחת לשם סוג התורנות.
- **רזרבה, לא הוקפץ**: מסגרת מקווקוות (dotted), רקע חצי-שקוף בגוון עמום, תווית "רזרבה" בשורה מתחת לשם סוג התורנות.
- **רזרבה שהוקפץ** (`called_up_from` מוגדר על השיבוץ): אותה מסגרת מקווקוות, אך התווית מוחלפת ל-"הוקפץ" + טווח התאריכים (בהשאלה מהמחרוזות הקיימות `reserve_called_up`/`called_up_from_to`), **במקום** "רזרבה" — כי מבחינת החייל הוא כבר משרת בפועל כמו ראשי לתקופה הזו.

**אין** הצגת מספר משובצים (X/Y) — לא רלוונטי לחייל הפשוט; המידע הזה כבר קיים וזמין למפקד/אחראי תורנויות דרך `ShiftDetailPanel` הקיים.

### 2. פירוט מלא בהתראות פטור

בכל אתר יצירת התראה על החלטה בבקשת פטור (`reject_request`, `approve_duty_manager_step` ב-`services/exemption_requests.py`, ומקבילותיהן ב-`services/exemptions.py` עבור מתן/ביטול פטור ישיר):

- `title` כולל את שם סוג הפטור (`ExemptionType.name`) ואת טווח התאריכים, או "קבוע" אם `end_date is None` (ר' סעיף 3 להלן לגבי המוסכמה). למשל: `בקשת הפטור נדחתה — חופשה, 10/08–15/08`.
- `body` כולל את `decision_note` כשהוא קיים (למשל נימוק דחייה), באותו דפוס שכבר קיים ב-`notify_duty_managers_of_request` עבור `reason`.

אין שינוי סכמה — `Notification.title`/`body` כבר תומכים בכך, ו-`reference_id` כבר מצביע על הבקשה הספציפית.

### 3. checkbox לפטור קבוע

בטופס בקשת הפטור ב-`MyRequestsPage.tsx`: checkbox חדש "פטור קבוע". כשמסומן — שדה תאריך הסיום מנוטרל (disabled) ומתרוקן, והפעלת השליחה שולחת `end_date: null`. כשלא מסומן — שדה תאריך הסיום הופך לחובה (required) כפי שהוא היום.

אין שינוי backend/סכמה — הצד השרת כבר מתייחס ל-`end_date = null` כפטור קבוע בכל מקום (מהמרה ישירה מ-`ExemptionRequest` ל-`SoldierExemption` בעת אישור), והתצוגה הקיימת כבר משתמשת במחרוזת `exemptions.forever`.

### 4. התראות פעילות — כפתורים אמיתיים + פעולות החלטה

**כפתורי בסיס, בכל התראה, תמיד:** שני כפתורי אייקון אמיתיים (padding, hover, לא תו יוניקוד זעיר) עם אייקוני lucide — `Check`/`CheckCheck` ל"סמן כנקרא" (קורא ל-`markRead` הקיים), ו-`Trash2` ל"מחק" (קורא ל-`deleteNotification` הקיים). מוצגים תמיד, בלי תלות בסוג ההתראה.

**כפתורי החלטה נוספים, רק לשני סוגי התראה:** `swap_offer_incoming` ו-`range_excusal_pending` — אלו הסוגים היחידים היום שיש להם החלטה בינארית פשוטה שאפשר לבצע בלי לצאת מההתראה, בלי לדרוש עיון מעמיק (בשונה למשל מ-`constraint_pending`/`exemption_request_pending`/`swap_pending_approval`/`transfer_request_pending`/`enrollment_request_received`, שדורשים עיון בפרטי הבקשה בעמוד הייעודי). מוצגים בנוסף לשני הכפתורים הבסיסיים:

- **אשר** — כפתור ירוק עם אייקון `Check`.
- **דחה** — כפתור אדום עם אייקון `X`.

עבור `swap_offer_incoming`: `n.reference_id` הוא `SwapRequest.id` וממופה ישירות לפונקציות הקיימות `soldierApproveSwap(id)` / `soldierRejectSwap(id)` (`frontend/src/api/swaps.ts`), הקוראות ל-`POST /me/swaps/{id}/approve` / `POST /me/swaps/{id}/reject` — נקודות קצה השרות-עצמי הקיימות, ללא צורך בהרשאה נוספת (השרת בודק שהמשתמש הוא אכן מועמד מוזמן בבקשה).

עבור `range_excusal_pending`: נקודת הקצה הקיימת (`POST /ranges/{event_id}/excusal-requests/{request_id}/decide`) דורשת גם `event_id` וגם `request_id`, אך ל-`reference_id` של ההתראה יש רק את ה-`request_id`. פותרים על ידי הוספת עמודת `metadata` (JSONB, nullable) ל-`Notification`, ו-`services/range_excusal.py` (`request_primary_excusal`) כותב לתוכה `{"event_id": ...}` בעת יצירת ההתראה. ה-frontend קורא ל-`decideRangeExcusal(metadata.event_id, n.reference_id, approve)` הקיים.

כל שאר סוגי ההתראות ("ממתין לאישור" וכדומה) ממשיכים להציג רק את שני הכפתורים הבסיסיים + קישור ניווט קיים לעמוד המלא לקבלת ההחלטה — ללא שינוי.

## Architecture and data flow

### מיגרציה ומודל

- הוספת `called_up_from: date | None`, `called_up_to: date | None` ל-`EffectiveDutyOut` (`backend/app/routes/assignments.py`) ול-`effective_duty_spans()` (`backend/app/services/scoring.py`) — מעתיק את שני השדות מ-`DutyAssignment` (קיימים כבר במודל) לתוך ה-span המחושב, כמו שכבר נעשה עם `weapon_ineligible`. אין שינוי סכמה (השדות כבר קיימים ב-`DutyAssignment`).
- הוספת עמודת `metadata: dict | None` (JSONB, nullable, default `None`) ל-`Notification`. מיגרציית Alembic להוספת העמודה בלבד — לא נדרש backfill (ערך `null` תקין לכל ההתראות הקיימות ולרוב הסוגים העתידיים).

### Backend

- `services/exemption_requests.py`: `reject_request()`, `approve_duty_manager_step()` — טוענים `ExemptionType` לפי `req.exemption_type_id` ובונים `title`/`body` מועשרים.
- `services/exemptions.py`: אותו טיפול במתן/ביטול פטור ישיר (`grant`/`revoke`).
- `services/range_excusal.py`: `request_primary_excusal()` — כותב `metadata={"event_id": ...}` בקריאה ל-`create_notification` עבור `range_excusal_pending`.
- `create_notification()` (המנגנון המשותף, `services/notifications.py`): מקבל פרמטר `metadata: dict | None = None` אופציונלי חדש, מעביר אותו ל-`Notification.metadata`.

### Frontend

- `EffectiveDuty` (`frontend/src/api/assignments.ts`): שני שדות חדשים `called_up_from`/`called_up_to`.
- `UpcomingDutiesWidget.tsx`: שינוי מבנה מטבלה לבלוקים, לוגיקת תווית לפי `is_reserve`/`called_up_from` כמתואר לעיל.
- `MyRequestsPage.tsx`: checkbox "פטור קבוע" בטופס בקשת פטור, state מקומי (לא נשמר בשרת) הממופה ל-`end_date: null`/שדה חובה.
- `NotificationDTO` (`frontend/src/api/notifications.ts`): שדה `metadata: Record<string, unknown> | null` חדש.
- `NotificationBell.tsx`, `NotificationsPage.tsx`: מחליפים את תווי ה-✓/✕ בכפתורי lucide (`Check`, `Trash2`, ובנוסף `Check`/`X` בצבע ירוק/אדום לשני סוגי ההחלטה), עם לוגיקת "האם זו התראת החלטה מהירה" (`type === "swap_offer_incoming" || type === "range_excusal_pending"`) לקביעה אם להציג את זוג הכפתורים הנוסף.
- `getNotificationLink` (`frontend/src/api/notifications.ts`): מוסיף מיפוי חסר עבור `swap_offer_incoming` → `/swaps?tab=incoming` (כיום נופל בטעות ל-`/swaps?tab=mine`), כדי שהניווט הרגיל (ללא לחיצה על כפתור ההחלטה) ימשיך לעבוד נכון.

## Testing requirements

- Backend: בדיקות יחידה ל-`reject_request`/`approve_duty_manager_step` (ומקבילות ב-`exemptions.py`) שמוודאות ש-`title`/`body` כוללים את שם סוג הפטור ואת טווח התאריכים/"קבוע"; בדיקה ש-`request_primary_excusal` כותב `metadata={"event_id": ...}` נכון.
- Backend: בדיקת מיגרציה/מודל ש-`Notification.metadata` נשמר ונטען כ-JSON תקין (dict), וברירת מחדל `None` להתראות קיימות/ישנות.
- Backend: בדיקה ש-`GET /assignments/effective` מחזיר `called_up_from`/`called_up_to` נכון (span עם שיבוץ רזרבה מוקפץ מול לא-מוקפץ).
- Frontend: `UpcomingDutiesWidget.test.tsx` — בדיקת תווית "ראשי"/"רזרבה"/"הוקפץ" לפי הקומבינציות של `is_reserve`/`called_up_from`; אין הצגת מספר משובצים.
- Frontend: `MyRequestsPage.test.tsx` — סימון ה-checkbox מנטרל ומרוקן את שדה תאריך הסיום ושולח `end_date: null`; ביטול הסימון מחזיר את השדה לחובה.
- Frontend: `NotificationBell.test.tsx`/`NotificationsPage.test.tsx` — כפתורי "סמן כנקרא"/"מחק" מוצגים תמיד; כפתורי אשר/דחה מוצגים רק עבור `swap_offer_incoming`/`range_excusal_pending`; לחיצה על אשר/דחה קוראת לפונקציית ה-API הנכונה עם הפרמטרים הנכונים (כולל `metadata.event_id` עבור מטווח).
- Suite קיים (backend + frontend) נשאר ירוק.

## Out of scope

- שיבוץ אוטומטי מוגבל לסוגי תורנויות/קבוצות כשירות ספציפיות — ספק נפרד ([`2026-08-09-auto-assign-scope-filters-design.md`](2026-08-09-auto-assign-scope-filters-design.md)).
- הוספת כפתורי אשר/דחה מהירים לסוגי התראות נוספים מעבר לשניים שצוינו — אם יתברר בהמשך שעוד סוג התראה מתאים, ידרוש ספק/דיון נפרד (כל סוג דורש בדיקת "פשטות ההחלטה" משלו, כמו שנעשה כאן עבור `range_excusal_pending`).
