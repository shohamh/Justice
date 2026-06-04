import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import TabBar from "../components/TabBar";
import { useAuth } from "../auth/AuthContext";
import {
  SwapRequest, cancelSwap, createSwap, listBoard,
  listMySwaps, listIncomingSwaps, submitCoverOffer, CreateSwapInput,
} from "../api/swaps";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import type { DutyType } from "../api/dutyConfig";

const STATUS_COLORS: Record<string, string> = {
  applied: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  pending_approval: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  open: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  rejected: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
  cancelled: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400",
};

function statusKey(status: string) {
  const map: Record<string, string> = {
    open: "swaps.status_open",
    pending_approval: "swaps.status_pending_approval",
    applied: "swaps.status_applied",
    rejected: "swaps.status_rejected",
    cancelled: "swaps.status_cancelled",
  };
  return map[status] ?? status;
}

function AskSwapModal({
  duty, dutyTypeName, onClose, onCreated,
}: {
  duty: EffectiveDuty; dutyTypeName: string; onClose: () => void; onCreated: () => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"open" | "soldier">("open");
  const [targetSoldierId, setTargetSoldierId] = useState("");
  const [reason, setReason] = useState("");
  const [dutyDate, setDutyDate] = useState(duty.start_date);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const input: CreateSwapInput = {
        duty_assignment_id: duty.assignment_id,
        duty_date: dutyDate,
        reason: reason || null,
        target_soldier_id: mode === "soldier" && targetSoldierId ? targetSoldierId : null,
      };
      await createSwap(input);
      onCreated();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold dark:text-gray-100">{t("swaps.ask_swap")}: {dutyTypeName}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="text-sm text-gray-600 dark:text-gray-300">
            {t("swaps.duty_date")}:
            <input type="date" value={dutyDate} onChange={e => setDutyDate(e.target.value)}
              min={duty.start_date} max={duty.end_date}
              className="border rounded px-1 py-0.5 text-xs mr-2 dark:bg-gray-700 dark:border-gray-600" required />
          </div>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
              <input type="radio" name="mode" checked={mode === "open"} onChange={() => setMode("open")} />
              {t("swaps.post_open")}
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
              <input type="radio" name="mode" checked={mode === "soldier"} onChange={() => setMode("soldier")} />
              {t("swaps.send_to_soldier")}
            </label>
          </div>
          {mode === "soldier" && (
            <input type="text" placeholder="מספר אישי של חייל" value={targetSoldierId}
              onChange={e => setTargetSoldierId(e.target.value)}
              className="w-full border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          )}
          <textarea placeholder={t("swaps.personal_message")} value={reason}
            onChange={e => setReason(e.target.value)} rows={3}
            className="w-full border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded dark:border-gray-600 dark:text-gray-300">{t("swaps.cancel")}</button>
            <button type="submit" className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">{t("swaps.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function CoverOfferModal({
  swap, myDuties, dutyTypes, onClose, onDone,
}: {
  swap: SwapRequest; myDuties: EffectiveDuty[]; dutyTypes: Record<string, string>; onClose: () => void; onDone: () => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"free" | "trade">("free");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  function toggleDuty(id: string) {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  async function handleSubmit() {
    setError(null);
    try {
      await submitCoverOffer(swap.id, mode === "trade" ? selectedIds : []);
      onDone();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold dark:text-gray-100">{t("swaps.cover")}</h3>
          <button onClick={onClose} className="text-gray-500">✕</button>
        </div>
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input type="radio" name="cover_mode" checked={mode === "free"} onChange={() => setMode("free")} />
            {t("swaps.cover_free")}
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input type="radio" name="cover_mode" checked={mode === "trade"} onChange={() => setMode("trade")} />
            {t("swaps.offer_trade")}
          </label>
          {mode === "trade" && (
            <div className="space-y-1 max-h-40 overflow-y-auto border rounded p-2 dark:border-gray-600">
              <p className="text-xs text-gray-500 mb-1">{t("swaps.select_duties_to_offer")}:</p>
              {myDuties.filter(d => d.assignment_id !== swap.duty_assignment_id).map(d => (
                <label key={d.assignment_id} className="flex items-center gap-2 text-xs cursor-pointer dark:text-gray-300">
                  <input type="checkbox" checked={selectedIds.includes(d.assignment_id)} onChange={() => toggleDuty(d.assignment_id)} />
                  <span>{dutyTypes[d.duty_type_id] ?? d.duty_type_id} — {d.start_date}</span>
                </label>
              ))}
            </div>
          )}
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded dark:border-gray-600 dark:text-gray-300">{t("swaps.cancel")}</button>
            <button type="button" onClick={() => void handleSubmit()}
              disabled={mode === "trade" && selectedIds.length === 0}
              className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
              {t("swaps.submit_offer")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function SwapsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [tab, setTab] = useState(0);
  const [myDuties, setMyDuties] = useState<EffectiveDuty[]>([]);
  const [dutyTypes, setDutyTypes] = useState<Record<string, string>>({});
  const [mySwaps, setMySwaps] = useState<SwapRequest[]>([]);
  const [boardSwaps, setBoardSwaps] = useState<SwapRequest[]>([]);
  const [incomingSwaps, setIncomingSwaps] = useState<SwapRequest[]>([]);
  const [askSwapDuty, setAskSwapDuty] = useState<EffectiveDuty | null>(null);
  const [coverSwap, setCoverSwap] = useState<SwapRequest | null>(null);

  const refresh = useCallback(async () => {
    if (!user) return;
    const [mine, board, incoming, duties] = await Promise.all([
      listMySwaps(),
      listBoard(),
      listIncomingSwaps(),
      listEffectiveDuties(user.id).catch(() => [] as EffectiveDuty[]),
    ]);
    // fetch duty types lazily
    const { listDutyTypes } = await import("../api/dutyConfig");
    const dts = await listDutyTypes().catch(() => [] as DutyType[]);
    setMySwaps(mine);
    setBoardSwaps(board);
    setIncomingSwaps(incoming);
    setMyDuties(duties);
    setDutyTypes(Object.fromEntries(dts.map(d => [d.id, d.name])));
  }, [user]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function handleCancel(id: string) {
    try { await cancelSwap(id); await refresh(); }
    catch (err: unknown) {
      alert((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "שגיאה");
    }
  }

  const tabs = [t("swaps.tab_mine"), t("swaps.tab_board"), t("swaps.tab_incoming")];

  const renderSwapCard = (swap: SwapRequest, showCover = false) => (
    <li key={swap.id} className="border rounded p-3 text-sm space-y-1 dark:border-gray-600">
      <div className="flex items-center justify-between">
        <span dir="ltr" className="font-medium">{swap.duty_date}</span>
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[swap.status] ?? ""}`}>
          {t(statusKey(swap.status))}
        </span>
      </div>
      {swap.reason && <p className="text-gray-500 text-xs">{swap.reason}</p>}
      {(swap.status === "open" || swap.status === "pending_approval") && !showCover && (
        <button type="button" onClick={() => handleCancel(swap.id)} className="text-red-600 text-xs hover:underline">
          {t("swaps.cancel")}
        </button>
      )}
      {showCover && swap.status === "open" && (
        <button type="button" onClick={() => setCoverSwap(swap)}
          className="bg-indigo-600 text-white px-2 py-1 rounded text-xs hover:bg-indigo-700">
          {t("swaps.cover")}
        </button>
      )}
    </li>
  );

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6" dir="rtl" data-testid="swaps-page">
        <h2 className="text-xl font-semibold mb-4 dark:text-gray-100">{t("swaps.title")}</h2>
        <TabBar tabs={tabs} active={tab} onChange={setTab} />

        {tab === 0 && (
          <div className="space-y-4">
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400">{t("swaps.my_upcoming_duties")}</h3>
              {myDuties.length === 0 && <p className="text-sm text-gray-500">{t("swaps.no_duties")}</p>}
              <ul className="space-y-2">
                {myDuties.map(d => (
                  <li key={d.assignment_id} className="border rounded p-3 text-sm flex items-center justify-between dark:border-gray-600">
                    <div>
                      <span className="font-medium dark:text-gray-100">{dutyTypes[d.duty_type_id] ?? d.duty_type_id}</span>
                      <span className="text-gray-500 mr-2 text-xs" dir="ltr">{d.start_date} → {d.end_date}</span>
                    </div>
                    <button type="button" onClick={() => setAskSwapDuty(d)}
                      className="text-xs bg-indigo-600 text-white px-2 py-1 rounded hover:bg-indigo-700">
                      {t("swaps.ask_swap")}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            {mySwaps.length > 0 && (
              <div className="border-t pt-4 space-y-2 dark:border-gray-600">
                <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400">{t("swaps.mine")}</h3>
                <ul className="space-y-2">{mySwaps.map(s => renderSwapCard(s))}</ul>
              </div>
            )}
          </div>
        )}

        {tab === 1 && (
          <div className="space-y-2">
            {boardSwaps.length === 0 && <p className="text-sm text-gray-500">{t("swaps.none_board")}</p>}
            <ul className="space-y-2">{boardSwaps.map(s => renderSwapCard(s, true))}</ul>
          </div>
        )}

        {tab === 2 && (
          <div className="space-y-2">
            {incomingSwaps.length === 0 && <p className="text-sm text-gray-500">{t("swaps.none_incoming")}</p>}
            <ul className="space-y-2">
              {incomingSwaps.map(swap => (
                <li key={swap.id} className="border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950 rounded p-3 text-sm space-y-1">
                  <div className="flex items-center justify-between">
                    <span dir="ltr" className="font-medium">{swap.duty_date}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[swap.status] ?? ""}`}>
                      {t(statusKey(swap.status))}
                    </span>
                  </div>
                  {swap.reason && <p className="text-gray-600 dark:text-gray-400 text-xs">{swap.reason}</p>}
                  <button type="button" onClick={() => setCoverSwap(swap)}
                    className="bg-indigo-600 text-white px-2 py-1 rounded text-xs hover:bg-indigo-700">
                    {t("swaps.accept_cover")}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {askSwapDuty && (
        <AskSwapModal
          duty={askSwapDuty}
          dutyTypeName={dutyTypes[askSwapDuty.duty_type_id] ?? askSwapDuty.duty_type_id}
          onClose={() => setAskSwapDuty(null)}
          onCreated={async () => { setAskSwapDuty(null); await refresh(); }}
        />
      )}

      {coverSwap && (
        <CoverOfferModal
          swap={coverSwap}
          myDuties={myDuties}
          dutyTypes={dutyTypes}
          onClose={() => setCoverSwap(null)}
          onDone={async () => { setCoverSwap(null); await refresh(); }}
        />
      )}
    </Layout>
  );
}
