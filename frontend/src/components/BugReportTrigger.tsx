import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Bug, Loader2 } from "lucide-react";
import { toPng } from "html-to-image";
import BugReportModal from "./BugReportModal";

// html-to-image inlines every font/image on the page as a base64 data URL before
// rasterizing, which can take a long time (or never settle at all) on content-heavy
// pages. Without a cap, a hang here would leave the trigger disabled forever with no
// way to open the modal — capping it means capture failure (including a hang) is
// always non-fatal, matching the rest of this feature's error handling.
const CAPTURE_TIMEOUT_MS = 6000;

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
  const [open, setOpen] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [screenshot, setScreenshot] = useState<string | null>(null);
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

  async function handleClick() {
    // Freeze the current scroll position before any async work.
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    setCapturing(true);
    setScreenshot(null);
    try {
      // pixelRatio: 1 avoids multiplying the capture by devicePixelRatio, which is
      // often the single biggest driver of an oversized PNG on retina/high-DPI
      // displays. width/height clamp the capture to the viewport instead of the
      // full document — but clamping alone would always crop starting at the top
      // of the document (a previously-seen bug: scrolled pages showed only the
      // header). The clone is shifted up by the current scroll offset via
      // `style.transform` so the SVG foreignObject (which clips to width/height)
      // reveals the section of the page actually on screen, not the top of it.
      // Capture happens BEFORE the modal opens/mounts, so the modal's own
      // dimming overlay and empty form are never present in document.body while
      // toPng reads it — otherwise the screenshot would show the modal itself
      // instead of the page the user is reporting a bug about.
      const dataUrl = await withTimeout(
        toPng(document.body, {
          pixelRatio: 1,
          width: window.innerWidth,
          height: window.innerHeight,
          style: { transform: `translate(${-scrollX}px, ${-scrollY}px)` },
        }),
        CAPTURE_TIMEOUT_MS,
      );
      setScreenshot(dataUrl);
    } catch {
      // non-fatal (rejection or timeout): submission proceeds without a screenshot
      setScreenshot(null);
    } finally {
      setCapturing(false);
      setOpen(true);
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
    <>
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
      </button>
      {open && <BugReportModal screenshot={screenshot} onClose={() => setOpen(false)} />}
    </>,
    document.body,
  );
}
