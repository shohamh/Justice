// frontend/src/contexts/SoldierModalContext.tsx
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { SoldierDTO, SoldierScoreDTO, getSoldier, getSoldierScore } from "../api/soldiers";
import UnifiedSoldierModal, { type TabKey } from "../components/UnifiedSoldierModal";
import MessageDialog from "../components/MessageDialog";

interface SoldierModalContextValue {
  openSoldierModal: (soldierId: string, onRefresh?: () => void, initialTab?: TabKey, initialHistoryTypes?: string[]) => void;
}

const SoldierModalContext = createContext<SoldierModalContextValue | null>(null);

export function useSoldierModal(): SoldierModalContextValue {
  const ctx = useContext(SoldierModalContext);
  if (!ctx) throw new Error("useSoldierModal used outside SoldierModalProvider");
  return ctx;
}

interface ModalState {
  soldier: SoldierDTO;
  score: SoldierScoreDTO | null;
  onRefresh?: () => void;
  initialTab?: TabKey;
  initialHistoryTypes?: string[];
}

export function SoldierModalProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [modal, setModal] = useState<ModalState | null>(null);
  const [opening, setOpening] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const activeOpenRequest = useRef(0);

  const openSoldierModal = useCallback(
    async (soldierId: string, onRefresh?: () => void, initialTab?: TabKey, initialHistoryTypes?: string[]) => {
      const requestId = ++activeOpenRequest.current;
      setOpening(true);
      setLoadError(false);
      try {
        const soldier = await getSoldier(soldierId).catch(() => null);
        if (activeOpenRequest.current !== requestId) return;
        if (!soldier) {
          setLoadError(true);
          return;
        }

        setModal({ soldier, score: null, onRefresh, initialTab, initialHistoryTypes });
        if (soldier.visibility !== "public") {
          void getSoldierScore(soldierId)
            .then((score) => {
              if (activeOpenRequest.current !== requestId) return;
              setModal((previous) => previous?.soldier.id === soldierId
                ? { ...previous, score }
                : previous);
            })
            .catch(() => {
              // Score is supplemental; keep the already-open detail modal usable.
            });
        }
      } finally {
        if (activeOpenRequest.current === requestId) setOpening(false);
      }
    },
    []
  );

  function handleClose() {
    activeOpenRequest.current += 1;
    setModal(null);
    setOpening(false);
  }

  async function handleRefresh() {
    if (!modal) return;
    const { onRefresh, soldier } = modal;  // extract before await
    onRefresh?.();
    const updated = await getSoldier(soldier.id).catch(() => null);
    if (updated) setModal((prev) => prev && { ...prev, soldier: updated });
  }

  return (
    <SoldierModalContext.Provider value={{ openSoldierModal }}>
      {children}
      {opening && (
        <div data-testid="soldier-modal-opening" className="fixed inset-0 bg-black/10 flex items-center justify-center z-40 pointer-events-none">
          <div className="bg-white rounded px-4 py-2 text-sm text-gray-600 shadow">טוען...</div>
        </div>
      )}
      {modal && (
        <UnifiedSoldierModal
          key={modal.soldier.id}
          soldier={modal.soldier}
          score={modal.score}
          onClose={handleClose}
          onRefresh={handleRefresh}
          initialTab={modal.initialTab}
          initialHistoryTypes={modal.initialHistoryTypes}
        />
      )}
      <MessageDialog
        open={loadError}
        title={t("common.error")}
        message={t("team.load_soldier_failed")}
        onClose={() => setLoadError(false)}
      />
    </SoldierModalContext.Provider>
  );
}
