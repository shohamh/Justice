import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Layout from "../../components/Layout";
import { queryKeys } from "../../queryKeys";
import { AdjustmentPreview, createAdjustment, listAdjustments, previewAdjustment } from "../../api/scoreAdjustments";
import { getSoldierScore, listSoldiers, SoldierDTO } from "../../api/soldiers";
import { getEffortBreakdown } from "../../api/scoring";

export default function ScoreAdjustmentPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  // Soldier search combobox
  const [soldierSearch, setSoldierSearch] = useState("");
  const [soldierId, setSoldierId] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const comboRef = useRef<HTMLDivElement>(null);

  // Delta: sign + positive amount
  const [sign, setSign] = useState<"+" | "-">("+");
  const [amount, setAmount] = useState("");

  // Preview
  const [preview, setPreview] = useState<AdjustmentPreview | null>(null);

  const [reason, setReason] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [error, setError] = useState("");

  const soldiersQuery = useQuery({ queryKey: queryKeys.soldiers(), queryFn: listSoldiers });
  const soldiers = soldiersQuery.data ?? [];

  useEffect(() => {
    if (soldiersQuery.isError) setError(t("score_adjustment.soldiers_load_error"));
  }, [soldiersQuery.isError, t]);

  const adjustmentsQuery = useQuery({
    queryKey: queryKeys.scoreAdjustments(soldierId),
    queryFn: () => listAdjustments(soldierId),
    enabled: !!soldierId,
  });
  const adjustments = adjustmentsQuery.data ?? [];

  const soldierScoreQuery = useQuery({
    queryKey: queryKeys.soldierScore(soldierId),
    queryFn: () => getSoldierScore(soldierId),
    enabled: !!soldierId,
  });
  const soldierScore = soldierScoreQuery.data ?? null;

  const effortBreakdownQuery = useQuery({
    queryKey: queryKeys.effortBreakdown(soldierId),
    queryFn: () => getEffortBreakdown(soldierId),
    enabled: !!soldierId,
  });
  const effortData = effortBreakdownQuery.data ?? null;

  useEffect(() => {
    setPreview(null);
  }, [soldierId]);

  const previewMutation = useMutation({
    mutationFn: () => previewAdjustment(soldierId, delta),
    onSuccess: (result) => setPreview(result),
    onError: () => { /* ignore — preview is optional */ },
  });

  const submitMutation = useMutation({
    mutationFn: () => createAdjustment({ soldier_id: soldierId, delta, reason: reason.trim() }),
    onSuccess: () => {
      setSuccessMsg(t("score_adjustment.success_msg"));
      setAmount("");
      setSign("+");
      setReason("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.scoreAdjustments(soldierId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.soldierScore(soldierId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.effortBreakdown(soldierId) });
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? t("score_adjustment.generic_error"));
    },
  });

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
    setSuccessMsg("");
  }

  const delta = amount ? (sign === "+" ? amount : `-${amount}`) : "";

  function handlePreview() {
    if (!soldierId || !delta) return;
    setPreview(null);
    previewMutation.mutate();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!soldierId || !delta || !reason.trim()) return;
    setError("");
    setSuccessMsg("");
    submitMutation.mutate();
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

          {/* Before / after metrics */}
          {soldierScore && (
            <div className="rounded-lg border border-gray-200 dark:border-gray-600 overflow-hidden text-sm">
              <div className="grid grid-cols-3 bg-gray-50 dark:bg-gray-700/50 text-xs text-gray-500 dark:text-gray-400 font-medium">
                <span className="px-3 py-2"></span>
                <span className="px-3 py-2 text-center border-r border-gray-200 dark:border-gray-600">לפני</span>
                <span className="px-3 py-2 text-center">אחרי</span>
              </div>
              {[
                {
                  label: "ניקוד צבור",
                  before: preview ? preview.cumulative_score_before : Number(soldierScore.cumulative_score).toFixed(3),
                  after: preview ? preview.cumulative_score_after : (delta ? (Number(soldierScore.cumulative_score) + Number(delta)).toFixed(3) : null),
                  note: undefined,
                },
                {
                  label: "ניקוד מנורמל",
                  before: preview ? preview.normalised_score_before : Number(soldierScore.normalised_score).toFixed(3),
                  after: preview ? preview.normalised_score_after : null,
                  note: "לחץ תצוגה מקדימה",
                },
                {
                  label: "עומס",
                  before: preview ? preview.effort_score_before : (effortData ? Number(effortData.effort_score).toFixed(3) : "—"),
                  after: preview ? preview.effort_score_after : null,
                  note: "לחץ תצוגה מקדימה",
                },
              ].map(({ label, before, after, note }) => (
                <div key={label} className="grid grid-cols-3 border-t border-gray-200 dark:border-gray-600">
                  <span className="px-3 py-2 font-medium text-gray-700 dark:text-gray-300">{label}</span>
                  <span className="px-3 py-2 text-center border-r border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 font-mono" dir="ltr">
                    {before}
                  </span>
                  <span className="px-3 py-2 text-center" dir="ltr">
                    {after !== null && after !== undefined ? (
                      <span className={`font-mono font-semibold ${Number(delta) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                        {after}
                      </span>
                    ) : (
                      <span className="text-gray-400 dark:text-gray-500 text-xs">{note ?? "—"}</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Delta: +/- buttons + positive number */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t("score_adjustment.delta_label")} <span className="text-red-500">*</span>
            </label>
            <div className="flex items-center gap-2" dir="ltr">
              <button
                type="button"
                onClick={() => { setSign("+"); setPreview(null); }}
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
                onClick={() => { setSign("-"); setPreview(null); }}
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
                onChange={(e) => { setAmount(e.target.value); setPreview(null); }}
                placeholder="0.00"
                className="w-32 border border-gray-300 dark:border-gray-600 rounded-lg p-2 text-sm dark:bg-gray-700 dark:text-gray-100"
              />
              {amount && Number(amount) > 0 && (
                <button
                  type="button"
                  onClick={handlePreview}
                  disabled={previewMutation.isPending || !soldierId}
                  className="px-3 py-2 text-xs border border-indigo-400 text-indigo-600 dark:text-indigo-400 dark:border-indigo-500 rounded-lg hover:bg-indigo-50 dark:hover:bg-indigo-900/30 disabled:opacity-50 transition-colors"
                >
                  {previewMutation.isPending ? "..." : "תצוגה מקדימה"}
                </button>
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
            disabled={submitMutation.isPending || !soldierId || !amount || Number(amount) <= 0 || !reason.trim()}
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
                        {Number(a.delta) >= 0 ? "+" : ""}{Number(a.delta).toFixed(3)}
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
