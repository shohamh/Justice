import { useState } from "react";
import DutyManagerPortfolioDialog from "../components/DutyManagerPortfolioDialog";
import { NodeDTO } from "../api/hierarchy";

export function useDutyManagerPortfolio({ nodes, onChanged }: { nodes: NodeDTO[]; onChanged: () => void }) {
  const [portfolioSoldier, setPortfolioSoldier] = useState<{ id: string; name: string } | null>(null);

  function open(soldierId: string, name: string) {
    setPortfolioSoldier({ id: soldierId, name });
  }

  const dialog = portfolioSoldier ? (
    <DutyManagerPortfolioDialog
      soldierId={portfolioSoldier.id}
      soldierName={portfolioSoldier.name}
      nodes={nodes}
      onClose={() => setPortfolioSoldier(null)}
      onChanged={onChanged}
    />
  ) : null;

  return { open, dialog };
}
