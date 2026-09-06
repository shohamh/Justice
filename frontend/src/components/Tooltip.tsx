import { CSSProperties, ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";

const POPOVER_WIDTH = 224; // px, matches w-56
const MARGIN = 8;

interface Props {
  /** Bold heading line at the top of the popover (optional — omit for a plain body). */
  label?: ReactNode;
  /** Popover body content, shown when the trigger is hovered or clicked/tapped. */
  content: ReactNode;
  /** Plain-text fallback shown via the native `title` attribute, so hovering the
   * trigger with a mouse gets the browser's own tooltip even before any click. */
  title?: string;
  /** Accessible name for the trigger. */
  ariaLabel?: string;
  /** Extra classes merged onto the trigger element (in addition to the shared base style). */
  className?: string;
  /** The trigger's own visual content (an icon, badge text, "?", etc). */
  children: ReactNode;
  /** Render the trigger as a plain focusable span instead of a <button> — use when a
   * literal <button> can't be nested where this is placed (e.g. inside another
   * button or a <button>-only ancestor). Both variants open the same popover. */
  as?: "button" | "span";
  testId?: string;
}

/**
 * Shared tooltip: a small trigger that shows explanatory content both on hover
 * (via the native `title` attribute) and on click/tap (via a positioned
 * popover) — for touch devices and anyone tapping instead of hovering. Not
 * for use on a real action button (whose click should perform the button's
 * own action, not toggle a tooltip) — those should keep a plain `title`.
 */
export default function Tooltip({ label, content, title, ariaLabel, className, children, as = "button", testId }: Props) {
  const [open, setOpen] = useState(false);
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({});
  const triggerRef = useRef<HTMLElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open) return;
    function reposition() {
      const trigger = triggerRef.current;
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
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
        triggerRef.current && !triggerRef.current.contains(e.target as Node) &&
        popoverRef.current && !popoverRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
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

  const toggle = (e: { stopPropagation: () => void }) => {
    e.stopPropagation();
    setOpen((o) => !o);
  };

  const sharedProps = {
    "aria-label": ariaLabel,
    title,
    className,
    "data-testid": testId,
    onClick: toggle as React.MouseEventHandler,
  };

  return (
    <span className="relative inline-block">
      {as === "span" ? (
        <span
          {...sharedProps}
          ref={triggerRef as React.RefObject<HTMLSpanElement>}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); }
          }}
        >
          {children}
        </span>
      ) : (
        <button type="button" {...sharedProps} ref={triggerRef as React.RefObject<HTMLButtonElement>}>
          {children}
        </button>
      )}
      {open && (
        <div
          ref={popoverRef}
          role="tooltip"
          onClick={(e) => e.stopPropagation()}
          style={popoverStyle}
          className="z-[70] w-56 max-w-[calc(100vw-1rem)] whitespace-pre-line rounded border border-gray-200 bg-white p-2 text-xs text-gray-700 shadow-lg dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
        >
          {label && <p className="mb-1 font-semibold">{label}</p>}
          {content}
        </div>
      )}
    </span>
  );
}
