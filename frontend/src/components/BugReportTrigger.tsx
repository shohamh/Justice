import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { Bug, Loader2 } from "lucide-react";
import { toPng } from "html-to-image";
import { useBugReportModal } from "../contexts/BugReportModalContext";
import { getMyBugReportsUnseenCount } from "../api/bugReports";
import { queryKeys } from "../queryKeys";

// html-to-image inlines every font/image on the page as a base64 data URL before
// rasterizing, which can take a long time (or never settle at all) on content-heavy
// pages. Without a cap, a hang here would leave the trigger disabled forever with no
// way to open the modal — capping it means capture failure (including a hang) is
// always non-fatal, matching the rest of this feature's error handling.
const CAPTURE_TIMEOUT_MS = 6000;

function createCaptureClone(scrollX: number, scrollY: number, hasAppShell: boolean) {
  // This installed html-to-image release has no onClone hook. Stage our own
  // connected, off-screen copy so computed styles remain available while every
  // scroll adjustment is confined to the representation handed to toPng.
  const captureRoot = document.body.cloneNode(true) as HTMLBodyElement;
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
    try {
      // pixelRatio: 1 avoids multiplying the capture by devicePixelRatio, which is
      // often the single biggest driver of an oversized PNG on retina/high-DPI
      // displays. width/height clamp the capture to the viewport instead of the
      // full document — but clamping alone would always crop starting at the top
      // of the document (a previously-seen bug: scrolled pages showed only the
      // header). This html-to-image version has no onClone hook, so shell pages
      // use a connected off-screen copy whose marked content is shifted before
      // the library makes its own rendering clone. The live shell and fixed
      // header are untouched; non-shell pages retain the window-scroll fallback.
      // Capture happens BEFORE the modal opens/mounts, so the modal's own
      // dimming overlay and empty form are never present in document.body while
      // toPng reads it — otherwise the screenshot would show the modal itself
      // instead of the page the user is reporting a bug about.
      const capture = createCaptureClone(scrollX, scrollY, appScrollContent !== null);
      try {
        screenshot = await withTimeout(
          toPng(capture.captureRoot, {
            pixelRatio: 1,
            width: window.innerWidth,
            height: window.innerHeight,
            style: appScrollContent ? undefined : { transform: `translate(${-scrollX}px, ${-scrollY}px)` },
          }),
          CAPTURE_TIMEOUT_MS,
        );
      } finally {
        capture.remove();
      }
    } catch {
      // non-fatal (rejection or timeout): submission proceeds without a screenshot
      screenshot = null;
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
      className="fixed bottom-20 left-2 md:bottom-4 md:left-4 flex flex-col items-center gap-0.5 text-gray-500 hover:text-indigo-600 z-[100] disabled:opacity-60"
      data-testid="bug-report-trigger"
      disabled={capturing}
    >
      {capturing
        ? <Loader2 size={22} className="animate-spin" data-testid="bug-report-trigger-spinner" aria-hidden="true" />
        : <Bug size={22} />}
      <span className="text-[10px] leading-none">פידבק</span>
      {unseenCount > 0 && (
        <span
          className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center"
          data-testid="bug-report-trigger-badge"
        >
          {unseenCount > 99 ? "99+" : unseenCount}
        </span>
      )}
    </button>,
    document.body,
  );
}
