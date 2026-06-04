import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { SettingsMap } from "../../api/systemSettings";

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
  return `${label} פג תוקף בעוד ${daysLeft} ימים (${expiry.toLocaleDateString("he-IL")})`;
}

export default function AlertBanners({ lastMitvahimDate, lastAlalDate, settings }: Props) {
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

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
  if (visible.length === 0) return null;

  return (
    <div className="space-y-2 mb-4" dir="rtl">
      {visible.map((a) => (
        <div
          key={a.key}
          className="flex items-center justify-between bg-amber-50 border border-amber-300 rounded-lg px-4 py-3 cursor-pointer hover:bg-amber-100"
          onClick={() => navigate("/profile")}
          role="alert"
          data-testid={`alert-banner-${a.key}`}
        >
          <span className="text-sm text-amber-800 font-medium">⚠️ {a.message}</span>
          <button
            className="text-amber-500 hover:text-amber-700 text-lg leading-none ml-4"
            onClick={(e) => { e.stopPropagation(); setDismissed((prev) => new Set([...prev, a.key])); }}
            aria-label="סגור"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
