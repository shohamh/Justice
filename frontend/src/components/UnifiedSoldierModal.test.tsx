import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach } from "vitest";
import UnifiedSoldierModal from "./UnifiedSoldierModal";
import type { SoldierDTO } from "../api/soldiers";

const mockUpdateSoldierProfile = vi.fn();
const mockGetRanks = vi.fn().mockResolvedValue({ enlisted: ["טוראי"], officers: ["רסן"] });
vi.mock("../api/soldiers", () => ({
  updateSoldier: vi.fn(),
  updateSoldierProfile: (...args: unknown[]) => mockUpdateSoldierProfile(...args),
  getRanks: (...args: unknown[]) => mockGetRanks(...args),
}));
vi.mock("../api/constraints", () => ({
  listSoldierConstraints: vi.fn().mockResolvedValue([]),
  approveConstraint: vi.fn(),
  rejectConstraint: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (key === "errors.rank_track_incompatible" ? "הדרגה שנבחרה אינה תואמת למסלול השירות שנבחר" : key),
  }),
}));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { personal_number: "admin1", role: "admin", is_duty_manager: false, is_commander: false } }),
}));

const soldier: SoldierDTO = {
  id: "s1",
  personal_number: "1234567",
  full_name: "Test Soldier",
  role: "soldier",
  hierarchy_node_id: null,
  phone: "0500000000",
  must_change_password: false,
  left_at: null,
  enrolled_at: null,
  gender: null,
  is_officer: false,
  is_career: false,
  rank: null,
  bahad1_graduate: false,
  has_military_driving_license: false,
  military_driving_license_expiry: null,
  enlistment_date: null,
  mandatory_end_date: null,
  discharge_date: null,
  last_mitvahim_date: null,
  last_alal_date: null,
  telegram_linked: false,
};

function renderModal() {
  return render(
    <UnifiedSoldierModal
      soldier={soldier}
      score={null}
      nodes={[]}
      onClose={vi.fn()}
      onRefresh={vi.fn()}
      initialEditing
    />,
  );
}

describe("UnifiedSoldierModal profile save error handling", () => {
  beforeEach(() => {
    mockUpdateSoldierProfile.mockReset();
  });

  test("a rejected profile save surfaces a translated error and re-enables the save button", async () => {
    mockUpdateSoldierProfile.mockRejectedValueOnce({
      response: { data: { detail: "rank_track_incompatible: rank 'סרן' is not compatible with track 'חובה'" } },
    });
    renderModal();

    fireEvent.click(screen.getByTestId("modal-tab-profile"));
    fireEvent.click(screen.getByText("duty_config.save"));

    expect(await screen.findByText("הדרגה שנבחרה אינה תואמת למסלול השירות שנבחר")).toBeInTheDocument();
    // Button must not be stuck disabled/saving forever.
    await waitFor(() => expect(screen.getByText("duty_config.save")).not.toBeDisabled());
  });
});
