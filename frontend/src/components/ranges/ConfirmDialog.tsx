import { useState } from "react";
import { useTranslation } from "react-i18next";
import SharedConfirmDialog from "../ConfirmDialog";
import { EventDetailModal } from "../planning";

interface Props {
  open: boolean;
  title: string;
  message: string;
  /** When set, shows a required free-text reason field (used for the "clear
   * assignments" action, replacing window.prompt()). */
  reasonLabel?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: (reason?: string) => void;
  onClose: () => void;
}

export default function ConfirmDialog({
  open, title, message, reasonLabel, confirmLabel, cancelLabel,
  danger = false, onConfirm, onClose,
}: Props) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const translatedConfirmLabel = confirmLabel ?? t("common.confirm", { defaultValue: "אישור" });
  const translatedCancelLabel = cancelLabel ?? t("common.cancel", { defaultValue: "ביטול" });

  if (reasonLabel === undefined) {
    return <SharedConfirmDialog open={open} title={title} message={message} confirmLabel={confirmLabel} cancelLabel={cancelLabel} danger={danger} onConfirm={() => onConfirm()} onClose={onClose} />;
  }

  const canConfirm = reason.trim().length > 0;
  function handleClose() { setReason(""); onClose(); }
  return (
    <EventDetailModal open={open} title={title} onClose={handleClose}>
      <div className="space-y-3">
        <p className="text-sm text-gray-600 dark:text-gray-300">{message}</p>
        <label className="block text-sm">
          {reasonLabel}
          <textarea
            aria-label={reasonLabel}
            value={reason}
            onChange={e => setReason(e.target.value)}
            className="mt-1 w-full rounded border p-2 text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            rows={3}
            maxLength={500}
          />
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" data-testid="confirm-dialog-cancel" onClick={handleClose} className="rounded border px-4 py-2 text-sm dark:border-gray-600 dark:text-gray-100">
            {translatedCancelLabel}
          </button>
          <button
            type="button"
            data-testid="confirm-dialog-confirm"
            disabled={!canConfirm}
            onClick={() => { const value = reason.trim(); setReason(""); onConfirm(value); }}
            className={`rounded px-4 py-2 text-sm text-white disabled:opacity-40 ${danger ? "bg-red-600 hover:bg-red-700" : "bg-indigo-600 hover:bg-indigo-700"}`}
          >
            {translatedConfirmLabel}
          </button>
        </div>
      </div>
    </EventDetailModal>
  );
}
