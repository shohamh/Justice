import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import EntriesExitsPanel from "./EntriesExitsPanel";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";
import type { SoldierWithStatus } from "../api/commanderDashboard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("../api/hierarchyTransfers", () => ({
  createTransferRequest: vi.fn().mockResolvedValue({ id: "t1", status: "pending" }),
}));
vi.mock("../api/soldiers", () => ({ softDeleteSoldier: vi.fn(), updateSoldier: vi.fn() }));
vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn().mockResolvedValue([
    { id: "n1", name: "Node One", parent_id: null },
  ]),
}));
vi.mock("../api/exemptions", () => ({ grantExemption: vi.fn() }));
vi.mock("../api/dutyConfig", () => ({ listExemptionTypes: vi.fn().mockResolvedValue([]) }));

describe("EntriesExitsPanel - move flow", () => {
  it("moving a soldier creates a transfer request instead of moving them directly", async () => {
    const { createTransferRequest } = await import("../api/hierarchyTransfers");
    const { updateSoldier } = await import("../api/soldiers");
    const soldier = {
      id: "s1",
      personal_number: "123",
      full_name: "test",
      role: "soldier",
      hierarchy_node_id: null,
      status: "active",
      cumulative_score: "0",
      normalised_score: "0",
      enrolled_at: "2026-01-01",
      left_at: null,
    } satisfies SoldierWithStatus;
    render(
      <SoldierModalProvider>
        <EntriesExitsPanel soldiers={[soldier]} onRefresh={() => {}} />
      </SoldierModalProvider>
    );

    fireEvent.click(screen.getAllByText("command_dashboard.move")[0]);

    const combobox = await screen.findByRole("combobox");
    fireEvent.focus(combobox);
    const option = await screen.findByText("Node One");
    fireEvent.pointerDown(option);
    fireEvent.pointerUp(option);

    fireEvent.click(screen.getByText("command_dashboard.move_confirm"));

    await waitFor(() => expect(createTransferRequest).toHaveBeenCalledWith("s1", "n1"));
    expect(updateSoldier).not.toHaveBeenCalled();
  });
});
