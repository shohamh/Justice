import { useState } from "react";
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

  async function handleClick() {
    setCapturing(true);
    setScreenshot(null);
    try {
      // pixelRatio: 1 avoids multiplying the capture by devicePixelRatio, which is
      // often the single biggest driver of an oversized PNG on retina/high-DPI
      // displays. width clamps the PNG to viewport width. Omitting height allows
      // the full document height to be captured regardless of scroll offset —
      // including height clamped to window.innerHeight caused screenshots on
      // scrolled pages to show only the header region instead of the visible content.
      // Capture happens BEFORE the modal opens/mounts, so the modal's own
      // dimming overlay and empty form are never present in document.body while
      // toPng reads it — otherwise the screenshot would show the modal itself
      // instead of the page the user is reporting a bug about.
      const dataUrl = await withTimeout(
        toPng(document.body, { pixelRatio: 1, width: window.innerWidth }),
        CAPTURE_TIMEOUT_MS,
      );
      setScreenshot(dataUrl);
    } catch {
      // non-fatal (rejection or timeout): submission proceeds without a screenshot
      setScreenshot(null);
    } finally {
      setCapturing(false);
      setOpen(true);
    }
  }

  return createPortal(
    <>
      <button
        onClick={() => { void handleClick(); }}
        aria-label={capturing ? "מצלם צילום מסך..." : "מצאתי באג"}
        className="fixed bottom-20 left-4 md:bottom-4 text-gray-500 hover:text-indigo-600 z-[100] disabled:opacity-60"
        data-testid="bug-report-trigger"
        disabled={capturing}
      >
        {capturing
          ? <Loader2 size={22} className="animate-spin" data-testid="bug-report-trigger-spinner" aria-hidden="true" />
          : <Bug size={22} />}
      </button>
      {open && <BugReportModal screenshot={screenshot} onClose={() => setOpen(false)} />}
    </>,
    document.body,
  );
}
