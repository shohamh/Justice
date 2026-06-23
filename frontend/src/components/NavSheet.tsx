import { Link } from "react-router-dom";

export type BadgeColor = "red" | "blue" | "yellow" | "green";

const BADGE_COLOR_CLASSES: Record<BadgeColor, string> = {
  red: "bg-red-500 text-white",
  blue: "bg-blue-500 text-white",
  yellow: "bg-yellow-500 text-gray-900",
  green: "bg-green-500 text-white",
};

interface NavSheetItem {
  label: string;
  to: string;
  badge?: number;
  badgeColor?: BadgeColor;
  testId?: string;
}

interface NavSheetProps {
  open: boolean;
  onClose: () => void;
  items: NavSheetItem[];
  testId?: string;
}

export default function NavSheet({ open, onClose, items, testId }: NavSheetProps) {
  if (!open) return null;

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
        className="fixed bottom-0 right-0 left-0 md:bottom-0 md:right-24 md:left-auto md:top-0 bg-white z-50 rounded-t-2xl md:rounded-none shadow-xl overflow-y-auto max-h-[50vh] md:max-h-full md:w-48 py-4 space-y-1 dark:bg-gray-800 dark:text-gray-100"
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
          <Link
            key={item.to}
            to={item.to}
            onClick={onClose}
            className="flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg"
            data-testid={item.testId}
          >
            <span>{item.label}</span>
            {item.badge != null && item.badge > 0 && (
              <span className={`${BADGE_COLOR_CLASSES[item.badgeColor ?? "red"]} text-xs rounded-full px-2 py-0.5 leading-4 min-w-[1.25rem] text-center`}>
                {item.badge}
              </span>
            )}
          </Link>
        ))}
      </div>
    </>
  );
}
