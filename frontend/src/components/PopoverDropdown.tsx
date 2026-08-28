import { useState, useRef, useEffect, type ReactNode } from "react";

interface Props {
  triggerLabel: string;
  badgeCount: number;
  panelClassName?: string;
  /** Optional tooltip shown on the trigger button (e.g. "סנן עמודה"). */
  title?: string;
  /** Overrides the trigger button's default className entirely, when set. */
  triggerClassName?: string;
  /** Optional `dir` attribute applied to the panel (e.g. "rtl" for right-edge-anchored panels). */
  panelDir?: "rtl" | "ltr";
  /** Optional test id applied to the trigger button, for tests that need to open the panel directly. */
  triggerTestId?: string;
  children: (close: () => void) => ReactNode;
}

export default function PopoverDropdown({
  triggerLabel,
  badgeCount,
  panelClassName,
  title,
  triggerClassName,
  panelDir,
  triggerTestId,
  children,
}: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        title={title}
        data-testid={triggerTestId}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
        className={
          triggerClassName ??
          "border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 flex items-center gap-1"
        }
      >
        {triggerLabel}
        {badgeCount > 0 && (
          <span className="bg-blue-600 text-white rounded-full text-[10px] px-1.5">{badgeCount}</span>
        )}
        <span>▾</span>
      </button>
      {open && (
        <div
          dir={panelDir}
          className={
            panelClassName ??
            "absolute top-full mt-1 z-30 bg-white dark:bg-gray-800 border dark:border-gray-600 rounded-lg shadow-xl min-w-40 max-h-56 flex flex-col"
          }
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
