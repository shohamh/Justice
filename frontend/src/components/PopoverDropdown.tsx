import { useState, useRef, useEffect, type ReactNode } from "react";

interface Props {
  triggerLabel: string;
  badgeCount: number;
  panelClassName?: string;
  children: (close: () => void) => ReactNode;
}

export default function PopoverDropdown({ triggerLabel, badgeCount, panelClassName, children }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 flex items-center gap-1"
      >
        {triggerLabel}
        {badgeCount > 0 && (
          <span className="bg-blue-600 text-white rounded-full text-[10px] px-1.5">{badgeCount}</span>
        )}
        <span>▾</span>
      </button>
      {open && (
        <div
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
