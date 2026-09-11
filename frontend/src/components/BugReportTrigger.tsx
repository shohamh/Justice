import { useRef } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { Bug } from "lucide-react";
import { toPng } from "html-to-image";
import { reportFrontendError } from "../errorReporting";
import { useBugReportModal } from "../contexts/BugReportModalContext";
import { getMyBugReportsUnseenCount } from "../api/bugReports";
import { queryKeys } from "../queryKeys";

// Rasterizer history, for the next person tempted to "just make this
// faster": snapdom (SVG-foreignObject-based, no JS repaint) was tried here
// and reliably 4-10x faster — but on this app's actual duty calendar
// (FullCalendar's day-grid, multi-day events using RTL negative-offset
// absolute positioning: `left: -425px; right: 0` instead of `left/width`)
// it silently DROPPED specific real events from the capture. Confirmed live,
// pixel-by-pixel, across five different configurations: a manual clip rect,
// `clip: 'viewport'` alone, `clip: 'viewport'` + `reconcile: true`, no clip
// at all, and a manual left/right-style normalization on the offending
// elements — every one either dropped content or (no-clip) still dropped
// this specific multi-day-event pattern. html-to-image's JS-repaint approach
// does not share this failure mode (it isn't relying on the browser's own
// foreignObject layout engine to resolve that CSS pattern) and is what this
// feature shipped with originally — slower, but correct, which matters more
// for a bug-report screenshot than speed does. Capture running in the
// background after the modal is already open (see handleClick) is what
// actually fixes the original "long wait, sometimes fails" complaint; the
// library choice here is now about correctness, not speed.
const CAPTURE_TIMEOUT_MS = 20000;

function createCaptureClone(scrollX: number, scrollY: number, hasAppShell: boolean) {
  // Stage our own connected copy so computed styles remain available while
  // every scroll adjustment is confined to the representation handed to the
  // capture call, and so the capture box itself can be clipped to the
  // viewport via plain CSS (overflow: hidden) instead of a library-specific
  // crop option.
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

  // The bug-report modal itself may already be open and mounted in
  // document.body (capture now runs in the background after the modal
  // opens, not before) — drop it from the clone so the screenshot shows the
  // page being reported on, not a picture of the report form itself.
  captureRoot.querySelector("[data-bug-report-capture-exclude]")?.remove();

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

// Cloning document.body and rasterizing it are both synchronous-heavy work
// that blocks the main thread. The modal opens (and becomes usable) before
// this runs, so without yielding here first, its first frame would freeze
// instead of actually painting. rAF runs just before the next repaint; the
// following setTimeout runs just after it, once that repaint has actually
// made it to the screen.
function nextPaint(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => setTimeout(resolve, 0));
  });
}

export default function BugReportTrigger() {
  const { openBugReportModal, setBugReportScreenshot } = useBugReportModal();
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

    // Open the modal immediately — description/severity entry and even
    // submission (without a screenshot yet) all work right away — instead of
    // making the user wait out the capture (which can take tens of seconds
    // on a heavy page) before they can do anything. The capture below fills
    // the screenshot in once it's ready, via the returned token so a stale
    // result can't clobber a different modal open.
    const token = openBugReportModal({ tab: "new", screenshotPending: true });
    // Reset now rather than waiting for the (now backgrounded) capture to
    // finish — the modal's overlay covers this button immediately once
    // mounted, so nothing meaningful is gained by holding the guard longer.
    triggeredRef.current = false;

    const captureStartedAt = performance.now();
    let screenshot: string | null = null;
    try {
      await nextPaint();
      const capture = createCaptureClone(scrollX, scrollY, appScrollContent !== null);
      try {
        screenshot = await withTimeout(
          toPng(capture.captureRoot, {
            // pixelRatio: 1 avoids multiplying the capture by devicePixelRatio,
            // often the single biggest driver of an oversized PNG on retina/
            // high-DPI displays. width/height clamp the capture to the capture
            // root's own already-viewport-clamped box (belt and suspenders with
            // the CSS overflow: hidden in createCaptureClone).
            pixelRatio: 1,
            width: window.innerWidth,
            height: window.innerHeight,
            // Downloading + base64-embedding every @font-face on the page can by
            // itself take longer than the capture timeout on pages with heavy
            // custom-font usage. Fonts are already loaded in the live page, so
            // skipping re-embedding still renders real text — just via the
            // browser's already-loaded fonts instead of a self-contained embed.
            skipFonts: true,
          }),
          CAPTURE_TIMEOUT_MS,
        );
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
      setBugReportScreenshot(token, screenshot);
    }
  }

  function trigger() {
    if (triggeredRef.current) return;
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
      aria-label="מצאתי באג"
      className="fixed bottom-20 left-2 md:bottom-6 md:left-6 flex flex-col items-center gap-0.5 text-gray-500 hover:text-indigo-600 z-[100] md:flex-row md:gap-2 md:rounded-full md:bg-indigo-600 md:px-4 md:py-3 md:text-white md:shadow-lg md:hover:bg-indigo-700 md:hover:text-white md:transition-colors"
      data-testid="bug-report-trigger"
    >
      <Bug size={22} className="md:size-5" />
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
