import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi } from "vitest";
import UnifiedSoldierModal from "./UnifiedSoldierModal";
import type { SoldierDTO } from "../api/soldiers";

// The panels have no QueryClient of their own; the modal must wire their
// onDecided callback to a nav-counts invalidation.
vi.mock("./ExemptionsPanel", () => ({
  default: ({ onDecided }: { onDecided?: () => void }) => (
    <button type="button" data-testid="stub-exemptions-decided" onClick={onDecided} />
  ),
}));
vi.mock("./DutyHistoryPanel", () => ({
  default: ({ onDecided }: { onDecided?: () => void }) => (
    <button type="button" data-testid="stub-history-decided" onClick={onDecided} />
  ),
}));
vi.mock("./DeputiesPanel", () => ({ default: () => null }));
vi.mock("../api/hierarchyTransfers", () => ({ createTransferRequest: vi.fn() }));
vi.mock("../api/soldiers", () => ({
  updateSoldier: vi.fn(),
  updateSoldierProfile: vi.fn(),
  submitFieldUpdate: vi.fn(),
  listFieldUpdates: vi.fn().mockResolvedValue([]),
  getRanks: vi.fn().mockResolvedValue({ enlisted: [], officers: [], officer_academic: [] }),
}));
vi.mock("../api/constraints", () => ({
  listSoldierConstraints: vi.fn().mockResolvedValue([]),
  approveConstraint: vi.fn(),
  rejectConstraint: vi.fn(),
  cancelConstraintForManager: vi.fn(),
}));
vi.mock("../api/rangeStatus", () => ({
  getSoldierRangeStatus: vi.fn().mockResolvedValue({ soldier_id: "s1", statuses: [] }),
}));
const mockT = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: mockT }) }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { personal_number: "admin1", role: "admin", is_duty_manager: false, is_commander: false } }),
}));

const soldier = {
  id: "s1", personal_number: "1234567", full_name: "Test Soldier", role: "soldier", hierarchy_node_id: null,
  phone: "0500000000", must_change_password: false, left_at: null, enrolled_at: null, gender: null,
  is_officer: false, is_career: false, rank: null, rank_track: null, bahad1_graduate: false,
  has_military_driving_license: false, military_driving_license_expiry: null, enlistment_date: null,
  mandatory_end_date: null, discharge_date: null, last_mitvahim_date: null, last_alal_date: null,
  telegram_linked: false, next_rank_date: null, next_rank_date_overridden: false,
  can_edit_rank_advancement: false, unit_join_date: null, can_request_unit_join_date: false,
} as SoldierDTO;

function renderModal(initialTab: "exemptions" | "duty_history") {
  const qc = new QueryClient();
  const spy = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <UnifiedSoldierModal soldier={soldier} score={null} onClose={vi.fn()} onRefresh={vi.fn()} initialTab={initialTab} />
    </QueryClientProvider>,
  );
  return spy;
}

describe("UnifiedSoldierModal panel decision wiring", () => {
  test("a decision in the exemptions panel invalidates the nav counts", () => {
    const spy = renderModal("exemptions");
    fireEvent.click(screen.getByTestId("stub-exemptions-decided"));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ queryKey: ["navigation", "counts"] });
  });

  test("a decision in the duty history panel invalidates the nav counts", () => {
    const spy = renderModal("duty_history");
    fireEvent.click(screen.getByTestId("stub-history-decided"));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ queryKey: ["navigation", "counts"] });
  });
});
