import { Link } from "react-router-dom";

interface NavSheetItem {
  label: string;
  to: string;
}

interface NavSheetProps {
  open: boolean;
  onClose: () => void;
  items: NavSheetItem[];
  testId?: string;
}

export default function NavSheet({ open, onClose, items, testId }: NavSheetProps) {
  if (!open) return null;

  const linkClass = "block px-4 py-3 rounded hover:bg-gray-100 text-sm font-medium" as const;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
        data-testid={testId ? `${testId}-backdrop` : undefined}
        role="presentation"
      />
      <div
        role="dialog"
        aria-modal="true"
        className="fixed bottom-0 right-0 left-0 md:bottom-0 md:right-24 md:left-auto md:top-0 bg-white z-50 rounded-t-2xl md:rounded-none shadow-xl overflow-y-auto max-h-[50vh] md:max-h-full md:w-48 py-4 space-y-1"
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
        data-testid={testId}
      >
        <div className="flex justify-end px-3">
          <button
            autoFocus
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            aria-label="סגור"
          >
            ✕
          </button>
        </div>
        {items.map((item) => (
          <Link key={item.to} to={item.to} onClick={onClose} className={linkClass}>
            {item.label}
          </Link>
        ))}
      </div>
    </>
  );
}
