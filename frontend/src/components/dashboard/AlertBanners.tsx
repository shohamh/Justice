import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { SettingsMap, getSystemSettings } from "../../api/systemSettings";
import { formatDate } from "../../utils/formatDate";
import { listEffectiveDuties, EffectiveDuty } from "../../api/assignments";
import { useAuth } from "../../auth/AuthContext";

interface Props {
  lastMitvahimDate: string | null;
  lastAlalDate: string | null;
  settings: SettingsMap;
}

function getNum(settings: SettingsMap, key: string, fallback: number): number {
  const v = settings[key];
  return v != null ? Number(v) : fallback;
}

function alertMessage(
  lastDateStr: string | null,
  validityDays: number,
  warnDays: number,
  label: string
): string | null {
  if (!lastDateStr) return `תאריך ${label} לא מעודכן`;
  const expiry = new Date(lastDateStr);
  expiry.setDate(expiry.getDate() + validityDays);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const daysLeft = Math.floor((expiry.getTime() - today.getTime()) / 86_400_000);
  if (daysLeft > warnDays) return null;
  if (daysLeft <= 0) return `${label} פג תוקף`;
  return `${label} פג תוקף בעוד ${daysLeft} ימים (${formatDate(expiry)})`;
}

function daysUntil(dateStr: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateStr);
  target.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86400000);
}

function dayOfWeekHe(dateStr: string): string {
  const days = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"];
  return "יום " + days[new Date(dateStr).getDay()];
}

function formatDaysUntil(days: number, t: TFunction): string {
  if (days === 0) return t("upcoming_duty_alert.today");
  if (days === 1) return t("upcoming_duty_alert.tomorrow");
  if (days === 2) return t("upcoming_duty_alert.day_after");
  return t("upcoming_duty_alert.in_days", { count: days });
}

export default function AlertBanners({ lastMitvahimDate, lastAlalDate, settings }: Props) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [upcomingAlerts, setUpcomingAlerts] = useState<{ duty: EffectiveDuty; days: number }[]>([]);

  useEffect(() => {
    if (!user) return;
    void (async () => {
      const [duties, fetchedSettings] = await Promise.all([
        listEffectiveDuties(user.id).catch(() => [] as EffectiveDuty[]),
        getSystemSettings().catch(() => ({} as SettingsMap)),
      ]);
      const alertDays = Number(fetchedSettings["alerts.upcoming_duty_days"] ?? 3);
      if (alertDays === 0) return;
      const alerts = duties
        .map(d => ({ duty: d, days: daysUntil(d.start_date) }))
        .filter(({ days }) => days >= 0 && days <= alertDays)
        .sort((a, b) => a.days - b.days);
      setUpcomingAlerts(alerts);
    })();
  }, [user]);

  const mitvahimValidity = getNum(settings, "home.mitvahim_validity_days", 180);
  const mitvahimWarn = getNum(settings, "home.mitvahim_warn_days", 30);
  const alalValidity = getNum(settings, "home.alal_validity_days", 90);
  const alalWarn = getNum(settings, "home.alal_warn_days", 30);

  const alerts: { key: string; message: string }[] = [];

  const mitvMsg = alertMessage(lastMitvahimDate, mitvahimValidity, mitvahimWarn, "מטווחים");
  if (mitvMsg) alerts.push({ key: "mitvahim", message: mitvMsg });

  const alalMsg = alertMessage(lastAlalDate, alalValidity, alalWarn, 'אל"ל');
  if (alalMsg) alerts.push({ key: "alal", message: alalMsg });

  const visible = alerts.filter((a) => !dismissed.has(a.key));

  if (visible.length === 0 && upcomingAlerts.length === 0) return null;

  return (
    <div className="space-y-2 mb-4" dir="rtl">
      {visible.map((a) => (
        <div
          key={a.key}
          className="flex items-center justify-between bg-amber-50 dark:bg-amber-950 border border-amber-300 dark:border-amber-700 rounded-lg px-4 py-3 cursor-pointer hover:bg-amber-100 dark:hover:bg-amber-900"
          onClick={() => navigate("/profile")}
          role="alert"
          data-testid={`alert-banner-${a.key}`}
        >
          <span className="text-sm text-amber-800 dark:text-amber-200 font-medium">⚠️ {a.message}</span>
          <button
            className="text-amber-500 hover:text-amber-700 text-lg leading-none ml-4"
            onClick={(e) => { e.stopPropagation(); setDismissed((prev) => new Set([...prev, a.key])); }}
            aria-label="סגור"
          >
            ✕
          </button>
        </div>
      ))}
      {upcomingAlerts.map(({ duty, days }) => (
        <div
          key={duty.assignment_id}
          className="flex items-start gap-3 bg-amber-50 dark:bg-amber-950 border border-amber-300 dark:border-amber-700 rounded-lg p-3 text-sm"
          dir="rtl"
        >
          <span className="text-xl flex-shrink-0">⏰</span>
          <div className="flex-1">
            <p className="font-semibold text-amber-800 dark:text-amber-200">
              {t("upcoming_duty_alert.title")} — {formatDaysUntil(days, t)}
            </p>
            <p className="text-amber-700 dark:text-amber-300 text-xs mt-0.5">
              {dayOfWeekHe(duty.start_date)} · {duty.start_date}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
