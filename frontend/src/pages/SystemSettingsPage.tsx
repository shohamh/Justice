import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Upload } from "lucide-react";
import Layout from "../components/Layout";
import { getSystemSettings, updateSystemSettings, exportSystemSettings, importSystemSettings, SettingsMap } from "../api/systemSettings";
import ReactMarkdown from "react-markdown";
import changelogRaw from "../../CHANGELOG.md?raw";
import { queryKeys } from "../queryKeys";
import { useLevelTypes } from "../hooks/useLevelTypes";
import DateInput from "../components/DateInput";

interface SettingDef {
  key: string;
  label: string;
  description?: string;
  type: "boolean" | "number" | "decimal" | "select" | "date" | "text" | "multiselect";
  defaultValue: string | number | boolean | string[];
  options?: { value: string; label: string }[];
}

const SETTING_GROUPS: { label: string; settings: SettingDef[] }[] = [
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
      { key: "constraints.require_manager_approval", label: "דורש אישור מפקד", description: "האם בקשות אילוץ דורשות אישור מפקד", type: "boolean", defaultValue: true },
    ],
  },
  {
    label: "החלפות",
    settings: [
      { key: "swaps.require_manager_approval", label: "דורש אישור מפקד", description: "האם החלפות דורשות אישור מפקד", type: "boolean", defaultValue: true },
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
    label: "שקיפות",
    settings: [
      {
        key: "transparency.visible_commander_levels",
        label: "",
        type: "multiselect" as const,
        defaultValue: [],
      },
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
    label: "כשירות",
    settings: [
      { key: "eligibility.mitvahim_months", label: "חודשים מאז מטווח אחרון", description: "מספר חודשים מרבי מאז מטווח אחרון לצורך כשירות", type: "number", defaultValue: 6 },
      { key: "eligibility.alal_months", label: 'חודשים מאז אל"ל אחרון', description: 'מספר חודשים מרבי מאז אל"ל אחרון לצורך כשירות', type: "number", defaultValue: 3 },
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
    label: "הוגנות אלגוריתם",
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
    label: "מגבלות צפיפות (אלגוריתם)",
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
    label: "פירוק וקבוצות (אלגוריתם)",
    settings: [
      { key: "algorithm.batching_enabled", label: "פירוק וקבוצות", description: "פירוק כל הרצה לקבוצות כשירות בלתי-תלויות ולקבוצות כרונולוגיות, כדי לשמור על הוגנות מדויקת (L1) גם בהרצות גדולות. כבה כדי לפתור את כל הבעיה בבת אחת.", type: "boolean", defaultValue: true },
      { key: "algorithm.batch_size", label: "גודל קבוצה (תורנויות)", description: "מספר התורנויות המרבי בקבוצה כרונולוגית אחת. קטן יותר = מהיר יותר אך גרידי יותר.", type: "number", defaultValue: 50 },
      { key: "algorithm.batch_time_limit_seconds", label: "מגבלת זמן לקבוצה (שניות)", description: "תקציב זמן הפותר לכל קבוצה.", type: "number", defaultValue: 120 },
    ],
  },
  {
    label: "משמרות",
    settings: [
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
    label: "טלגרם",
    settings: [
      {
        key: "telegram.enabled",
        label: "טלגרם מופעל",
        description: "כיבוי מסתיר את כל ממשק הטלגרם ומפסיק שליחת התראות דרכו",
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
    ],
  },
  {
    label: "התראות",
    settings: [
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
    label: "פטורים",
    settings: [
      {
        key: "exemptions.require_rasn_approver",
        label: "מאשר פטורים — דרג רסן ומעלה בלבד",
        description: "אם מסומן, רק מפקדים בדרג רסן ומעלה יוכלו לאשר פטורים (בנוסף למנהלי תורניות)",
        type: "boolean" as const,
        defaultValue: false,
      },
      {
        key: "exemptions.commander_exemption_min_level",
        label: "החל מאיזו רמת פיקוד ניתן להעניק פטור פיקודי",
        description: "מפקד ברמה זו ומעלה (קרוב יותר לשורש) יכול להעניק פטור פיקודי, גם ללא דרגת קצונה מתאימה",
        type: "select" as const,
        defaultValue: "מדור",
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
        defaultValue: "מרכז",
        options: [],
      },
    ],
  },
  {
    label: "הקפצה פיקודית",
    settings: [
      { key: "forced_callup.enabled", label: "הקפצה פיקודית מופעלת", description: "כיבוי מסתיר את דף ההקפצה הפיקודית ומבטל את כל הפעולות הקשורות אליה", type: "boolean" as const, defaultValue: true },
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
        key: "duty.default_rest_hours",
        label: "שעות מנוחה בסיסיות בין תורנויות",
        description: "מספר שעות המנוחה המינימלי הנדרש לחייל בין סיום תורנות אחת לתחילת הבאה. ניתן לשנות פר-סוג תורנות.",
        type: "number" as const,
        defaultValue: 12,
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
  if (def.type === "multiselect") return Array.isArray(raw) ? raw : [];
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
  const MIN_LEVEL_SETTING_KEYS = new Set([
    "exemptions.commander_exemption_min_level",
    "exemptions.medical_doc_min_commander_level",
    "exemptions.medical_doc_min_duty_manager_level",
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
        <div key={group.label} className="bg-white rounded-lg shadow p-5 space-y-4 dark:bg-gray-800">
          <h2 className="font-semibold text-gray-700 border-b pb-2 dark:text-gray-200 dark:border-gray-600">{group.label}</h2>
          {group.settings.map(def => {
            const value = resolveValue(draft, def);
            return (
              <div key={def.key} className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-800 dark:text-gray-100">
                    {def.key === "transparency.visible_commander_levels"
                      ? t("admin_settings.transparency_visible_levels")
                      : def.key === "constraints.reset_period"
                        ? t("admin_settings.constraints_reset_period")
                        : def.label}
                  </div>
                  {def.description && <div className="text-xs text-gray-400 dark:text-gray-300 mt-0.5">{def.description}</div>}
                </div>
                <div className="flex-shrink-0">
                  {def.type === "multiselect" ? (
                    <div className="flex flex-col gap-1 max-h-40 overflow-y-auto" dir="rtl">
                      {levelTypes.map((lt) => {
                        const selected = Array.isArray(value) && value.includes(lt.key);
                        return (
                          <label key={lt.id} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                            <input
                              type="checkbox"
                              checked={selected}
                              onChange={(e) => {
                                const current = Array.isArray(value) ? value : [];
                                const next = e.target.checked
                                  ? [...current, lt.key]
                                  : current.filter((k) => k !== lt.key);
                                setValue(def.key, next);
                              }}
                            />
                            {lt.label}
                          </label>
                        );
                      })}
                      {levelTypes.length === 0 && (
                        <span className="text-xs text-gray-400">{t("admin_settings.transparency_no_level_types")}</span>
                      )}
                    </div>
                  ) : def.type === "boolean" ? (
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
                      {(def.key === "swaps.restrict_to_hierarchy_level"
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
      ))}

    </div>
  );
}

export default function SystemSettingsPage() {
  return <Layout><SystemSettingsContent /></Layout>;
}
