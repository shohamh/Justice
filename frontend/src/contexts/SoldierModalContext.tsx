// frontend/src/contexts/SoldierModalContext.tsx
import {
  createContext,
  useCallback,
  useContext,
  useState,
  ReactNode,
} from "react";
import { SoldierDTO, SoldierScoreDTO, getSoldier, getSoldierScore } from "../api/soldiers";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import UnifiedSoldierModal from "../components/UnifiedSoldierModal";

interface SoldierModalContextValue {
  openSoldierModal: (soldierId: string, onRefresh?: () => void) => void;
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
}

export function SoldierModalProvider({ children }: { children: ReactNode }) {
  const [modal, setModal] = useState<ModalState | null>(null);

  const openSoldierModal = useCallback(
    async (soldierId: string, onRefresh?: () => void) => {
      const [soldier, score, nodes] = await Promise.allSettled([
        getSoldier(soldierId),
        getSoldierScore(soldierId),
        fetchTree(),
      ]);

      if (soldier.status === "rejected") return;

      setModal({
        soldier: (soldier as PromiseFulfilledResult<SoldierDTO>).value,
        score:
          score.status === "fulfilled"
            ? (score as PromiseFulfilledResult<SoldierScoreDTO>).value
            : null,
        nodes:
          nodes.status === "fulfilled"
            ? (nodes as PromiseFulfilledResult<NodeDTO[]>).value
            : [],
        onRefresh,
      });
    },
    []
  );

  function handleClose() {
    setModal(null);
  }

  async function handleRefresh() {
    if (!modal) return;
    modal.onRefresh?.();
    const updated = await getSoldier(modal.soldier.id).catch(() => null);
    if (updated) setModal((prev) => prev && { ...prev, soldier: updated });
  }

  return (
    <SoldierModalContext.Provider value={{ openSoldierModal }}>
      {children}
      {modal && (
        <UnifiedSoldierModal
          soldier={modal.soldier}
          // @ts-ignore
          score={modal.score}
          nodes={modal.nodes}
          onClose={handleClose}
          onRefresh={handleRefresh}
        />
      )}
    </SoldierModalContext.Provider>
  );
}
