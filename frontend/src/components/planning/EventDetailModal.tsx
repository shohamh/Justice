import type { ReactNode } from "react";
import { useModalBackClose } from "../../hooks/useModalBackClose";

export interface EventMetadataItem {
  label: ReactNode;
  value: ReactNode;
}

export interface EventDetailModalProps {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  metadata?: EventMetadataItem[];
  actions?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

export function EventDetailModal({ open, title, subtitle, metadata = [], actions, onClose, children }: EventDetailModalProps) {
  useModalBackClose(onClose, open);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-30 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="event-detail-title"
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-y-auto rounded-lg bg-white p-5 shadow-xl dark:bg-gray-800"
        dir="rtl"
        onClick={event => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 id="event-detail-title" className="text-lg font-bold">{title}</h3>
            {subtitle && <p className="text-sm text-gray-500 dark:text-gray-400">{subtitle}</p>}
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="text-xl text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">✕</button>
        </div>
        {metadata.length > 0 && (
          <dl className="mb-4 grid grid-cols-1 gap-2 rounded bg-gray-50 p-3 text-sm dark:bg-gray-700 sm:grid-cols-2">
            {metadata.map((item, index) => <div key={index}><dt className="text-xs text-gray-500 dark:text-gray-400">{item.label}</dt><dd>{item.value}</dd></div>)}
          </dl>
        )}
        {actions && <div className="mb-4 flex flex-wrap gap-2">{actions}</div>}
        {children}
      </div>
    </div>
  );
}

export default EventDetailModal;
