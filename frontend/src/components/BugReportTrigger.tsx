import { useState } from "react";
import { createPortal } from "react-dom";
import { Bug } from "lucide-react";
import BugReportModal from "./BugReportModal";

export default function BugReportTrigger() {
  const [open, setOpen] = useState(false);

  return createPortal(
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="מצאתי באג"
        className="fixed top-3 left-3 text-gray-500 hover:text-indigo-600 z-[100]"
        data-testid="bug-report-trigger"
      >
        <Bug size={22} />
      </button>
      {open && <BugReportModal onClose={() => setOpen(false)} />}
    </>,
    document.body,
  );
}
