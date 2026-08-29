import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { EventDetailModal } from "./planning";

export interface InputDialogProps {
  open: boolean;
  title: ReactNode;
  message?: ReactNode;
  label: string;
  initialValue?: string;
  placeholder?: string;
  multiline?: boolean;
  confirmLabel?: string;
  cancelLabel?: string;
  required?: boolean;
  onConfirm: (value: string) => void;
  onClose: () => void;
}

export default function InputDialog({ open, title, message, label, initialValue = "", placeholder, multiline = false, confirmLabel, cancelLabel, required = false, onConfirm, onClose }: InputDialogProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState(initialValue);
  const confirmText = confirmLabel ?? t("common.confirm", { defaultValue: "אישור" });
  const cancelText = cancelLabel ?? t("common.cancel", { defaultValue: "ביטול" });

  useEffect(() => { if (!open) setValue(initialValue); }, [open, initialValue]);
  function handleClose() { setValue(initialValue); onClose(); }
  function handleConfirm() {
    const trimmed = value.trim();
    if (required && !trimmed) return;
    setValue(initialValue);
    onConfirm(trimmed);
  }
  const className = "mt-1 w-full rounded border p-2 text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100";
  return (
    <EventDetailModal open={open} title={title} onClose={handleClose}>
      <div className="space-y-4">
        {message && <p className="whitespace-pre-line text-sm text-gray-600 dark:text-gray-300">{message}</p>}
        <label className="block text-sm text-gray-700 dark:text-gray-200">{label}{multiline ? <textarea aria-label={label} value={value} placeholder={placeholder} onChange={event => setValue(event.target.value)} className={className} rows={3} /> : <input aria-label={label} value={value} placeholder={placeholder} onChange={event => setValue(event.target.value)} className={className} />}</label>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" data-testid="input-dialog-cancel" onClick={handleClose} className="rounded border px-4 py-2 text-sm dark:border-gray-600 dark:text-gray-100">{cancelText}</button>
          <button type="button" data-testid="input-dialog-confirm" disabled={required && !value.trim()} onClick={handleConfirm} className="rounded bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-40">{confirmText}</button>
        </div>
      </div>
    </EventDetailModal>
  );
}
