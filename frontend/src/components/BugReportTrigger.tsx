import { useState } from "react";
import { createPortal } from "react-dom";
import { Bug } from "lucide-react";
import { toPng } from "html-to-image";
import BugReportModal from "./BugReportModal";

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
      const dataUrl = await toPng(document.body, {
        pixelRatio: 1,
        width: window.innerWidth,
      });
      setScreenshot(dataUrl);
    } catch {
      // non-fatal: submission proceeds without a screenshot
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
        aria-label="מצאתי באג"
        className="fixed bottom-20 left-4 md:bottom-4 text-gray-500 hover:text-indigo-600 z-[100]"
        data-testid="bug-report-trigger"
        disabled={capturing}
      >
        <Bug size={22} />
      </button>
      {open && (
        <BugReportModal
          screenshot={screenshot}
          capturing={capturing}
          onClose={() => setOpen(false)}
        />
      )}
    </>,
    document.body,
  );
}
