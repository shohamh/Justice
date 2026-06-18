import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { createAdjustment, listAdjustments, ScoreAdjustment } from "../../api/scoreAdjustments";
import { listSoldiers, SoldierDTO } from "../../api/soldiers";

export default function ScoreAdjustmentPage() {
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [adjustments, setAdjustments] = useState<ScoreAdjustment[]>([]);

  // Soldier search combobox
  const [soldierSearch, setSoldierSearch] = useState("");
  const [soldierId, setSoldierId] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const comboRef = useRef<HTMLDivElement>(null);

  // Delta: sign + positive amount
  const [sign, setSign] = useState<"+" | "-">("+");
  const [amount, setAmount] = useState("");

  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    listSoldiers().then(setSoldiers).catch(() => setError(t("score_adjustment.soldiers_load_error")));
  }, [t]);

  useEffect(() => {
    if (!soldierId) { setAdjustments([]); return; }
    listAdjustments(soldierId).then(setAdjustments).catch(() => setAdjustments([]));
  }, [soldierId]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (comboRef.current && !comboRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const filteredSoldiers = soldiers.filter((s) =>
    s.full_name.includes(soldierSearch)
  );

  function selectSoldier(s: SoldierDTO) {
    setSoldierId(s.id);
    setSoldierSearch(s.full_name);
    setShowDropdown(false);
    setSuccessMsg("");
  }

  function clearSoldier() {
    setSoldierId("");
    setSoldierSearch("");
    setAdjustments([]);
    setSuccessMsg("");
  }

  const delta = amount ? (sign === "+" ? amount : `-${amount}`) : "";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!soldierId || !delta || !reason.trim()) return;
    setSubmitting(true);
    setError("");
    setSuccessMsg("");
    try {
      await createAdjustment({ soldier_id: soldierId, delta, reason: reason.trim() });
      setSuccessMsg(t("score_adjustment.success_msg"));
      setAmount("");
      setSign("+");
      setReason("");
      listAdjustments(soldierId).then(setAdjustments).catch(() => {});
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? t("score_adjustment.generic_error"));
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

          {/* Soldier searchable combobox */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t("score_adjustment.soldier_label")} <span className="text-red-500">*</span>
            </label>
            <div ref={comboRef} className="relative">
              <div className="flex items-center border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 overflow-hidden">
                <input
                  type="text"
                  value={soldierSearch}
                  onChange={(e) => {
                    setSoldierSearch(e.target.value);
                    setSoldierId("");
                    setShowDropdown(true);
                  }}
                  onFocus={() => setShowDropdown(true)}
                  placeholder={t("score_adjustment.soldier_placeholder")}
                  className="flex-1 p-2 text-sm bg-transparent outline-none dark:text-gray-100"
                  autoComplete="off"
                />
                {soldierSearch && (
                  <button
                    type="button"
                    onClick={clearSoldier}
                    className="px-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-lg leading-none"
                    tabIndex={-1}
                  >
                    ✕
                  </button>
                )}
              </div>
              {showDropdown && filteredSoldiers.length > 0 && (
                <ul className="absolute z-20 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg mt-1 shadow-lg max-h-52 overflow-y-auto text-sm">
                  {filteredSoldiers.map((s) => (
                    <li
                      key={s.id}
                      onMouseDown={() => selectSoldier(s)}
                      className={`px-3 py-2 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 ${s.id === soldierId ? "bg-blue-50 dark:bg-blue-900/40 font-medium" : ""}`}
                    >
                      {s.full_name}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* Delta: +/- buttons + positive number */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t("score_adjustment.delta_label")} <span className="text-red-500">*</span>
            </label>
            <div className="flex items-center gap-2" dir="ltr">
              <button
                type="button"
                onClick={() => setSign("+")}
                className={`w-10 h-10 rounded-lg text-lg font-bold border transition-colors ${
                  sign === "+"
                    ? "bg-green-500 text-white border-green-500"
                    : "bg-white dark:bg-gray-700 text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 hover:border-green-400"
                }`}
              >
                +
              </button>
              <button
                type="button"
                onClick={() => setSign("-")}
                className={`w-10 h-10 rounded-lg text-lg font-bold border transition-colors ${
                  sign === "-"
                    ? "bg-red-500 text-white border-red-500"
                    : "bg-white dark:bg-gray-700 text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 hover:border-red-400"
                }`}
              >
                −
              </button>
              <input
                id="adj-amount"
                type="number"
                step="0.01"
                min="0"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="0.00"
                className="w-32 border border-gray-300 dark:border-gray-600 rounded-lg p-2 text-sm dark:bg-gray-700 dark:text-gray-100"
              />
              {amount && (
                <span className={`text-sm font-semibold ${sign === "+" ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                  {sign}{Number(amount).toFixed(2)}
                </span>
              )}
            </div>
          </div>

          {/* Reason */}
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
            disabled={submitting || !soldierId || !amount || Number(amount) <= 0 || !reason.trim()}
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
                      <td className="py-2 text-xs text-gray-600 dark:text-gray-400 max-w-xs" title={a.reason}>{a.reason}</td>
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
