import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Fuse from "fuse.js";
import { DeputyDTO, createDeputy, listDeputies, revokeDeputy } from "../api/deputies";
import { SoldierDTO, listSoldiers } from "../api/soldiers";
import DateInput from "./DateInput";
import { translateApiError } from "../utils/translateApiError";
import ConfirmDialog from "./ConfirmDialog";

interface Props {
  principalId: string;
  principalRoles: { isCommander: boolean; isDutyManager: boolean };
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function statusOf(g: DeputyDTO, today: string): "active" | "future" | "expired" {
  if (g.end_date < today) return "expired";
  if (g.start_date > today) return "future";
  return "active";
}

export default function DeputiesPanel({ principalId, principalRoles }: Props) {
  const { t } = useTranslation();
  const [grants, setGrants] = useState<DeputyDTO[]>([]);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [selectedDeputyId, setSelectedDeputyId] = useState("");
  const [searchText, setSearchText] = useState("");
  const [open, setOpen] = useState(false);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const [role, setRole] = useState<"commander" | "duty_manager">(
    principalRoles.isCommander ? "commander" : "duty_manager"
  );
  const [startDate, setStartDate] = useState(todayIso());
  const [endDate, setEndDate] = useState(todayIso());
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const bothRoles = principalRoles.isCommander && principalRoles.isDutyManager;

  async function refresh() {
    setGrants(await listDeputies(principalId));
  }

  useEffect(() => {
    void refresh();
    void listSoldiers().then(setSoldiers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [principalId]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const fuse = useMemo(
    () => new Fuse(soldiers, { keys: ["full_name", "personal_number"], threshold: 0.4 }),
    [soldiers]
  );
  const filtered = searchText ? fuse.search(searchText).map((r) => r.item).slice(0, 20) : soldiers.slice(0, 20);

  async function handleAdd() {
    if (!selectedDeputyId) return;
    setError(null);
    try {
      await createDeputy({
        principal_id: principalId, deputy_id: selectedDeputyId, role,
        start_date: startDate, end_date: endDate,
      });
      setSelectedDeputyId("");
      setSearchText("");
      await refresh();
    } catch (err) {
      setError(translateApiError(err, t, t("errors.generic", "שגיאה")));
    }
  }

  async function handleRevoke(id: string) {
    await revokeDeputy(id);
    await refresh();
  }

  const today = todayIso();

  return (
    <div className="space-y-3" dir="rtl">
      <h4 className="font-semibold text-sm">{t("deputies.title", "ממלאי מקום")}</h4>

      {!(open && filtered.length > 0) && (grants.length === 0 ? (
        <p className="text-xs text-gray-500 dark:text-gray-400">{t("deputies.no_deputies", "אין ממלאי מקום מוגדרים")}</p>
      ) : (
        <ul className="space-y-1">
          {grants.map((g) => {
            const s = statusOf(g, today);
            const badgeKey = s === "active" ? "deputies.active_badge" : s === "future" ? "deputies.future_badge" : "deputies.expired_badge";
            const badgeText = s === "active" ? "פעיל" : s === "future" ? "עתידי" : "פג תוקף";
            return (
              <li key={g.id} className="flex items-center justify-between text-sm border-b dark:border-gray-600 py-1">
                <span>
                  {g.deputy_name}{" "}
                  <span className="text-xs text-gray-400">
                    ({g.role === "commander" ? t("deputies.role_commander", "מפקד") : t("deputies.role_duty_manager", "אחראי תורנויות")}, {g.start_date} — {g.end_date})
                  </span>{" "}
                  <span className="text-xs">{t(badgeKey, badgeText)}</span>
                </span>
                {s !== "expired" && (
                  <button type="button" onClick={() => setRevokeId(g.id)} className="text-red-600 text-xs hover:underline">
                    {t("deputies.revoke", "הסר")}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ))}

      <div className="flex flex-wrap gap-2 items-end pt-2 border-t dark:border-gray-600">
        <div ref={containerRef} className="relative">
          <input
            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={searchText}
            onChange={(e) => { setSearchText(e.target.value); setSelectedDeputyId(""); setOpen(true); }}
            onFocus={() => setOpen(true)}
            placeholder={t("deputies.search_soldier_placeholder", "חיפוש חייל...")}
            autoComplete="off"
          />
          {open && filtered.length > 0 && (
            <ul className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-700 border dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto">
              {filtered.map((s) => (
                <li
                  key={s.id}
                  className="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 dark:text-gray-100"
                  onClick={() => { setSelectedDeputyId(s.id); setSearchText(`${s.full_name} (${s.personal_number})`); setOpen(false); }}
                >
                  {s.full_name} <span className="text-gray-400 text-xs">({s.personal_number})</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {bothRoles && (
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500" htmlFor="deputy-role-select">{t("deputies.role_label", "תפקיד")}</label>
            <select
              id="deputy-role-select"
              value={role}
              onChange={(e) => setRole(e.target.value as "commander" | "duty_manager")}
              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            >
              <option value="commander">{t("deputies.role_commander", "מפקד")}</option>
              <option value="duty_manager">{t("deputies.role_duty_manager", "אחראי תורנויות")}</option>
            </select>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500" htmlFor="deputy-start-date">{t("deputies.start_date", "מתאריך")}</label>
          <DateInput id="deputy-start-date" className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={startDate} onChange={setStartDate} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500" htmlFor="deputy-end-date">{t("deputies.end_date", "עד תאריך")}</label>
          <DateInput id="deputy-end-date" className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={endDate} onChange={setEndDate} min={startDate} />
        </div>

        <button
          type="button"
          onClick={() => void handleAdd()}
          disabled={!selectedDeputyId}
          className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm hover:bg-indigo-700 disabled:opacity-50"
        >
          {t("deputies.add", "הוסף ממלא מקום")}
        </button>
      </div>
      {error && <p className="text-red-500 text-xs">{error}</p>}
      <ConfirmDialog
        open={revokeId !== null}
        title={t("deputies.revoke_title", "הסרת ממלא מקום")}
        message={t("deputies.revoke_confirm", "להסיר את ממלא המקום?")}
        danger
        onClose={() => setRevokeId(null)}
        onConfirm={() => {
          const id = revokeId;
          setRevokeId(null);
          if (id) void handleRevoke(id);
        }}
      />
    </div>
  );
}
