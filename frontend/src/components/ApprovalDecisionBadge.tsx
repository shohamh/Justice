import { useState } from "react";

/** Click-to-reveal decision detail badge shared by ApprovalStageIcons (two-step
 * commander/duty-manager approval) and DirectCommanderApproval (ancestor-chain
 * approval) — both rendered an identical fixed-position details box under a
 * ✓/✗/… symbol before this was extracted, so consolidating here keeps their
 * look and behavior (not the popover-anchored positioning `Tooltip` uses)
 * from drifting apart again. */
export default function ApprovalDecisionBadge({
  symbol, label, title, testId, details, colorClass,
}: {
  symbol: string;
  label?: string;
  title?: string;
  testId?: string;
  details?: string;
  colorClass: string;
}) {
  const [open, setOpen] = useState(false);
  const [detailsTop, setDetailsTop] = useState<number | null>(null);

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        className={`inline-flex items-center gap-0.5 text-xs font-bold ${colorClass}`}
        title={title ?? label}
        aria-label={title ?? label}
        data-testid={testId}
        aria-expanded={open}
        onClick={(event) => (details ? setOpen((v) => {
          const next = !v;
          setDetailsTop(next ? event.currentTarget.getBoundingClientRect().bottom + 4 : null);
          return next;
        }) : undefined)}
      >
        {symbol}
        {label && <span className="font-normal">{label}</span>}
      </button>
      {open && details && (
        <span
          role="status"
          data-testid="approval-decision-details"
          style={{ top: detailsTop ?? 0, left: "50%", transform: "translateX(-50%)" }}
          className="fixed z-50 w-[calc(100vw-1rem)] max-w-[20rem] whitespace-normal break-words rounded bg-gray-900 px-2 py-1 text-right text-xs text-white shadow-lg"
        >
          {details}
        </span>
      )}
    </span>
  );
}
