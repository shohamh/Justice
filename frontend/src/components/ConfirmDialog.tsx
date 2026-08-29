import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { EventDetailModal } from "./planning";

export interface ConfirmDialogProps {
  open: boolean;
  title: ReactNode;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export default function ConfirmDialog({ open, title, message, confirmLabel, cancelLabel, danger = false, onConfirm, onClose }: ConfirmDialogProps) {
  const { t } = useTranslation();
  const confirmText = confirmLabel ?? t("common.confirm", { defaultValue: "אישור" });
  const cancelText = cancelLabel ?? t("common.cancel", { defaultValue: "ביטול" });
  return (
    <EventDetailModal open={open} title={title} onClose={onClose}>
      <div className="space-y-4">
        <p className="whitespace-pre-line text-sm text-gray-600 dark:text-gray-300">{message}</p>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" data-testid="confirm-dialog-cancel" onClick={onClose} className="rounded border px-4 py-2 text-sm dark:border-gray-600 dark:text-gray-100">{cancelText}</button>
          <button type="button" data-testid="confirm-dialog-confirm" onClick={onConfirm} className={`rounded px-4 py-2 text-sm text-white ${danger ? "bg-red-600 hover:bg-red-700" : "bg-indigo-600 hover:bg-indigo-700"}`}>{confirmText}</button>
        </div>
      </div>
    </EventDetailModal>
  );
}
