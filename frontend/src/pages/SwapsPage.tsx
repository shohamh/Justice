import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import {
  SwapRequest,
  CreateSwapInput,
  cancelSwap,
  claimSwap,
  createSwap,
  listBoard,
  listMySwaps,
} from "../api/swaps";

const STATUS_COLORS: Record<string, string> = {
  applied: "bg-green-100 text-green-700",
  pending_approval: "bg-amber-100 text-amber-700",
  open: "bg-amber-100 text-amber-700",
  rejected: "bg-red-100 text-red-700",
  cancelled: "bg-gray-100 text-gray-600",
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

interface CreateSwapModalProps {
  onClose: () => void;
  onCreated: () => void;
}

function CreateSwapModal({ onClose, onCreated }: CreateSwapModalProps) {
  const { t } = useTranslation();
  const [dutyDate, setDutyDate] = useState("");
  const [assignmentId, setAssignmentId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const input: CreateSwapInput = {
        duty_date: dutyDate,
        duty_assignment_id: assignmentId,
        reason: reason || null,
      };
      await createSwap(input);
      onCreated();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{t("swaps.create")}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <label className="block text-sm">
            {t("swaps.duty_date")}
            <input type="date" value={dutyDate} onChange={e => setDutyDate(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" required />
          </label>
          <label className="block text-sm">
            {t("swaps.assignment_id")}
            <input type="text" value={assignmentId} onChange={e => setAssignmentId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" required placeholder="מזהה שיבוץ" />
          </label>
          <label className="block text-sm">
            {t("swaps.reason")}
            <textarea value={reason} onChange={e => setReason(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" rows={2} />
          </label>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded">{t("swaps.cancel")}</button>
            <button type="submit" className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">{t("swaps.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function SwapsPage() {
  const { t } = useTranslation();
  const [mySwaps, setMySwaps] = useState<SwapRequest[]>([]);
  const [boardSwaps, setBoardSwaps] = useState<SwapRequest[]>([]);
  const [showCreate, setShowCreate] = useState(false);

  const refresh = useCallback(async () => {
    const [mine, board] = await Promise.all([listMySwaps(), listBoard()]);
    setMySwaps(mine);
    setBoardSwaps(board);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function handleCancel(id: string) {
    try {
      await cancelSwap(id);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(detail ?? "שגיאה");
    }
  }

  async function handleClaim(id: string) {
    try {
      await claimSwap(id);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(detail ?? "שגיאה");
    }
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6" dir="rtl" data-testid="swaps-page">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-semibold">{t("swaps.title")}</h2>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
          >
            {t("swaps.create")}
          </button>
        </div>

        {/* My Swap Requests */}
        <div>
          <h3 className="text-base font-medium mb-2">{t("swaps.mine")}</h3>
          {mySwaps.length === 0 && <p className="text-sm text-gray-500">{t("swaps.none_mine")}</p>}
          <ul className="space-y-2">
            {mySwaps.map(swap => (
              <li key={swap.id} className="border rounded p-3 text-sm space-y-1">
                <div className="flex items-center justify-between">
                  <span dir="ltr" className="font-medium">{swap.duty_date}</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[swap.status] ?? ""}`}>
                    {t(statusKey(swap.status))}
                  </span>
                </div>
                {swap.reason && <p className="text-gray-500 text-xs">{swap.reason}</p>}
                {(swap.status === "open" || swap.status === "pending_approval") && (
                  <button
                    type="button"
                    onClick={() => handleCancel(swap.id)}
                    className="text-red-600 text-xs hover:underline"
                  >
                    {t("swaps.cancel")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* Swap Board */}
        <div>
          <h3 className="text-base font-medium mb-2">{t("swaps.board")}</h3>
          {boardSwaps.length === 0 && <p className="text-sm text-gray-500">{t("swaps.none_board")}</p>}
          <ul className="space-y-2">
            {boardSwaps.map(swap => (
              <li key={swap.id} className="border rounded p-3 text-sm space-y-1">
                <div className="flex items-center justify-between">
                  <span dir="ltr" className="font-medium">{swap.duty_date}</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[swap.status] ?? ""}`}>
                    {t(statusKey(swap.status))}
                  </span>
                </div>
                {swap.reason && <p className="text-gray-500 text-xs">{swap.reason}</p>}
                <button
                  type="button"
                  onClick={() => handleClaim(swap.id)}
                  className="bg-indigo-600 text-white px-2 py-1 rounded text-xs hover:bg-indigo-700"
                >
                  {t("swaps.cover")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {showCreate && (
        <CreateSwapModal
          onClose={() => setShowCreate(false)}
          onCreated={async () => { setShowCreate(false); await refresh(); }}
        />
      )}
    </Layout>
  );
}
