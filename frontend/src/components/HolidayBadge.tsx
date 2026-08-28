import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { formatDate } from "../utils/formatDate";

export interface HolidayHit {
  date: string;
  name: string;
}

export default function HolidayBadge({ holidays }: { holidays: HolidayHit[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({});
  const btnRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const POPOVER_WIDTH = 224;
  const MARGIN = 8;

  useLayoutEffect(() => {
    if (!open) return;
    function reposition() {
      const btn = btnRef.current;
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      const left = Math.min(
        Math.max(rect.left, MARGIN),
        window.innerWidth - POPOVER_WIDTH - MARGIN
      );
      setPopoverStyle({ position: "fixed", top: rect.bottom + 4, left });
    }
    reposition();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (
        btnRef.current && !btnRef.current.contains(e.target as Node) &&
        popoverRef.current && !popoverRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  if (holidays.length === 0) return null;

  const label = t("holidays.badge_label", { count: holidays.length });

  return (
    <span className="relative inline-block">
      <button
        ref={btnRef}
        type="button"
        aria-label={label}
        title={label}
        data-testid="holiday-badge"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        className="inline-flex items-center gap-0.5 rounded bg-amber-100 px-1.5 py-0.5 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
      >
        📅 <span className="text-[10px] leading-4">{holidays.length}</span>
      </button>
      {open && (
        <div
          ref={popoverRef}
          role="tooltip"
          onClick={(e) => e.stopPropagation()}
          style={popoverStyle}
          className="z-[70] w-56 max-w-[calc(100vw-1rem)] rounded border border-gray-200 bg-white p-2 text-xs text-gray-700 shadow-lg dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
        >
          <p className="font-semibold mb-1">{t("holidays.calendar_legend")}</p>
          <ul className="space-y-0.5">
            {holidays.map((h) => (
              <li key={h.date}>{formatDate(h.date)} — {h.name}</li>
            ))}
          </ul>
        </div>
      )}
    </span>
  );
}
