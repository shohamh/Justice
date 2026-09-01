import { Fragment, useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, HelpCircle, Upload } from "lucide-react";
import Layout from "../components/Layout";
import { getSystemSettings, updateSystemSettings, exportSystemSettings, importSystemSettings, SettingsMap } from "../api/systemSettings";
import { getRankLadder, updateRankAdvancementIntervals, RankIntervalUpdate, RankTrack } from "../api/rankAdvancement";
import ReactMarkdown from "react-markdown";
import changelogRaw from "../../CHANGELOG.md?raw";
import { queryKeys } from "../queryKeys";
import { useLevelTypes } from "../hooks/useLevelTypes";
import DateInput from "../components/DateInput";

interface SettingDef {
  key: string;
  label: string;
  description?: string;
  type: "boolean" | "number" | "decimal" | "select" | "date" | "text";
  defaultValue: string | number | boolean | string[];
  options?: { value: string; label: string }[];
}

const SETTING_GROUPS: { label: string; settings: SettingDef[] }[] = [
  {
    label: "שקיפות וניקוד",
    settings: [
      {
        key: "scoring.active_days_reference_date",
        label: "תאריך ייחוס לימים פעילים",
        description: "מועד תחילת תיעוד התורנויות עבור חישוב שקיפות. שינוי התאריך עשוי לשנות בדיעבד את השקיפות והניקוד.",
        type: "date" as const,
        defaultValue: "",
      },
    ],
  },
  {
    label: "חיילים",
    settings: [
      {
        key: "soldiers.commander_delete_min_level",
        label: "החל מאיזו רמת פיקוד ניתן למחוק חייל",
        description: "מפקד ברמה זו ומעלה (קרוב יותר לשורש) יכול למחוק (רישום היסטורי) חיילים בתת-העץ שלו",
        type: "select" as const,
        defaultValue: "מדור",
        options: [],
      },
    ],
  },
  {
    label: "תורנויות ומשמרות",
    settings: [
      {
        key: "duty.default_rest_hours",
        label: "שעות מנוחה בסיסיות בין תורנויות",
        description: "מספר שעות המנוחה המינימלי הנדרש לחייל בין סיום תורנות אחת לתחילת הבאה. ניתן לשנות פר-סוג תורנות.",
        type: "number" as const,
        defaultValue: 12,
      },
      {
        key: "shifts.auto_split_node_quotas",
        label: "פיצול מכסות אוטומטי לפי פוטנציאל",
        description: "כשמופעל, מכסות ליחידות-בת מחושבות אוטומטית לפי פוטנציאל (סה\"כ חיילים) בכל פעם שנבחרת יחידת-אב יחידה ונקבע מספר נדרש בטופס משמרת",
        type: "boolean" as const,
        defaultValue: false,
      },
    ],
  },
  {
    label: "אילוצים אישיים",
    settings: [
      { key: "constraints.personal_cap_days", label: "מכסת ימי אילוץ לחייל", description: "מספר ימי האילוץ המרביים שחייל יכול לבקש", type: "number", defaultValue: 15 },
      {
        key: "constraints.reset_period",
        label: "תקופת איפוס ימי אילוץ",
        description: "התדירות שבה מכסת ימי האילוץ של חייל מתאפסת",
        type: "select" as const,
        defaultValue: "quarter",
        options: [
          { value: "quarter", label: "רבעון" },
          { value: "half_year", label: "חצי שנה" },
          { value: "year", label: "שנה" },
        ],
      },
      { key: "constraints.require_commander_approval", label: "דורש אישור מפקד", description: "האם בקשות אילוץ דורשות אישור מפקד", type: "boolean", defaultValue: true },
      { key: "constraints.require_duty_manager_approval", label: "דורש אישור אחראי תורנויות", description: "האם בקשות אילוץ דורשות אישור אחראי תורנויות (בנוסף לאישור מפקד)", type: "boolean", defaultValue: true },
      { key: "constraints.allow_manual_override", label: "אפשר עקיפת אילוצים בשיבוץ ידני", description: "האם אחראי תורנויות יכול לשבץ ידנית חייל עם אילוץ אישי מאושר, לאחר מתן נימוק", type: "boolean", defaultValue: true },
    ],
  },
  {
    label: "החלפות",
    settings: [
      { key: "swaps.require_manager_approval", label: "דורש אישור מפקד", description: "האם החלפות דורשות אישור מפקד", type: "boolean", defaultValue: true },
      { key: "swaps.require_duty_manager_approval", label: "דורש אישור אחראי תורנויות", description: "האם החלפות דורשות אישור אחראי תורנויות (בנוסף לאישור מפקד)", type: "boolean", defaultValue: true },
      {
        key: "swaps.restrict_to_hierarchy_level",
        label: "הגבלת החלפות לרמת היררכיה",
        description: "מגביל בקשות החלפה לחיילים החולקים אב משותף ברמה זו (ריק = ללא הגבלה)",
        type: "select" as const,
        defaultValue: "",
        options: [],
      },
    ],
  },
  {
    label: "פטורים",
    settings: [
      {
        key: "exemptions.commander_exemption_min_level",
        label: "החל מאיזו רמת פיקוד ניתן להעניק פטור פיקודי",
        description: "מפקד ברמה זו ומעלה (קרוב יותר לשורש) יכול להעניק פטור פיקודי, גם ללא דרגת קצונה מתאימה",
        type: "select" as const,
        defaultValue: "מרכז",
        options: [],
      },
      {
        key: "exemptions.commander_escalation_min_level",
        label: "החל מאיזו רמת אחראי תורנויות ניתן להחיל פטור פיקודי מיידית",
        description: "אחראי תורנויות ברמה זו ומעלה (או מנהל) יכול להחיל פטור פיקודי באופן מיידי, ללא המתנה לאישור",
        type: "select" as const,
        defaultValue: "מרכז",
        options: [],
      },
      {
        key: "exemptions.medical_doc_min_commander_level",
        label: "צפייה במסמך רפואי — החל מאיזו רמת מפקד בשרשרת הפיקוד",
        description: "מפקדים ברמה זו ומעלה בשרשרת הפיקוד של החייל יכולים לצפות במסמך הרפואי עצמו (לא רק בפרטי הפטור)",
        type: "select" as const,
        defaultValue: "מדור",
        options: [],
      },
      {
        key: "exemptions.medical_doc_min_duty_manager_level",
        label: "צפייה במסמך רפואי — החל מאיזו רמת אחראי תורנויות",
        description: "אחראי תורנויות עם סמכות ברמה זו ומעלה יכול לצפות במסמך הרפואי עצמו",
        type: "select" as const,
        defaultValue: "ענף",
        options: [],
      },
    ],
  },
  {
    label: "גימלים",
    settings: [
      {
        key: "gimalim.enabled",
        label: "גלגול תורנויות בגימלים",
        description: "כשמופעל, שחרור גימלים מגלגל את החייל לתורנות העתידית הבאה המתאימה — מרתיע ניצול לרעה של גימלים",
        type: "boolean" as const,
        defaultValue: true,
      },
      {
        key: "gimalim.default_rest_days",
        label: "ימי מנוחה נוספים לגימלים",
        description: "מספר ימים נוספים, מעל שעות המנוחה הבסיסיות, לפני שיבוץ חוזר לחייל ששוחרר בגימלים (ניתן לשינוי בכל פעולת גימלים)",
        type: "number" as const,
        defaultValue: 7,
      },
      {
        key: "gimalim.reserve_fate",
        label: "גורל רזרבת הגימלים",
        description: "מה קורה לרזרבה שהוקפצה לכיסוי לאחר שסיימה את תפקידה",
        type: "select" as const,
        defaultValue: "keep",
        options: [
          { value: "keep", label: "שמור כרזרבה כללית" },
          { value: "release", label: "שחרר מהתורנות" },
        ],
      },
    ],
  },
  {
    label: "הקפצה פיקודית",
    settings: [
      { key: "forced_callup.enabled", label: "הקפצה פיקודית מופעלת", description: "כיבוי מסתיר את דף ההקפצה הפיקודית ומבטל את כל הפעולות הקשורות אליה", type: "boolean" as const, defaultValue: false },
      {
        key: "hakpaza.callup_multiplier",
        label: "מכפיל הקפצה פיקודית",
        description: "מכפיל ניקוד שיחויב על חייל שהוקפץ פיקודית (ברירת מחדל: 2.0)",
        type: "decimal" as const,
        defaultValue: 2.0,
      },
    ],
  },
  {
    label: "כשירות",
    settings: [
      { key: "eligibility.mitvahim_months", label: "חודשים מאז מטווח אחרון", description: "מספר חודשים מרבי מאז מטווח אחרון לצורך כשירות", type: "number", defaultValue: 6 },
      { key: "eligibility.alal_months", label: 'חודשים מאז אל"ל אחרון', description: 'מספר חודשים מרבי מאז אל"ל אחרון לצורך כשירות', type: "number", defaultValue: 3 },
    ],
  },
  {
    label: "עליית דרגה",
    settings: [
      {
        key: "rank_advancement.warning_days",
        label: "ימי אזהרה לפני עליית דרגה",
        description: "כמה ימים לפני עליית דרגה צפויה תישלח לחייל התראה מקדימה",
        type: "number" as const,
        defaultValue: 7,
      },
    ],
  },
  {
    label: "ניקוד",
    settings: [
      { key: "scoring.reserve_standby_multiplier", label: "מכפיל רזרבה במצב המתנה", description: "מכפיל ניקוד לחייל רזרבה שלא הוקפץ", type: "decimal", defaultValue: 0.2 },
      { key: "scoring.reserve_called_up_multiplier", label: "מכפיל רזרבה שהוקפץ", description: "מכפיל ניקוד לחייל רזרבה שהוקפץ לשירות", type: "decimal", defaultValue: 1.0 },
      { key: "scoring.dismissed_multiplier", label: "מכפיל שחרור", description: "מכפיל ניקוד לימים בהם החייל שוחרר מתורנות", type: "decimal", defaultValue: 0.0 },
    ],
  },
  {
    label: "אלגוריתם — הוגנות",
    settings: [
      { key: "fairness.reserve_hierarchy_weight", label: "משקל קרבה היררכית לרזרבה", description: "משקל קרבה היררכית בבחירת חיילי רזרבה (0=ללא משקל, ערכים גבוהים=מעדיפים חיילים קרובים)", type: "decimal", defaultValue: 1.0 },
      {
        key: "fairness.reset_date",
        label: "תאריך איפוס נתוני הוגנות",
        description: "רק תורנויות מתאריך זה ואילך נלקחות בחשבון לחישוב עומס ההוגנות. מומלץ לבחור תחילת רבעון (1 בינואר, אפריל, יולי, אוקטובר). שינוי תאריך זה ישפיע על כל הרצות אלגוריתם עתידיות.",
        type: "date" as const,
        defaultValue: "",
      },
      {
        key: "fairness.effort_resolution",
        label: "רזולוציית עומס (הוגנות)",
        description: "דיוק חישוב ההוגנות — ככל שגבוה יותר, ההבחנה בין רמות עומס דקה יותר (ערך גבוה משמר תורנויות רזרבה). ברירת מחדל: 10000.",
        type: "number",
        defaultValue: 10000,
      },
    ],
  },
  {
    label: "אלגוריתם — צפיפות",
    settings: [
      { key: "algorithm.max_duties_per_window", label: "מכסת תורנויות ללא רזרבה בחלון (T)", description: "מספר תורנויות אמת מרבי לחייל בכל חלון נע. חייב להיות קטן או שווה למכסה הכוללת (R).", type: "number", defaultValue: 8 },
      { key: "algorithm.window_t", label: "אורך חלון תורנויות ללא רזרבה (Wt)", description: "גודל החלון הנע בימים שבו נספרת מכסת T. בדרך כלל קצר יותר מחלון R.", type: "number", defaultValue: 14 },
      { key: "algorithm.max_total_duties_per_window", label: "מכסת תורנויות כוללת בחלון (R)", description: "מספר התורנויות הכולל המרבי לחייל בכל חלון נע, כולל רזרבה. חייב להיות גדול או שווה ל-T.", type: "number", defaultValue: 15 },
      { key: "algorithm.window_r", label: "אורך חלון תורנויות כולל (Wr)", description: "גודל החלון הנע בימים שבו נספרת המכסה הכוללת R. בדרך כלל ארוך יותר מחלון T.", type: "number", defaultValue: 28 },
      { key: "algorithm.relax_t_ceiling", label: "תקרת הרפיה — תורנויות ללא רזרבה", description: "הערך המרבי שאליו האלגוריתם יכול להרפות את T כשאין פתרון פיזיבילי. חייב להיות ≤ תקרת R.", type: "number", defaultValue: 10 },
      { key: "algorithm.relax_r_ceiling", label: "תקרת הרפיה — תורנויות כוללת", description: "הערך המרבי שאליו האלגוריתם יכול להרפות את R כשאין פתרון פיזיבילי. R מורפה ראשון, ואחר כך T.", type: "number", defaultValue: 20 },
    ],
  },
  {
    label: "אלגוריתם — פירוק וקבוצות",
    settings: [
      { key: "algorithm.batching_enabled", label: "פירוק וקבוצות", description: "פירוק כל הרצה לקבוצות כשירות בלתי-תלויות ולקבוצות כרונולוגיות, כדי לשמור על הוגנות מדויקת (L1) גם בהרצות גדולות. כבה כדי לפתור את כל הבעיה בבת אחת.", type: "boolean", defaultValue: true },
      { key: "algorithm.batch_size", label: "גודל קבוצה (תורנויות)", description: "מספר התורנויות המרבי בקבוצה כרונולוגית אחת. קטן יותר = מהיר יותר אך גרידי יותר.", type: "number", defaultValue: 50 },
      { key: "algorithm.batch_time_limit_seconds", label: "מגבלת זמן לקבוצה (שניות)", description: "תקציב זמן הפותר לכל קבוצה.", type: "number", defaultValue: 120 },
    ],
  },
  {
    label: "הרשמה",
    settings: [
      { key: "registration.telegram_required", label: "טלגרם חובה", description: "האם חיילים חדשים חייבים לקשר חשבון טלגרם לאחר ההרשמה", type: "boolean", defaultValue: false },
      { key: "registration.email_domain_hint", label: "סיומת דומיין אימייל מומלצת", description: "דומיין ברירת מחדל המוצג כרמז בשדה האימייל, למשל gmail.com (ריק = ללא רמז)", type: "text", defaultValue: "" },
    ],
  },
  {
    label: "פרטיות",
    settings: [
      {
        key: "soldiers.phone_public",
        label: "מספר טלפון גלוי לכולם",
        description: "כשמופעל, כל חייל יכול לראות את מספר הטלפון של כל חייל אחר. כשכבוי, גלוי רק למפקדים/אחראי תורנויות בשרשרת הפיקוד ולחייל עצמו",
        type: "boolean" as const,
        defaultValue: true,
      },
      {
        key: "soldiers.email_public",
        label: "כתובת אימייל גלויה לכולם",
        description: "כשמופעל, כל חייל יכול לראות את כתובת האימייל של כל חייל אחר. כשכבוי, גלוי רק למפקדים/אחראי תורנויות בשרשרת הפיקוד ולחייל עצמו",
        type: "boolean" as const,
        defaultValue: true,
      },
    ],
  },
  {
    label: "טלגרם",
    settings: [
      {
        key: "telegram.enabled",
        label: "טלגרם מופעל",
        description: "מפעיל או מכבה את שליחת התראות המערכת דרך בוט הטלגרם, בנוסף להתראות באפליקציה ובאימייל. כיבוי גם מסתיר את כל ממשק הטלגרם במערכת.",
        type: "boolean",
        defaultValue: false,
      },
    ],
  },
  {
    label: "דף הבית",
    settings: [
      { key: "home.mitvahim_validity_days", label: "תוקף מטווחים (ימים)", description: "מספר ימים שמטווחים בתוקף לאחר ביצוע", type: "number", defaultValue: 180 },
      { key: "home.mitvahim_warn_days", label: "אזהרה לפני פקיעת מטווחים (ימים)", description: "כמה ימים לפני פקיעת המטווחים תופיע אזהרה בדף הבית", type: "number", defaultValue: 30 },
      { key: "home.alal_validity_days", label: 'תוקף אל"ל (ימים)', description: 'מספר ימים שאל"ל בתוקף לאחר ביצוע', type: "number", defaultValue: 90 },
      { key: "home.alal_warn_days", label: 'אזהרה לפני פקיעת אל"ל (ימים)', description: 'כמה ימים לפני פקיעת האל"ל תופיע אזהרה בדף הבית', type: "number", defaultValue: 30 },
      {
        key: "alerts.upcoming_duty_days",
        label: "ימי הקדמה להתראת תורנות",
        description: "כמה ימים לפני תורנות תוצג התראה (0 = ללא התראה)",
        type: "number" as const,
        defaultValue: 3,
      },
    ],
  },
  {
    label: "מטווחים",
    settings: [
      {
        key: "mitvachim.enabled",
        label: "הפעלת תת-מערכת מטווחים",
        description: "מפעיל/מכבה את כל תת-המערכת הניסיונית של מטווחים ואל\"ל.",
        type: "boolean" as const,
        defaultValue: false,
      },
      {
        key: "mitvachim.laser_validity_days",
        label: "תוקף מטווח לייזר (ימים)",
        type: "number" as const,
        defaultValue: 180,
      },
      {
        key: "mitvachim.live_validity_days",
        label: "תוקף מטווח חי (ימים)",
        type: "number" as const,
        defaultValue: 365,
      },
      {
        key: "mitvachim.alal_validity_days",
        label: "תוקף אלל (ימים)",
        type: "number" as const,
        defaultValue: 365,
      },
      {
        key: "mitvachim.attendance_edit_min_level",
        label: "רמת היררכיה מינימלית לעריכת נוכחות",
        description: "אחראי תורנויות ברמה זו ומעלה בלבד יכולים לערוך/לתקן רישומי נוכחות במטווח.",
        type: "text" as const,
        defaultValue: "ענף",
      },      {
        key: "mitvachim.reminder_days_before",
        label: "כמה ימים מראש לשלוח תזכורת למטווח",
        description: "מספר הימים לפני המטווח שבהם תישלח תזכורת חד-פעמית",
        type: "number" as const,
        defaultValue: 3,
      },
      {
        key: "weapon_qualification.enforce_eligibility",
        label: "אכיפת כשירות נשק לתורנויות",
        description: "בודק שלחיילים המשובצים לתורנויות הדורשות נשק יש הכשרת מטווח בתוקף (נוכחית או עתידית מתוזמנת) בתאריך התורנות.",
        type: "boolean" as const,
        defaultValue: true,
      },
      {
        key: "weapon_qualification.pending_excusal_disqualifies",
        label: "בקשת פטור ממתינה פוסלת מטווח עתידי",
        description: "כאשר דלוק: מטווח עתידי עם בקשת פטור שטרם הוכרעה לא ייחשב כמעניק כשירות. כאשר כבוי: רק בקשת פטור מאושרת פוסלת.",
        type: "boolean" as const,
        defaultValue: true,
      },

    ],
  },
  {
    label: "שקיפות",
    settings: [
      {
        key: "transparency.min_visible_level",
        label: "החל ממפקדים/אחראי תורנויות באיזה דרג ניתן לראות נתוני שקיפות במערכת",
        type: "select" as const,
        defaultValue: "מדור",
      },
      {
        key: "transparency.commander_levels_above",
        label: "כמה דרגים מעל תחום הפיקוד יכול מפקד לראות (לצורך השוואה)",
        type: "number" as const,
        defaultValue: 0,
      },
      {
        key: "transparency.duty_manager_levels_above",
        label: "כמה דרגים מעל תחום האחריות יכול אחראי תורנויות לראות (לצורך השוואה)",
        type: "number" as const,
        defaultValue: 0,
      },
    ],
  },
];

// ── Changelog tab content ─────────────────────────────────────────────────────

export function ChangelogContent() {
  return (
    <div className="p-4 max-w-3xl prose prose-sm dark:prose-invert" dir="ltr">
      <ReactMarkdown
        components={{
          h1: ({ children }) => <h1 className="text-lg font-bold text-gray-900 dark:text-gray-100 mt-4 mb-2">{children}</h1>,
          h2: ({ children }) => <h2 className="text-base font-bold text-gray-900 dark:text-gray-100 mt-5 mb-1 border-b border-gray-200 dark:border-gray-600 pb-1">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold text-indigo-700 dark:text-indigo-400 mt-3 mb-1">{children}</h3>,
          p: ({ children }) => <p className="text-sm text-gray-600 dark:text-gray-400 my-1">{children}</p>,
          ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 text-sm text-gray-700 dark:text-gray-300 my-1">{children}</ul>,
          li: ({ children }) => <li className="text-sm">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-gray-800 dark:text-gray-200">{children}</strong>,
          hr: () => <hr className="border-gray-200 dark:border-gray-600 my-4" />,
          code: ({ children }) => <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded text-xs">{children}</code>,
        }}
      >
        {changelogRaw}
      </ReactMarkdown>
    </div>
  );
}

function resolveValue(map: SettingsMap, def: SettingDef): string | number | boolean | string[] {
  const raw = map[def.key];
  if (raw === undefined || raw === null) return def.defaultValue;
  if (def.type === "boolean") return Boolean(raw);
  if (def.type === "number") return Number(raw);
  return String(raw);
}

export function SystemSettingsContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: queryKeys.systemSettings(), queryFn: getSystemSettings });
  const settings = settingsQuery.data ?? {};
  const { levelTypes } = useLevelTypes();
  const hierarchyLevelOptions = [
    { value: "", label: "ללא הגבלה" },
    ...levelTypes.map(lt => ({ value: lt.key, label: lt.label })),
  ];
  // A minimum level must always be set, so unlike hierarchyLevelOptions above,
  // this one has no "no restriction" entry. Shared by every "minimum level"
  // setting (commander exemption grants, medical document view thresholds).
  const commanderExemptionLevelOptions = levelTypes.map(lt => ({ value: lt.key, label: lt.label }));
  // "Every soldier" is the most permissive option for the transparency minimum
  // visible level, so it is offered in addition to the configured hierarchy
  // levels (unlike the commander-exemption lists above).
  const transparencyMinVisibleLevelOptions = [
    { value: "every_soldier", label: "כל חייל" },
    ...levelTypes.map(lt => ({ value: lt.key, label: lt.label })),
  ];
  const MIN_LEVEL_SETTING_KEYS = new Set([
    "exemptions.commander_exemption_min_level",
    "exemptions.commander_escalation_min_level",
    "exemptions.medical_doc_min_commander_level",
    "exemptions.medical_doc_min_duty_manager_level",
    "soldiers.commander_delete_min_level",
  ]);

  // draft mirrors the query result but is then edited locally before saving,
  // so it stays a useState fed by an effect rather than reading straight from
  // the query on every render (same pattern as ProfilePage's notification prefs).
  const [draft, setDraft] = useState<SettingsMap>({});
  const [saved, setSaved] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (settingsQuery.data) setDraft(settingsQuery.data);
  }, [settingsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: updateSystemSettings,
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.systemSettings() });
      setDraft(updated);
      setSaved(true);
    },
  });

  const importMutation = useMutation({
    mutationFn: importSystemSettings,
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.systemSettings() });
      setDraft(updated);
      setSaved(true);
      setImportError(null);
    },
    onError: () => {
      setImportError("שגיאה בייבוא ההגדרות");
    },
  });

  async function handleExport() {
    const data = await exportSystemSettings();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "הגדרות-מערכת.json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function handleImportFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as SettingsMap;
        importMutation.mutate(parsed);
      } catch {
        setImportError("קובץ לא תקין");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  }

  function setValue(key: string, value: string | number | boolean | string[]) {
    setDraft(prev => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  function handleSave() {
    saveMutation.mutate(draft);
  }

  const saving = saveMutation.isPending;
  const error = saveMutation.isError
    ? "שגיאה בשמירת ההגדרות"
    : settingsQuery.isError
      ? "שגיאה בטעינת ההגדרות"
      : null;

  const isDirty = JSON.stringify(draft) !== JSON.stringify(settings);

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t("system_settings.title")}</h1>
        <div className="flex items-center gap-3">
          {saved && <span className="text-sm text-green-600">נשמר ✓</span>}
          <button
            type="button"
            onClick={handleExport}
            className="text-sm text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600 px-3 py-1.5 rounded hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-1.5"
          >
            <Download className="w-4 h-4" />
            ייצוא הגדרות
          </button>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={importMutation.isPending}
            className="text-sm text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600 px-3 py-1.5 rounded hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-1.5 disabled:opacity-50"
          >
            <Upload className="w-4 h-4" />
            {importMutation.isPending ? "מייבא..." : "ייבוא הגדרות"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json"
            className="hidden"
            onChange={handleImportFileChange}
          />
          <button
            onClick={handleSave}
            disabled={saving || !isDirty}
            className="bg-indigo-600 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
          >
            {saving ? "שומר..." : t("system_settings.save")}
          </button>
        </div>
      </div>

      {error && <div className="text-red-600 text-sm bg-red-50 rounded p-3">{error}</div>}
      {importError && <div className="text-red-600 text-sm bg-red-50 rounded p-3">{importError}</div>}

      {SETTING_GROUPS.map(group => (
        <Fragment key={group.label}>
        <div className="bg-white rounded-lg shadow p-5 space-y-4 dark:bg-gray-800">
          <h2 className="font-semibold text-gray-700 border-b pb-2 dark:text-gray-200 dark:border-gray-600">{group.label}</h2>
          {group.settings.map(def => {
            const value = resolveValue(draft, def);
            return (
              <div key={def.key} className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-800 dark:text-gray-100">
                    {def.key === "constraints.reset_period"
                      ? t("admin_settings.constraints_reset_period")
                      : def.label}
                  </div>
                  {def.description && <div className="text-xs text-gray-400 dark:text-gray-300 mt-0.5">{def.description}</div>}
                </div>
                <div className="flex-shrink-0">
                  {def.type === "boolean" ? (
                    <button
                      dir="ltr"
                      onClick={() => setValue(def.key, !value)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${value ? "bg-indigo-600" : "bg-gray-300 dark:bg-gray-600"}`}
                      aria-pressed={Boolean(value)}
                    >
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white dark:bg-gray-200 transition-transform ${value ? "translate-x-6" : "translate-x-1"}`} />
                    </button>
                  ) : def.type === "select" ? (
                    <select
                      value={String(value ?? def.defaultValue)}
                      onChange={(e) => setValue(def.key, e.target.value)}
                      className="border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1 text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-indigo-300 outline-none"
                      dir="rtl"
                    >
                      {(def.key === "transparency.min_visible_level"
                        ? transparencyMinVisibleLevelOptions
                        : def.key === "swaps.restrict_to_hierarchy_level"
                        ? hierarchyLevelOptions
                        : MIN_LEVEL_SETTING_KEYS.has(def.key)
                        ? commanderExemptionLevelOptions
                        : def.options ?? []
                      ).map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  ) : def.type === "date" ? (
                    <DateInput
                      value={String(value ?? "")}
                      onChange={isoValue => setValue(def.key, isoValue)}
                      className="border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1 text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-indigo-300 outline-none"
                    />
                  ) : def.type === "text" ? (
                    <input
                      type="text"
                      value={String(value ?? "")}
                      onChange={e => setValue(def.key, e.target.value)}
                      className="w-40 border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1 text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-indigo-300 outline-none"
                      dir="ltr"
                    />
                  ) : (
                    <input
                      type="number"
                      step={def.type === "decimal" ? "0.01" : "1"}
                      min="0"
                      value={String(value)}
                      onChange={e => setValue(def.key, def.type === "decimal" ? e.target.value : Number(e.target.value))}
                      className="w-28 border rounded px-2 py-1 text-sm text-right dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                      dir="ltr"
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {group.label === "עליית דרגה" && <RankAdvancementIntervalsSection />}
        </Fragment>
      ))}
    </div>
  );
}

// ── Rank advancement intervals ──────────────────────────────────────────────
// months_to_next per rank/track is a list of rows, not a single value, so it
// doesn't fit the flat SettingDef shape above — it gets its own small table UI
// with its own draft/isDirty/save-mutation state, following the same pattern
// as the generic settings draft but keyed by "track:rank" instead of a
// settings key.
const TRACK_LABELS: Record<RankTrack, string> = {
  enlisted: "חיילים",
  officer: "קצינים",
  officer_academic: "קצינים אקדמאים",
};
const TRACKS = ["enlisted", "officer", "officer_academic"] as const;

interface DraftEntry {
  months_to_next: number | "";
  advance_on_career_entry: boolean;
}

function draftKey(track: RankTrack, rank: string): string {
  return `${track}:${rank}`;
}

function RankAdvancementIntervalsSection() {
  const queryClient = useQueryClient();
  const ladderQuery = useQuery({ queryKey: queryKeys.rankLadder(), queryFn: getRankLadder });

  const [draft, setDraft] = useState<Record<string, DraftEntry>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!ladderQuery.data) return;
    const next: Record<string, DraftEntry> = {};
    for (const track of TRACKS) {
      for (const entry of ladderQuery.data[track]) {
        next[draftKey(track, entry.rank)] = {
          months_to_next: entry.months_to_next ?? "",
          advance_on_career_entry: entry.advance_on_career_entry,
        };
      }
    }
    setDraft(next);
  }, [ladderQuery.data]);

  const saveMutation = useMutation({
    mutationFn: updateRankAdvancementIntervals,
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.rankLadder(), updated);
      setSaved(true);
    },
  });

  function setMonthsValue(track: RankTrack, rank: string, raw: string) {
    setDraft(prev => ({
      ...prev,
      [draftKey(track, rank)]: {
        ...prev[draftKey(track, rank)],
        months_to_next: raw === "" ? "" : Number(raw),
      },
    }));
    setSaved(false);
  }

  function setCareerEntryValue(track: RankTrack, rank: string, checked: boolean) {
    setDraft(prev => ({
      ...prev,
      [draftKey(track, rank)]: {
        ...prev[draftKey(track, rank)],
        advance_on_career_entry: checked,
      },
    }));
    setSaved(false);
  }

  function handleSave() {
    if (!ladderQuery.data) return;
    const intervals: RankIntervalUpdate[] = TRACKS.flatMap(track =>
      ladderQuery.data![track].map(entry => {
        const draftEntry = draft[draftKey(track, entry.rank)];
        return {
          track,
          rank: entry.rank,
          months_to_next: !draftEntry || draftEntry.months_to_next === "" ? null : Number(draftEntry.months_to_next),
          advance_on_career_entry: draftEntry?.advance_on_career_entry ?? false,
        };
      }),
    );
    saveMutation.mutate(intervals);
  }

  const serverDraft: Record<string, DraftEntry> = {};
  if (ladderQuery.data) {
    for (const track of TRACKS) {
      for (const entry of ladderQuery.data[track]) {
        serverDraft[draftKey(track, entry.rank)] = {
          months_to_next: entry.months_to_next ?? "",
          advance_on_career_entry: entry.advance_on_career_entry,
        };
      }
    }
  }
  const isDirty = JSON.stringify(draft) !== JSON.stringify(serverDraft);
  const saving = saveMutation.isPending;
  const error = saveMutation.isError
    ? "שגיאה בשמירת מרווחי עליית דרגה"
    : ladderQuery.isError
      ? "שגיאה בטעינת סולם הדרגות"
      : null;

  return (
    <div className="bg-white rounded-lg shadow p-5 space-y-4 dark:bg-gray-800">
      <div className="flex items-center justify-between border-b pb-2 dark:border-gray-600">
        <h2 className="font-semibold text-gray-700 dark:text-gray-200">מרווחי עליית דרגה</h2>
        <div className="flex items-center gap-3">
          {saved && !isDirty && <span className="text-sm text-green-600">נשמר ✓</span>}
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !isDirty || !ladderQuery.data}
            className="bg-indigo-600 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
          >
            {saving ? "שומר..." : "שמור"}
          </button>
        </div>
      </div>

      <p className="text-xs text-gray-400 dark:text-gray-300">
        מספר החודשים הנדרש בכל דרגה לפני קידום אוטומטי לדרגה הבאה. השאירו ריק כדי שדרגה לא תקודם אוטומטית.
      </p>

      {error && <div role="alert" className="text-red-600 text-sm bg-red-50 rounded p-3">{error}</div>}

      {TRACKS.map(track => (
        <div key={track}>
          <h3 className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-2">{TRACK_LABELS[track]}</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 dark:text-gray-400 text-xs">
                <th className="text-right py-1 font-normal">דרגה</th>
                <th className="text-right py-1 font-normal">חודשים לדרגה הבאה</th>
                <th className="text-right py-1 font-normal">
                  <span className="inline-flex items-center gap-1">
                    קידום עם כניסה לקבע
                    <span title="אם מסומן, החייל יקודם אוטומטית לדרגה הבאה ברגע שהוא נכנס לשירות קבע, גם אם התאריך המתוכנן לקידום לדרגה זו עדיין לא הגיע.">
                      <HelpCircle size={14} className="text-gray-400" />
                    </span>
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(ladderQuery.data?.[track] ?? []).map(entry => (
                <tr key={entry.rank} className="border-t dark:border-gray-700">
                  <td className="py-1 text-gray-800 dark:text-gray-100">{entry.rank}</td>
                  <td className="py-1">
                    <input
                      type="number"
                      min="1"
                      value={String(draft[draftKey(track, entry.rank)]?.months_to_next ?? "")}
                      onChange={e => setMonthsValue(track, entry.rank, e.target.value)}
                      className="w-28 border rounded px-2 py-1 text-sm text-right dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                      dir="ltr"
                    />
                  </td>
                  <td className="py-1">
                    <input
                      type="checkbox"
                      checked={draft[draftKey(track, entry.rank)]?.advance_on_career_entry ?? false}
                      onChange={e => setCareerEntryValue(track, entry.rank, e.target.checked)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

export default function SystemSettingsPage() {
  return <Layout><SystemSettingsContent /></Layout>;
}
