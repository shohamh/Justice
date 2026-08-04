import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from "react";
import BugReportModal from "../components/BugReportModal";

export type BugReportModalTab = "new" | "mine";

export interface OpenBugReportModalOptions {
  tab?: BugReportModalTab;
  reportId?: string;
  screenshot?: string | null;
}

interface BugReportModalContextValue {
  openBugReportModal: (opts?: OpenBugReportModalOptions) => void;
}

const BugReportModalContext = createContext<BugReportModalContextValue | null>(null);

export function useBugReportModal(): BugReportModalContextValue {
  const ctx = useContext(BugReportModalContext);
  if (!ctx) throw new Error("useBugReportModal used outside BugReportModalProvider");
  return ctx;
}

interface ModalState {
  token: number;
  tab: BugReportModalTab;
  reportId: string | null;
  screenshot: string | null;
}

export function BugReportModalProvider({ children }: { children: ReactNode }) {
  const [modal, setModal] = useState<ModalState | null>(null);
  const nextToken = useRef(0);

  const openBugReportModal = useCallback((opts: OpenBugReportModalOptions = {}) => {
    nextToken.current += 1;
    setModal({
      token: nextToken.current,
      tab: opts.tab ?? "new",
      reportId: opts.reportId ?? null,
      screenshot: opts.screenshot ?? null,
    });
  }, []);

  // External push/email links carry ?bugReport=<id> (see backend
  // _FRONTEND_PATHS) instead of a route, since the modal has no route of
  // its own. Open it once on first mount, then strip the param so it
  // doesn't re-trigger on an in-app refresh or get carried into a share.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const reportId = params.get("bugReport");
    if (!reportId) return;
    openBugReportModal({ tab: "mine", reportId });
    params.delete("bugReport");
    const newSearch = params.toString();
    const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : "") + window.location.hash;
    window.history.replaceState(window.history.state, "", newUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleClose() {
    setModal(null);
  }

  return (
    <BugReportModalContext.Provider value={{ openBugReportModal }}>
      {children}
      {modal && (
        <BugReportModal
          key={modal.token}
          screenshot={modal.screenshot}
          onClose={handleClose}
        />
      )}
    </BugReportModalContext.Provider>
  );
}
