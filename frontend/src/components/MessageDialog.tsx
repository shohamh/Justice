import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { EventDetailModal } from "./planning";

export interface MessageDialogProps {
  open: boolean;
  title: ReactNode;
  message: ReactNode;
  closeLabel?: string;
  onClose: () => void;
}

export default function MessageDialog({ open, title, message, closeLabel, onClose }: MessageDialogProps) {
  const { t } = useTranslation();
  const closeText = closeLabel ?? t("common.close", { defaultValue: "סגור" });
  return (
    <EventDetailModal open={open} title={title} onClose={onClose}>
      <div className="space-y-4">
        <p className="whitespace-pre-line text-sm text-gray-600 dark:text-gray-300">{message}</p>
        <div className="flex justify-end pt-1"><button type="button" data-testid="message-dialog-close" onClick={onClose} className="rounded bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700">{closeText}</button></div>
      </div>
    </EventDetailModal>
  );
}
