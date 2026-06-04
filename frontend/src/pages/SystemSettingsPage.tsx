import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import { getSystemSettings, updateSystemSettings, SettingsMap } from "../api/systemSettings";

interface SettingDef {
  key: string;
  label: string;
  description?: string;
  type: "boolean" | "number" | "decimal";
  defaultValue: string | number | boolean;
}

const SETTING_GROUPS: { label: string; settings: SettingDef[] }[] = [
  {
    label: "אילוצים אישיים",
    settings: [
      { key: "constraints.personal_cap_days", label: "מכסת ימי אילוץ לחייל", description: "מספר ימי האילוץ המרביים שחייל יכול לבקש", type: "number", defaultValue: 15 },
      { key: "constraints.require_manager_approval", label: "דורש אישור מפקד", description: "האם בקשות אילוץ דורשות אישור מפקד", type: "boolean", defaultValue: true },
    ],
  },
  {
    label: "החלפות",
    settings: [
      { key: "swaps.require_manager_approval", label: "דורש אישור מפקד", description: "האם החלפות דורשות אישור מפקד", type: "boolean", defaultValue: true },
    ],
  },
  {
    label: "הרשמה",
    settings: [
      { key: "registration.telegram_required", label: "טלגרם חובה", description: "האם חיילים חדשים חייבים לקשר חשבון טלגרם לאחר ההרשמה", type: "boolean", defaultValue: false },
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
    ],
  },
];

function resolveValue(map: SettingsMap, def: SettingDef): string | number | boolean {
  const raw = map[def.key];
  if (raw === undefined || raw === null) return def.defaultValue;
  if (def.type === "boolean") return Boolean(raw);
  if (def.type === "number") return Number(raw);
  return String(raw);
}

export function SystemSettingsContent() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<SettingsMap>({});
  const [draft, setDraft] = useState<SettingsMap>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSystemSettings().then(s => {
      setSettings(s);
      setDraft(s);
    }).catch(() => setError("שגיאה בטעינת ההגדרות"));
  }, []);

  function setValue(key: string, value: string | number | boolean) {
    setDraft(prev => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateSystemSettings(draft);
      setSettings(updated);
      setDraft(updated);
      setSaved(true);
    } catch {
      setError("שגיאה בשמירת ההגדרות");
    } finally {
      setSaving(false);
    }
  }

  const isDirty = JSON.stringify(draft) !== JSON.stringify(settings);

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t("system_settings.title")}</h1>
        <div className="flex items-center gap-3">
          {saved && <span className="text-sm text-green-600">נשמר ✓</span>}
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

      {SETTING_GROUPS.map(group => (
        <div key={group.label} className="bg-white rounded-lg shadow p-5 space-y-4 dark:bg-gray-800">
          <h2 className="font-semibold text-gray-700 border-b pb-2 dark:text-gray-200 dark:border-gray-600">{group.label}</h2>
          {group.settings.map(def => {
            const value = resolveValue(draft, def);
            return (
              <div key={def.key} className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-800 dark:text-gray-100">{def.label}</div>
                  {def.description && <div className="text-xs text-gray-400 dark:text-gray-300 mt-0.5">{def.description}</div>}
                </div>
                <div className="flex-shrink-0">
                  {def.type === "boolean" ? (
                    <button
                      dir="ltr"
                      onClick={() => setValue(def.key, !value)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${value ? "bg-indigo-600" : "bg-gray-200"}`}
                      aria-pressed={Boolean(value)}
                    >
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${value ? "translate-x-6" : "translate-x-1"}`} />
                    </button>
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
