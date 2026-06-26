import { useState } from "react";
import { NodeDTO } from "../api/hierarchy";
import DutyManagerPortfolioDialog from "../components/DutyManagerPortfolioDialog";

export function usePortfolioDialog(nodes: NodeDTO[], onChanged: () => void) {
  const [portfolioSoldier, setPortfolioSoldier] = useState<{ id: string; name: string } | null>(null);

  return {
    open: (id: string, name: string) => setPortfolioSoldier({ id, name }),
    dialog: portfolioSoldier ? (
      <DutyManagerPortfolioDialog
        soldierId={portfolioSoldier.id}
        soldierName={portfolioSoldier.name}
        nodes={nodes}
        onClose={() => setPortfolioSoldier(null)}
        onChanged={onChanged}
      />
    ) : null,
  };
}
