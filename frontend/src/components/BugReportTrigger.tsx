import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { Bug, Loader2 } from "lucide-react";
import { snapdom } from "@zumer/snapdom";
import { reportFrontendError } from "../errorReporting";
import { useBugReportModal } from "../contexts/BugReportModalContext";
import { getMyBugReportsUnseenCount } from "../api/bugReports";
import { queryKeys } from "../queryKeys";

// snapdom rasterizes through the browser's own SVG foreignObject pipeline rather
// than repainting the DOM in JS, so it's usually near-instant — but external
// image fetches (or a pathological DOM) can still stall, so a cap remains.
// Without it, a hang here would leave the trigger disabled forever with no way
// to open the modal — capping it means capture failure (including a hang) is
// always non-fatal, matching the rest of this feature's error handling.
const CAPTURE_TIMEOUT_MS = 6000;

function createCaptureClone(scrollX: number, scrollY: number, hasAppShell: boolean) {
  // Stage our own connected, off-screen copy so computed styles remain
  // available while every scroll adjustment is confined to the representation
  // handed to the capture call, and so the capture box itself can be clipped
  // to the viewport via plain CSS (overflow: hidden) instead of a library-
  // specific crop option.
  const captureRoot = document.body.cloneNode(true) as HTMLBodyElement;
  Object.assign(captureRoot.style, {
    margin: "0",
    width: `${window.innerWidth}px`,
    height: `${window.innerHeight}px`,
    overflow: "hidden",
  });
  const host = document.createElement("div");
  host.dataset.bugReportCaptureHost = "";
  host.setAttribute("aria-hidden", "true");
  host.setAttribute("inert", "");
  Object.assign(host.style, {
    position: "fixed",
    inset: "0",
    width: `${window.innerWidth}px`,
    height: `${window.innerHeight}px`,
    overflow: "hidden",
    pointerEvents: "none",
    transform: "translateX(-100000px)",
    zIndex: "-2147483648",
  });

  if (hasAppShell) {
    const captureScrollContent = captureRoot.querySelector<HTMLElement>(
      "[data-bug-report-scroll-content]",
    );
    if (captureScrollContent) {
      captureScrollContent.style.transform = `translate(${-scrollX}px, ${-scrollY}px)`;
    }
  } else {
    // No app shell to target — the whole document scrolls, so compensate by
    // shifting the capture root itself (already clipped to viewport size above).
    captureRoot.style.transform = `translate(${-scrollX}px, ${-scrollY}px)`;
  }

  // Test hooks are not visual content and duplicate selectors while the
  // connected staging copy exists.
  captureRoot.querySelectorAll("[data-testid]").forEach((node) => {
    node.removeAttribute("data-testid");
  });

  host.append(captureRoot);
  document.body.append(host);
  return { captureRoot, remove: () => host.remove() };
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("screenshot capture timed out")), ms);
    promise.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (err) => { clearTimeout(timer); reject(err); },
    );
  });
}

// Cloning document.body and rasterizing it are both synchronous-heavy work that
// blocks the main thread, so setCapturing(true) alone isn't enough — React only
// queues the spinner render, it doesn't paint it until the browser gets a turn.
// Without yielding here first, the button would freeze on the pre-capture frame
// for the whole capture instead of showing the spinner. rAF runs just before the
// next repaint; the following setTimeout runs just after it, once that repaint
// has actually made it to the screen.
function nextPaint(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => setTimeout(resolve, 0));
  });
}

export default function BugReportTrigger() {
  const { openBugReportModal } = useBugReportModal();
  const [capturing, setCapturing] = useState(false);
  // Other panels (e.g. the notifications dropdown) close themselves via a
  // document-level "mousedown outside" listener. That listener always runs
  // before this button's "click" event (mousedown precedes click in the
  // native event order), so starting capture on click would already see the
  // panel closed/unmounted. Starting capture on mousedown instead lets us
  // read the DOM while the panel is still open, since our own mousedown
  // handler (registered on the button itself) fires before the event bubbles
  // up to the document-level listener that closes the panel. triggeredRef
  // guards against double-firing for the same interaction (mousedown then
  // click) while still supporting keyboard activation (Enter/Space fire
  // click with no preceding mousedown).
  const triggeredRef = useRef(false);

  const unseenQuery = useQuery({
    queryKey: queryKeys.myBugReportsUnseenCount(),
    queryFn: getMyBugReportsUnseenCount,
    refetchInterval: 30000,
  });
  const unseenCount = unseenQuery.data?.count ?? 0;

  async function handleClick() {
    // Freeze the current scroll position before any async work.
    const appScrollContainer = document.querySelector<HTMLElement>("[data-bug-report-scroll-container]");
    const appScrollContent = appScrollContainer?.querySelector<HTMLElement>("[data-bug-report-scroll-content]") ?? null;
    const scrollX = appScrollContainer?.scrollLeft ?? window.scrollX;
    const scrollY = appScrollContainer?.scrollTop ?? window.scrollY;
    setCapturing(true);
    let screenshot: string | null = null;
    const captureStartedAt = performance.now();
    try {
      await nextPaint();
      // dpr: 1 avoids multiplying the capture by devicePixelRatio, which is often
      // the single biggest driver of an oversized PNG on retina/high-DPI displays.
      // The capture root itself is already clamped to the viewport size (see
      // createCaptureClone), so no separate crop option is needed here — shell
      // pages shift their scroll content, non-shell pages shift the whole root.
      // Capture happens BEFORE the modal opens/mounts, so the modal's own
      // dimming overlay and empty form are never present in document.body while
      // the capture reads it — otherwise the screenshot would show the modal
      // itself instead of the page the user is reporting a bug about.
      // embedFonts defaults to false, so page fonts render via the browser's
      // already-loaded @font-face rules instead of being re-fetched and inlined —
      // avoiding the exact hang (KaTeX math fonts on formula-heavy pages) that
      // previously required skipping font embedding on the old library.
      const capture = createCaptureClone(scrollX, scrollY, appScrollContent !== null);
      try {
        const canvas = await withTimeout(
          snapdom.toCanvas(capture.captureRoot, { dpr: 1 }),
          CAPTURE_TIMEOUT_MS,
        );
        screenshot = canvas.toDataURL("image/png");
      } finally {
        capture.remove();
      }
    } catch (err) {
      // non-fatal (rejection or timeout): submission proceeds without a screenshot.
      // Still worth reporting — this catch swallows the error before it can ever
      // reach the global unhandledrejection listener, so without this call a
      // failed/timed-out capture leaves no trace anywhere (console or admin Errors).
      screenshot = null;
      reportFrontendError({
        kind: "bug-report-capture-failed",
        message: err instanceof Error ? err.message : String(err),
        stack: err instanceof Error ? err.stack : undefined,
        url: window.location.href,
        duration_ms: Math.round(performance.now() - captureStartedAt),
        user_agent: navigator.userAgent,
      });
    } finally {
      setCapturing(false);
      openBugReportModal({ tab: "new", screenshot });
      // Safety net for mousedown without a following click (e.g. the mouse
      // is released outside the button) — don't leave the trigger stuck.
      triggeredRef.current = false;
    }
  }

  function trigger() {
    if (triggeredRef.current || capturing) return;
    triggeredRef.current = true;
    void handleClick();
  }

  return createPortal(
    <button
      onMouseDown={trigger}
      onClick={() => {
        if (triggeredRef.current) {
          triggeredRef.current = false;
          return;
        }
        trigger();
      }}
      aria-label={capturing ? "מצלם צילום מסך..." : "מצאתי באג"}
      className="fixed bottom-20 left-2 md:bottom-6 md:left-6 flex flex-col items-center gap-0.5 text-gray-500 hover:text-indigo-600 z-[100] disabled:opacity-60 md:flex-row md:gap-2 md:rounded-full md:bg-indigo-600 md:px-4 md:py-3 md:text-white md:shadow-lg md:hover:bg-indigo-700 md:hover:text-white md:transition-colors"
      data-testid="bug-report-trigger"
      disabled={capturing}
    >
      {capturing
        ? <Loader2 size={22} className="animate-spin md:size-5" data-testid="bug-report-trigger-spinner" aria-hidden="true" />
        : <Bug size={22} className="md:size-5" />}
      <span className="text-[10px] leading-none md:text-sm md:font-medium md:leading-none">פידבק</span>
      {unseenCount > 0 && (
        <span
          className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center md:-top-1.5 md:-right-1.5"
          data-testid="bug-report-trigger-badge"
        >
          {unseenCount > 99 ? "99+" : unseenCount}
        </span>
      )}
    </button>,
    document.body,
  );
}
