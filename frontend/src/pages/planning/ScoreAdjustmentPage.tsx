import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { createAdjustment, listAdjustments, ScoreAdjustment } from "../../api/scoreAdjustments";
import { listSoldiers, SoldierDTO } from "../../api/soldiers";

export default function ScoreAdjustmentPage() {
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [adjustments, setAdjustments] = useState<ScoreAdjustment[]>([]);
  const [soldierId, setSoldierId] = useState("");
  const [delta, setDelta] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    listSoldiers().then(setSoldiers).catch(() => setError("שגיאה בטעינת רשימת חיילים"));
  }, []);

  // Load adjustments when soldier changes
  useEffect(() => {
    if (!soldierId) { setAdjustments([]); return; }
    listAdjustments(soldierId).then(setAdjustments).catch(() => setAdjustments([]));
  }, [soldierId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!soldierId || !delta || !reason.trim()) return;
    setSubmitting(true);
    setError("");
    setSuccessMsg("");
    try {
      await createAdjustment({ soldier_id: soldierId, delta, reason: reason.trim() });
      setSuccessMsg(t("score_adjustment.success_msg"));
      setDelta("");
      setReason("");
      // Reload adjustments for this soldier
      listAdjustments(soldierId).then(setAdjustments).catch(() => {});
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Layout>
      <div className="max-w-2xl mx-auto space-y-6 py-4" dir="rtl">
        <h2 className="text-xl font-semibold">{t("score_adjustment.title")}</h2>

        {/* Warning card */}
        <div className="bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-300 dark:border-yellow-700 rounded-lg p-4">
          <p className="font-semibold text-yellow-800 dark:text-yellow-300 text-sm mb-1">
            {t("score_adjustment.warning_title")}
          </p>
          <p className="text-yellow-700 dark:text-yellow-400 text-sm">
            {t("score_adjustment.warning_text")}
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 space-y-4">
          <div>
            <label htmlFor="adj-soldier" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t("score_adjustment.soldier_label")} <span className="text-red-500">*</span>
            </label>
            <select
              id="adj-soldier"
              value={soldierId}
              onChange={(e) => { setSoldierId(e.target.value); setSuccessMsg(""); }}
              required
              className="block w-full border border-gray-300 dark:border-gray-600 rounded-lg p-2 text-sm dark:bg-gray-700 dark:text-gray-100"
            >
              <option value="">— בחר חייל —</option>
              {soldiers.map((s) => (
                <option key={s.id} value={s.id}>{s.full_name}</option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="adj-delta" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t("score_adjustment.delta_label")} <span className="text-red-500">*</span>
            </label>
            <input
              id="adj-delta"
              type="number"
              step="0.01"
              value={delta}
              onChange={(e) => setDelta(e.target.value)}
              required
              placeholder="+1.5 / -2.0"
              className="block w-full border border-gray-300 dark:border-gray-600 rounded-lg p-2 text-sm dark:bg-gray-700 dark:text-gray-100"
              dir="ltr"
            />
          </div>

          <div>
            <label htmlFor="adj-reason" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t("score_adjustment.reason_label")} <span className="text-red-500">*</span>
            </label>
            <textarea
              id="adj-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
              rows={3}
              className="block w-full border border-gray-300 dark:border-gray-600 rounded-lg p-2 text-sm dark:bg-gray-700 dark:text-gray-100 resize-none"
            />
          </div>

          {error && <p className="text-red-500 text-sm">{error}</p>}
          {successMsg && <p className="text-green-600 dark:text-green-400 text-sm font-medium">{successMsg}</p>}

          <button
            type="submit"
            disabled={submitting || !soldierId || !delta || !reason.trim()}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {t("score_adjustment.submit_btn")}
          </button>
        </form>

        {/* Recent adjustments for selected soldier */}
        {soldierId && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5">
            <h3 className="font-medium text-sm mb-3">{t("score_adjustment.recent_title")}</h3>
            {adjustments.length === 0 ? (
              <p className="text-sm text-gray-500">{t("score_adjustment.no_adjustments")}</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
                    <th className="text-right pb-2 font-medium">{t("score_adjustment.date_col")}</th>
                    <th className="text-right pb-2 font-medium">{t("score_adjustment.delta_col")}</th>
                    <th className="text-right pb-2 font-medium">{t("score_adjustment.reason_col")}</th>
                  </tr>
                </thead>
                <tbody>
                  {adjustments.map((a) => (
                    <tr key={a.id} className="border-b dark:border-gray-600 last:border-0">
                      <td className="py-2 text-xs">{a.created_at.slice(0, 10)}</td>
                      <td className={`py-2 font-medium ${Number(a.delta) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                        {Number(a.delta) >= 0 ? "+" : ""}{Number(a.delta).toFixed(2)}
                      </td>
                      <td className="py-2 text-xs text-gray-600 dark:text-gray-400 max-w-xs truncate">{a.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </Layout>
  );
}
