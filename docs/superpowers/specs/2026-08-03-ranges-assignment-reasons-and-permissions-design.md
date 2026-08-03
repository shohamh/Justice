# מטווחים: סיבות שיבוץ, תרגום, הרשאות ורענון — Design Spec

## Goal

להפוך את modal השיבוצים של מטווחים לשקוף וברור: שיבוץ אוטומטי יציג סיבה קצרה לכל בחירה, שיבוץ ידני יקבל סיבה הניתנת לעריכה, כל הטקסטים והודעות השגיאה יהיו בעברית, מטווחים קרובים ישקפו מיד הסרה של חייל, ופעולות שינוי יוצגו רק למשתמשים המורשים להפעילן.

## Approved UX decisions

- לכל שיבוץ תוצג סיבת בחירה קצרה וברורה, כגון כשירות, זמינות או איזון עומס.
- שיבוץ ידני יתחיל בסיבה "שיבוץ ידני" ויאפשר למנהל לערוך את הסיבה.
- טבלת השיבוצים תציג את הסיבה ליד כל חייל, הן בראשיים והן ברזרבה.
- בקשת פטור עצמי לא תופיע בתוך שורת חייל. במקום זאת, חייל עם שיבוץ עתידי שאינו טיוטה יקבל בראש modal הפרטים כפתור "אני לא אוכל להגיע"; טופס הסיבה ייפתח מאותו כפתור.
- מטווחים יישארו לחיצים לכל משתמש. משתמש ללא הרשאת שינוי יראה modal לקריאה בלבד, ללא כפתורי עריכה, ביטול, שיבוץ, אישור או שינוי נוכחות.
- הודעות, labels ושגיאות API שהמשתמש רואה בפיצ'ר יוצגו בעברית דרך i18n.

## Architecture and data flow

### Assignment explanation

Add persisted fields to `RangeAssignment`:

- `assignment_reason_code`: stable backend code for an automatic or default reason.
- `assignment_reason_text`: optional editable text for a human explanation.

The auto-assignment service assigns a reason code based on the actual ranking/eligibility criterion. The API returns both fields. The frontend maps codes to Hebrew labels and displays the editable text when present. Manual assignment sends the default manual code/text and exposes an edit control in the assignment modal.

The existing attendance `note` remains attendance-specific and is not reused for selection explanations.

### Current-user upcoming ranges

The ranges response gains `assigned_to_me`, computed server-side from the authenticated user’s range assignments. The home-page upcoming-ranges widget filters to future planned events where this value is true. The planning page continues to show all ranges in the authorized planning scope.

All range assignment mutations invalidate the shared ranges query and the current range detail query, so the home widget updates immediately after removal or confirmation.

### Scoped permissions

The range API returns `can_edit_attendance` for the current user/event, using the same backend authority rule as the attendance mutation endpoint. The frontend gates attendance controls from this server-provided capability. Planner mutations continue to require `canPlan` in the UI and matching backend authorization.

### Translation

Move range UI labels, mutation feedback, shortfall text, assignment reasons, and API error mapping into the existing Hebrew i18n catalog. Raw backend error codes must not be rendered directly.

## Testing requirements

- Backend model/migration/API tests cover reason persistence, auto-assignment reason codes, manual reason updates, `assigned_to_me`, and `can_edit_attendance`.
- Frontend tests cover reason columns, manual reason editing, Hebrew text/error mapping, top-level self-excuse action, permission-gated actions, and immediate query invalidation behavior.
- Regression tests ensure removing a soldier removes the upcoming range from that soldier’s home widget.
- Existing backend and frontend suites must remain green.
