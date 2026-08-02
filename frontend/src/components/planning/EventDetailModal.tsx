import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { useModalBackClose } from "../../hooks/useModalBackClose";

export interface EventMetadataItem {
  id?: string;
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
  const titleId = useId();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useModalBackClose(onClose, open);

  useEffect(() => {
    if (!open) {
      if (wasOpenRef.current) {
        restoreFocusRef.current?.focus();
        restoreFocusRef.current = null;
        wasOpenRef.current = false;
      }
      return;
    }

    if (!wasOpenRef.current) {
      restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      wasOpenRef.current = true;
    }
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-30 p-4" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-y-auto rounded-lg bg-white p-5 shadow-xl dark:bg-gray-800" dir="rtl" onClick={event => event.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 id={titleId} className="text-lg font-bold">{title}</h3>
            {subtitle && <p className="text-sm text-gray-500 dark:text-gray-400">{subtitle}</p>}
          </div>
          <button ref={closeButtonRef} type="button" aria-label="סגור" onClick={onClose} className="text-xl text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">✕</button>
        </div>
        {metadata.length > 0 && <dl className="mb-4 grid grid-cols-1 gap-2 rounded bg-gray-50 p-3 text-sm dark:bg-gray-700 sm:grid-cols-2">{metadata.map((item, index) => <div key={item.id ?? String(item.label) + "-" + index}><dt className="text-xs text-gray-500 dark:text-gray-400">{item.label}</dt><dd>{item.value}</dd></div>)}</dl>}
        {actions && <div className="mb-4 flex flex-wrap gap-2">{actions}</div>}
        {children}
      </div>
    </div>
  );
}

export default EventDetailModal;