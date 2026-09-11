import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from "react";
import BugReportModal from "../components/BugReportModal";
import { useAuth } from "../auth/AuthContext";

export type BugReportModalTab = "new" | "mine";

export interface OpenBugReportModalOptions {
  tab?: BugReportModalTab;
  reportId?: string;
  screenshot?: string | null;
  // When true, the modal renders a "capturing..." placeholder instead of the
  // fallback "couldn't capture" message until setBugReportScreenshot is
  // called for this same open's token — lets the modal open (and be used)
  // immediately while a slow capture still runs in the background.
  screenshotPending?: boolean;
}

interface BugReportModalContextValue {
  // Returns the token identifying this open, so a caller doing an async
  // capture afterward can later push the result via setBugReportScreenshot
  // without racing a close/reopen in between.
  openBugReportModal: (opts?: OpenBugReportModalOptions) => number;
  setBugReportScreenshot: (token: number, screenshot: string | null) => void;
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
  screenshotPending: boolean;
}

export function BugReportModalProvider({ children }: { children: ReactNode }) {
  const { loggedIn } = useAuth();
  const [modal, setModal] = useState<ModalState | null>(null);
  const nextToken = useRef(0);
  const consumedBugReportParam = useRef(false);

  const openBugReportModal = useCallback((opts: OpenBugReportModalOptions = {}) => {
    nextToken.current += 1;
    const token = nextToken.current;
    setModal({
      token,
      tab: opts.tab ?? "new",
      reportId: opts.reportId ?? null,
      screenshot: opts.screenshot ?? null,
      screenshotPending: opts.screenshotPending ?? false,
    });
    return token;
  }, []);

  // Guarded by token so a capture that resolves after the modal was closed
  // (or replaced by a newer open) can't overwrite a different open's state.
  const setBugReportScreenshot = useCallback((token: number, screenshot: string | null) => {
    setModal((prev) => (prev && prev.token === token ? { ...prev, screenshot, screenshotPending: false } : prev));
  }, []);

  // External push/email links carry ?bugReport=<id> (see backend
  // _FRONTEND_PATHS) instead of a route, since the modal has no route of
  // its own. Wait until the user is actually logged in before consuming it
  // — this provider sits above the router (including the login page), so
  // opening the modal or stripping the param before auth resolves would
  // show a broken (401) modal over the login form and then lose the link
  // for good once the param is gone.
  useEffect(() => {
    if (!loggedIn || consumedBugReportParam.current) return;
    const params = new URLSearchParams(window.location.search);
    const reportId = params.get("bugReport");
    if (!reportId) return;
    consumedBugReportParam.current = true;
    openBugReportModal({ tab: "mine", reportId });
    params.delete("bugReport");
    const newSearch = params.toString();
    const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : "") + window.location.hash;
    window.history.replaceState(window.history.state, "", newUrl);
  }, [loggedIn, openBugReportModal]);

  function handleClose() {
    setModal(null);
  }

  return (
    <BugReportModalContext.Provider value={{ openBugReportModal, setBugReportScreenshot }}>
      {children}
      {modal && (
        <BugReportModal
          key={modal.token}
          screenshot={modal.screenshot}
          screenshotPending={modal.screenshotPending}
          initialTab={modal.tab}
          initialReportId={modal.reportId}
          onClose={handleClose}
        />
      )}
    </BugReportModalContext.Provider>
  );
}
