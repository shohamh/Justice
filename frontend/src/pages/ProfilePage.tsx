import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import ExemptionsPanel from "../components/ExemptionsPanel";
import { useAuth } from "../auth/AuthContext";
import {
  FieldUpdateDTO,
  submitFieldUpdate,
  listFieldUpdates,
} from "../api/soldiers";

export default function ProfilePage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [fieldUpdates, setFieldUpdates] = useState<FieldUpdateDTO[]>([]);
  const [mitvahimReq, setMitvahimReq] = useState("");
  const [alalReq, setAlalReq] = useState("");

  useEffect(() => {
    if (user) {
      void (async () => {
        const updates = await listFieldUpdates(user.id);
        setFieldUpdates(updates);
      })();
    }
  }, [user]);

  async function requestUpdate(field: string, value: string) {
    if (!user || !value) return;
    try {
      await submitFieldUpdate(user.id, field, value);
      const updated = await listFieldUpdates(user.id);
      setFieldUpdates(updated);
      if (field === "last_mitvahim_date") setMitvahimReq("");
      if (field === "last_alal_date") setAlalReq("");
    } catch {
      // submission failed silently — backend returns error detail
    }
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-3">
        <h2 className="text-xl font-semibold">{t("profile.title")}</h2>
        <p>{t("team.full_name")}: {user?.full_name}</p>
        <p>{t("team.personal_number")}: {user?.personal_number}</p>
        <p>{t("team.role")}: {user?.role}</p>
        <Link to="/change-password" className="text-indigo-600 hover:text-indigo-800" data-testid="profile-change-password">
          {t("profile.change_password")}
        </Link>
        {user?.id && (
          <div className="pt-4 border-t">
            <ExemptionsPanel soldierId={user.id} canManage={false} />
          </div>
        )}
      </section>

      <section className="bg-white rounded-lg shadow p-6 mt-4 space-y-4" dir="rtl">
        <h3 className="text-lg font-semibold">{t("soldier_profile.section_title")}</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          {user?.rank && <div><span className="font-medium">{t("soldier_profile.rank")}:</span> {user.rank}</div>}
          {user?.is_officer !== null && user?.is_officer !== undefined && (
            <div>
              <span className="font-medium">{t("soldier_profile.is_officer")}:</span>{" "}
              {user.is_officer ? t("soldier_profile.is_officer") : t("soldier_profile.is_enlisted")}
            </div>
          )}
          {user?.last_mitvahim_date && (
            <div><span className="font-medium">{t("soldier_profile.last_mitvahim_date")}:</span> {user.last_mitvahim_date}</div>
          )}
          {user?.last_alal_date && (
            <div><span className="font-medium">{t("soldier_profile.last_alal_date")}:</span> {user.last_alal_date}</div>
          )}
        </div>

        <div className="space-y-2 text-sm">
          <p className="font-medium">{t("soldier_profile.submit_update")}</p>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.last_mitvahim_date")}</label>
            <input type="date" value={mitvahimReq} onChange={e => setMitvahimReq(e.target.value)} className="border rounded p-1 text-sm" />
            <button
              type="button"
              onClick={() => requestUpdate("last_mitvahim_date", mitvahimReq)}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.last_alal_date")}</label>
            <input type="date" value={alalReq} onChange={e => setAlalReq(e.target.value)} className="border rounded p-1 text-sm" />
            <button
              type="button"
              onClick={() => requestUpdate("last_alal_date", alalReq)}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
        </div>

        {fieldUpdates.filter(u => u.status === "pending").length > 0 && (
          <div className="text-xs text-amber-600">
            {fieldUpdates.filter(u => u.status === "pending").length} {t("soldier_profile.update_pending")}
          </div>
        )}
      </section>
    </Layout>
  );
}
