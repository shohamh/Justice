# רה-ארגון הרשאות שקיפות ונראות היסטוריית תורנויות — Design Spec

## Goal

היום קיימות כמה בעיות נראות/הרשאות סביב עמוד השקיפות (`TransparencyPage.tsx`) והיסטוריית תורנויות של חיילים:

1. חייל פשוט יכול לראות היסטוריית תורנויות של **כל** חייל אחר — אין שום בדיקת היררכיה/הרשאה בנתיב הזה, רק סינון סוגי אירועים.
2. הגדרת המערכת `transparency.visible_commander_levels` (multiselect של דרגים) קובעת מי יכול לראות את עמוד השקיפות, אבל כברירת מחדל (ריקה) היא פתוחה לכולם — כולל חיילים פשוטים.
3. גם כשההגדרה מוגדרת (למשל "מדור ומעלה"), חייל פשוט יכול לפעמים עדיין לראות את העמוד בגלל race condition: העמוד מציג נתונים באופן אופטימי ומגיב רק בדיעבד ל-403, ושלוש כרטיסיות שונות בעמוד (`transparency`, `fairness-components`, `effort-breakdown`) נבדקות בנפרד — שתיים מהן לא בודקות את ההגדרה בכלל — כך שהעמוד עלול "להבהב" ולהעיף את המשתמש רק אחרי שכבר הציג לו תוכן.
4. אין דרך להגדיר שמפקדים/אחראי תורנויות יראו מעט מעבר לתחום הפיקוד המדויק שלהם (לצורך השוואה מול תת-יחידות מקבילות), בלי לפתוח את הכל.

המטרה: איחוד לוגיקת ההרשאה למקום אחד, המוחל באופן עקבי הן על עמוד השקיפות (כולל שלוש הכרטיסיות) והן על היסטוריית תורנויות של חייל אחר, וסגירת כל הפרצות שתוארו למעלה.

## Approved decisions

### הגדרות מערכת — שלוש הגדרות במקום multiselect אחד

מחליף את `transparency.visible_commander_levels` (JSON array):

| מפתח | סוג | משמעות | ברירת מחדל |
|---|---|---|---|
| `transparency.min_visible_level` | מפתח דרג (`HierarchyLevelType.key`) או ה-sentinel `"every_soldier"` | הדרג המינימלי שמפקד/אחראי תורנויות צריך להחזיק (בכל צומת שהוא מפקד/אחראי עליו) כדי לראות שקיפות והיסטוריית תורנויות של **כולם**, לא רק בתחומו | `"every_soldier"` (פתוח — תואם להתנהגות הקיימת כשההגדרה ריקה) |
| `transparency.commander_levels_above` | מספר שלם ≥ 0 | כמה דרגים מעל הצומת שהמפקד מפקד עליו הוא רואה בנוסף לתת-העץ שלו (0 = תת-העץ שלו בלבד, כהיום) | `0` |
| `transparency.duty_manager_levels_above` | מספר שלם ≥ 0 | אותו דבר, עבור אחראי תורנויות ביחס לשורש/י ה-`DutyManagerScope` שלו | `0` |

`min_visible_level` הוא ערך יחיד (לא multiselect), נבחר מתוך רשימת ה-`HierarchyLevelType` המוגדרים בפועל בפריסה הזו (ממוינים לפי `rank`), בתוספת אופציית "כל חייל" בקצה הפתוח. **לא** מקודד קשיח רשימת דרגים קבועה — הרשימה נשארת data-driven כמו היום.

`SystemSettingsPage.tsx`: ה-multiselect הקיים (`type: "multiselect"`, שורות ~315-325, ~523-547) מוחלף ב-select יחיד ממוין לפי rank + אופציית "כל חייל", ושני שדות מספריים (`commander_levels_above`, `duty_manager_levels_above`) עם טקסט עזר המסביר את מקרה השימוש של "השוואה מול היחידה המקבילה".

### מיגרציה

- אם `transparency.visible_commander_levels` הישן היה ריק/לא מוגדר → `min_visible_level = "every_soldier"`.
- אם היה מוגדר (מערך לא ריק) → `min_visible_level` = הדרג הבכיר ביותר (rank הנמוך ביותר) מבין הדרגים שנבחרו במערך הישן.
- `commander_levels_above` ו-`duty_manager_levels_above` מתחילים ב-`0` בכל הפריסות הקיימות (ללא שינוי התנהגות בציר הזה עד שאדמין יבחר להרחיב).
- מיגרציית Alembic data-migration שקוראת את הערך הישן, מחשבת את החדש, וכותבת. אם המפתח הישן לא קיים כלל (התקנה חדשה) — נכתב ברירת המחדל `"every_soldier"` ישירות.

### פונקציית הרשאה משותפת

פונקציה חדשה `can_view_soldier_scope(session, viewer: Soldier, target_node: HierarchyNode) -> bool` (ב-`backend/app/auth/authz.py` או מודול חדש `visibility.py` לצידו):

1. `viewer.role == "admin"` → `True`.
2. **תחום מורחב עצמי (תמיד מותר):**
   - לכל צומת שה-viewer מפקד עליו (`HierarchyNode.commander_id == viewer.id`): חשב אב-קדמון `commander_levels_above` צעדים למעלה לאורך `path_ids` (עצירה בשורש אם חורג); אם `target_node` נמצא בתת-העץ של אותו אב-קדמון (כלומר, ה-id שלו מופיע ב-`target_node.path_ids`) → `True`.
   - אותו דבר עבור כל שורש `DutyManagerScope` של ה-viewer, עם `duty_manager_levels_above`.
3. **דרג בכיר מספיק רואה את כולם:**
   - `threshold = get_setting("transparency.min_visible_level", "every_soldier")`.
   - אם `threshold == "every_soldier"` → `True` (לכולם, כולל חיילים פשוטים).
   - אחרת: קח את הדרג הבכיר ביותר (rank מינימלי) מבין כל הצמתים שה-viewer מפקד/מנהל תורנויות עליהם. אם הוא קיים ו-rank שלו ≤ ה-rank של `threshold` (כלומר בכיר יותר או שווה) → `True`.
4. אחרת → `False`.

חיילים פשוטים (ללא פיקוד וללא scope) לא עוברים שלב 2 (אין להם צמתים) ולא עוברים שלב 3 אלא אם ה-threshold הוא `"every_soldier"` — תואם בדיוק לדרישה: "חייל פשוט לא יכול לצפות בהיסטוריית תורנויות של חייל אחר, אלא אם כך מוגדר במערכת", ו"מפקד תמיד יכול לראות את היסטוריית התורנויות של חייליו".

### שימוש עקבי בפונקציה

מחליף שלושה מקומות נפרדים שהיום לא עקביים:

- `_transparency_allowed` ב-`scoring.py` (המשמש את `GET /scoring/transparency`) → קורא ל-`can_view_soldier_scope` לכל שורת חייל/צומת מוצגת.
- `fairness-components` ו-`effort-breakdown` (`scoring.py`) — היום עוקפים את הבדיקה לגמרי; מקבלים עכשיו את אותה בדיקה לכל חייל שהם מחזירים.
- `GET /soldiers/{id}/duty-history` (`soldiers.py:522-560`) — הענף `is_plain_soldier and not is_self` היום לא בודק שום דבר ורק מסנן סוגי אירועים. מוחלף בקריאה מפורשת ל-`can_view_soldier_scope`; אם `False` → 403 (לא רשימה מסוננת). אם `True` — הסינון הקיים לפי סוגי אירועים ציבוריים (`_PUBLIC_EVENT_TYPES`) וה-`can_see_private` הנפרד לשדות רגישים **נשארים כפי שהם** כשכבת הגבלה שנייה, בלתי תלויה.

### Frontend — סגירת ה-race condition

- נקודת קצה קלה (או הרחבת `/me` הקיים) שמחזירה `can_view_transparency: bool` מחושב מראש עבור המשתמש הנוכחי — נטענת פעם אחת בזמן ה-bootstrap של הסשן, לצד שאר מצב האימות.
- `TransparencyPage.tsx` בודק את הדגל הזה **לפני** רינדור התוכן המוגן (כולל שלוש הכרטיסיות), במקום לרנדר באופן אופטימי ולהגיב ל-403 שמגיע בדיעבד מכל endpoint בנפרד. כך כל הכרטיסיות נשערות מול אותו מקור אמת יחיד, ולא מול שלושה checks נפרדים שנפתרים בזמנים שונים.
- `UnifiedSoldierModal`/`DutyHistoryPanel.tsx` — קריאת ה-API הקיימת ל-`getSoldierDutyHistory` מתחילה להחזיר 403 עבור צפייה לא-מורשית; ה-UI מציג הודעת "אין הרשאה" תואמת (כמו ב-`TransparencyPage`) במקום להציג תוצאה ריקה/חלקית.

## Architecture and data flow

### מיגרציה ומודל

- Alembic revision: data migration שקוראת את `transparency.visible_commander_levels`, כותבת את שלוש ההגדרות החדשות לפי הכללים לעיל, ומוחקת (או משאירה בלי שימוש, לבדיקה) את המפתח הישן.
- `get_setting`/`set_setting` הקיימים (מנגנון `SystemSetting` הגנרי) משמשים ללא שינוי מבני לשלוש ההגדרות החדשות.

### ליבת הרשאה

- מודול/פונקציה `can_view_soldier_scope` כמתואר למעלה, עם helper פרטי `_ancestor_n_up(node, n)` שהולך לאורך `path_ids` (או משתמש בהיררכיה בפועל) ומחזיר את הצומת המתאים, ו-helper `_best_commanded_rank(session, viewer)` שמחזיר את ה-rank הבכיר ביותר מבין כל הצמתים שה-viewer מפקד/מנהל תורנויות עליהם (או `None`).
- בדיקות יחידה מקיפות לפונקציה הזו (ראה Testing).

### נקודות קריאה

- `scoring.py`: `_transparency_allowed` מוחלף בקריאות ל-`can_view_soldier_scope` לכל שורה/סיכום שמוחזר מ-`/scoring/transparency`, `/scoring/fairness-components`, `/scoring/effort-breakdown`.
- `soldiers.py`: הענף הרלוונטי ב-`GET /soldiers/{id}/duty-history` מוחלף כמתואר.
- endpoint/שדה חדש (למשל בתוך `/me` הקיים) שמחזיר `can_view_transparency` לצריכת ה-frontend.

### נראות — frontend

- `TransparencyPage.tsx`: gate מוקדם לפי `can_view_transparency` לפני רינדור התוכן; אם `False` — מציג את מסך "אין הרשאה" הקיים מיד, בלי לנסות לטעון אף אחת משלוש הכרטיסיות.
- `SystemSettingsPage.tsx`: multiselect קיים מוחלף בשלושת השדות החדשים (select יחיד + שני שדות מספריים) עם טקסט עזר בעברית.
- `DutyHistoryPanel.tsx`/`UnifiedSoldierModal.tsx`: מטפל ב-403 מ-`getSoldierDutyHistory` עם הודעת "אין הרשאה" תואמת (כרגע קורה רק דרך ה-error boundary/הודעת שגיאה גנרית — יעודכן להודעה ברורה).

## Testing requirements

- `backend/app/auth/tests/test_can_view_soldier_scope.py` (חדש): admin רואה הכל; מפקד רואה תת-עץ עצמו; מפקד עם `commander_levels_above=0` לא רואה מחוץ לתת-העץ; מפקד עם `commander_levels_above>0` רואה את האב-קדמון המורחב; אותו דבר לאחראי תורנויות עם `duty_manager_levels_above`; מפקד/אחראי בדרג בכיר מספיק (rank ≤ threshold) רואה חייל לא קשור; חייל פשוט נחסם כברירת מחדל; חייל פשוט מותר כש-`min_visible_level == "every_soldier"`; מיגרציה — מערך ישן לא ריק ממופה לדרג הבכיר ביותר בו, מערך ריק/חסר ממופה ל-`"every_soldier"`.
- בדיקות route: `/scoring/transparency`, `/scoring/fairness-components`, `/scoring/effort-breakdown`, ו-`GET /soldiers/{id}/duty-history` מחזירים 403 באופן עקבי לחייל פשוט חסום (סוגר את חוסר-העקביות הקיים היום שבו היסטוריית תורנויות דולפת בלי קשר להגדרת השקיפות).
- בדיקת מיגרציה (Alembic): מריצה על נתוני seed עם ערך ישן לדוגמה, מוודאת שהערכים החדשים נכתבים נכון.
- Frontend: `TransparencyPage` לא מרנדרת אף כרטיסייה מוגנת לפני שהדגל `can_view_transparency` נטען (מונע את ה-flash/race); הודעת "אין הרשאה" מוצגת נכון גם ב-`DutyHistoryPanel` עבור 403.
- Suite קיים (backend + frontend) נשאר ירוק.

## Out of scope (items מרשימת המשוב המקורית, לספקים נפרדים)

- הבהרת דף הבית (רזרבה מול ראשי, הסתרת מספר משובצים מחייל).
- שיבוץ אוטומטי מוגבל לסוגי תורנויות/קבוצות כשירות ספציפיות.
- פירוט מלא בהתראות (למשל "בקשת הפטור נדחתה — איזו בקשה").
- הבהרת UX לבקשת פטור קבוע.
