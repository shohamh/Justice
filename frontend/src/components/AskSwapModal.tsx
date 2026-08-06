import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import Fuse from "fuse.js";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";
import { createSwap, addSwapTargets, publishSwapToMarketplace, listEligibleTargets, getSwapConfig, CreateSwapInput } from "../api/swaps";
import { EffectiveDuty } from "../api/assignments";
import { lastDutyDay } from "../utils/formatDate";
import { translateApiError } from "../utils/translateApiError";

function extractErrorMessage(err: unknown, t: (key: string, options?: Record<string, unknown>) => string, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string" && detail) {
    if (detail.startsWith("cover_not_eligible:")) {
      return detail.slice("cover_not_eligible:".length) || fallback;
    }
  }
  if (Array.isArray(detail)) {
    // Pydantic v2 validation errors — list of {loc, msg, type}. The msg
    // itself is English framework text, so we don't surface it — just the field.
    const fields = (detail as { loc?: string[] }[])
      .map((d) => d.loc?.slice(1).join(".") ?? "?")
      .join(", ");
    return fields ? `נתונים לא תקינים בשדות: ${fields}` : fallback;
  }
  return translateApiError(err, t, fallback);
}

export interface EditingSwap {
  id: string;
  open_to_marketplace: boolean;
  candidates: { soldier_id: string }[];
}

export default function AskSwapModal({
  duty, dutyTypeName, onClose, onCreated, editingSwap,
}: {
  duty: Pick<EffectiveDuty, "assignment_id" | "start_date" | "end_date">;
  dutyTypeName: string;
  onClose: () => void;
  onCreated: () => void;
  editingSwap?: EditingSwap;
}) {
  const { t } = useTranslation();
  const { enrollmentPending } = useAuth();
  const [openToMarketplace, setOpenToMarketplace] = useState(editingSwap?.open_to_marketplace ?? false);
  const [selectedTargets, setSelectedTargets] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const eligibleQuery = useQuery({
    queryKey: ["swaps", "eligible-targets", duty.assignment_id],
    queryFn: () => listEligibleTargets(duty.assignment_id),
  });
  const eligibleTargets = useMemo(() => eligibleQuery.data ?? [], [eligibleQuery.data]);
  const [targetQuery, setTargetQuery] = useState("");
  const targetFuse = useMemo(
    () => new Fuse(eligibleTargets, { keys: ["full_name", "node_name"], threshold: 0.4 }),
    [eligibleTargets]
  );
  const filteredTargets = targetQuery.trim() === ""
    ? eligibleTargets
    : targetFuse.search(targetQuery).map(r => r.item);
  const configQuery = useQuery({ queryKey: queryKeys.swapConfig(), queryFn: getSwapConfig });
  const maxTargets = configQuery.data?.max_specific_targets ?? 5;

  const alreadyInvitedIds = new Set((editingSwap?.candidates ?? []).map((c) => c.soldier_id));
  const remainingSlots = Math.max(0, maxTargets - alreadyInvitedIds.size);
  const marketplaceAlreadyPublished = editingSwap?.open_to_marketplace === true;

  function toggleTarget(id: string) {
    setSelectedTargets((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < remainingSlots) next.add(id);
      return next;
    });
  }

  const newlyPublishing = openToMarketplace && !marketplaceAlreadyPublished;
  const nothingSelected = editingSwap
    ? selectedTargets.size === 0 && !newlyPublishing
    : selectedTargets.size === 0 && !openToMarketplace;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (nothingSelected) {
      setError(editingSwap ? t("swaps.nothing_new_selected") : t("swaps.select_at_least_one"));
      return;
    }
    try {
      if (editingSwap) {
        if (selectedTargets.size > 0) {
          await addSwapTargets(editingSwap.id, Array.from(selectedTargets));
        }
        if (newlyPublishing) {
          await publishSwapToMarketplace(editingSwap.id);
        }
      } else {
        const input: CreateSwapInput = {
          duty_assignment_id: duty.assignment_id,
          reason: reason || null,
          target_soldier_ids: Array.from(selectedTargets),
          open_to_marketplace: openToMarketplace,
        };
        await createSwap(input);
      }
      onCreated();
    } catch (err: unknown) {
      setError(extractErrorMessage(err, t, "שגיאה"));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold dark:text-gray-100">
            {editingSwap ? t("swaps.manage_swap_title") : t("swaps.ask_swap")}: {dutyTypeName}
          </h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3" dir="ltr">
          {(() => {
            const last = lastDutyDay(duty.end_date);
            return duty.start_date === last ? duty.start_date : `${duty.start_date} → ${last}`;
          })()}
        </p>
        {enrollmentPending && (
          <div className="rounded border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 text-sm text-yellow-800 dark:text-yellow-200 mb-2">
            בקשת הקליטה שלך למסגרת עדיין ממתינה לאישור — לא ניתן להגיש בקשות חדשות עד לאישור.
          </div>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input
              type="checkbox"
              data-testid="ask-swap-marketplace-checkbox"
              checked={openToMarketplace}
              disabled={marketplaceAlreadyPublished}
              onChange={(e) => setOpenToMarketplace(e.target.checked)}
            />
            {t("swaps.post_open")}
            {marketplaceAlreadyPublished && (
              <span className="text-xs text-gray-400">(<span>{t("swaps.already_on_marketplace")}</span>)</span>
            )}
          </label>
          <div className="space-y-1">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {t("swaps.select_up_to", { n: maxTargets })} ({alreadyInvitedIds.size + selectedTargets.size}/{maxTargets})
            </p>
            <input
              type="text"
              data-testid="ask-swap-target-search"
              value={targetQuery}
              onChange={e => setTargetQuery(e.target.value)}
              placeholder={t("swaps.search_soldier")}
              className="block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            />
            <div className="max-h-48 overflow-y-auto border rounded dark:border-gray-600">
              {eligibleQuery.isLoading ? (
                <p className="text-sm text-gray-500 p-2">{t("swaps.loading_eligible_targets")}</p>
              ) : eligibleTargets.length === 0 ? (
                <p className="text-sm text-gray-500 p-2">{t("swaps.no_eligible_targets")}</p>
              ) : filteredTargets.length === 0 ? (
                <p className="text-sm text-gray-500 p-2">{t("swaps.no_search_results")}</p>
              ) : (
                <ul>
                  {filteredTargets.map((s) => {
                    const alreadyInvited = alreadyInvitedIds.has(s.soldier_id);
                    const limitReached = !alreadyInvited && !selectedTargets.has(s.soldier_id) && selectedTargets.size >= remainingSlots;
                    return (
                      <li key={s.soldier_id} className="flex items-center gap-2 px-2 py-1 border-b last:border-b-0 dark:border-gray-700 text-sm">
                        <input
                          type="checkbox"
                          checked={alreadyInvited || selectedTargets.has(s.soldier_id)}
                          disabled={alreadyInvited || limitReached}
                          onChange={() => toggleTarget(s.soldier_id)}
                        />
                        <span>{s.full_name}{s.node_name ? ` — ${s.node_name}` : ""} ({t("swaps.organizational_distance")}: {s.hierarchy_distance})</span>
                        {alreadyInvited && <span className="text-xs text-gray-400">(<span>{t("swaps.already_invited")}</span>)</span>}
                        {limitReached && <span className="text-xs text-gray-400">(<span>{t("swaps.invite_limit_reached")}</span>)</span>}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
          {!editingSwap && (
            <textarea placeholder={t("swaps.personal_message")} value={reason}
              onChange={e => setReason(e.target.value)} rows={3}
              className="w-full border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          )}
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded dark:border-gray-600 dark:text-gray-300">{t("swaps.cancel")}</button>
            <button type="submit" disabled={enrollmentPending || nothingSelected} className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">{t("swaps.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
