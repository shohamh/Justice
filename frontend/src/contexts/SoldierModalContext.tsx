// frontend/src/contexts/SoldierModalContext.tsx
import {
  createContext,
  useCallback,
  useContext,
  useState,
  ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { SoldierDTO, SoldierScoreDTO, getSoldier, getSoldierScore } from "../api/soldiers";
import { NodeDTO, fetchTree } from "../api/hierarchy";
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
  nodes: NodeDTO[];
  onRefresh?: () => void;
  initialTab?: TabKey;
  initialHistoryTypes?: string[];
}

export function SoldierModalProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [modal, setModal] = useState<ModalState | null>(null);
  const [opening, setOpening] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const openSoldierModal = useCallback(
    async (soldierId: string, onRefresh?: () => void, initialTab?: TabKey, initialHistoryTypes?: string[]) => {
      setOpening(true);
      try {
        const soldier = await getSoldier(soldierId).catch(() => null);
        if (!soldier) {
          setLoadError(true);
          return;
        }

        // A soldier the viewer has no read scope over comes back in "public"
        // mode (redacted fields, no score/hierarchy-dependent data) — score
        // and the full hierarchy tree are irrelevant there, so skip fetching
        // them rather than firing requests whose result is never shown.
        let score: SoldierScoreDTO | null = null;
        let nodes: NodeDTO[] = [];
        if (soldier.visibility !== "public") {
          const [scoreResult, nodesResult] = await Promise.allSettled([
            getSoldierScore(soldierId),
            fetchTree(),
          ]);
          if (scoreResult.status === "fulfilled") score = scoreResult.value;
          if (nodesResult.status === "fulfilled") nodes = nodesResult.value;
        }

        setModal({ soldier, score, nodes, onRefresh, initialTab, initialHistoryTypes });
      } finally {
        setOpening(false);
      }
    },
    []
  );

  function handleClose() {
    setModal(null);
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
        <div className="fixed inset-0 bg-black/10 flex items-center justify-center z-40 pointer-events-none">
          <div className="bg-white rounded px-4 py-2 text-sm text-gray-600 shadow">טוען...</div>
        </div>
      )}
      {modal && (
        <UnifiedSoldierModal
          key={modal.soldier.id}
          soldier={modal.soldier}
          score={modal.score}
          nodes={modal.nodes}
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
