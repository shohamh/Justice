import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ExemptionTypeFormModal from "./ExemptionTypeFormModal";
import * as dutyConfigApi from "../api/dutyConfig";

vi.mock("../api/dutyConfig");

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([
    { id: "dt1", name: "שמירה", score_per_day: "1", description: null, active: true } as never,
  ]);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([
    { id: "loc1", name: "שער צפוני", base: null, active: true },
  ]);
  vi.mocked(dutyConfigApi.createExemptionType).mockResolvedValue({
    id: "et1", name: "רפואי", description: null, active: true,
  });
  vi.mocked(dutyConfigApi.setExemptionDutyTypes).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.setExemptionDutyLocations).mockResolvedValue([]);
});

describe("ExemptionTypeFormModal", () => {
  it("disables submit until both duty-type and duty-location review are confirmed", async () => {
    render(<ExemptionTypeFormModal onSaved={vi.fn()} onClose={vi.fn()} />);
    const nameInput = await screen.findByLabelText(/שם/);
    fireEvent.change(nameInput, { target: { value: "רפואי" } });

    const submitBtn = screen.getByRole("button", { name: /הוסף|שמור/ });
    expect(submitBtn).toBeDisabled();

    fireEvent.click(await screen.findByLabelText(/שמירה/));
    fireEvent.click(screen.getByLabelText(/עברתי על רשימת סוגי התורנות/));
    expect(submitBtn).toBeDisabled(); // location review still missing

    fireEvent.click(screen.getByLabelText(/עברתי על רשימת המיקומים/));
    expect(submitBtn).not.toBeDisabled();
  });

  it("saves duty-type and duty-location mappings after creating the exemption type", async () => {
    const onSaved = vi.fn();
    render(<ExemptionTypeFormModal onSaved={onSaved} onClose={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText(/שם/), { target: { value: "רפואי" } });
    fireEvent.click(await screen.findByLabelText(/שמירה/));
    fireEvent.click(await screen.findByLabelText(/שער צפוני/));
    fireEvent.click(screen.getByLabelText(/עברתי על רשימת סוגי התורנות/));
    fireEvent.click(screen.getByLabelText(/עברתי על רשימת המיקומים/));

    fireEvent.click(screen.getByRole("button", { name: /הוסף|שמור/ }));

    await waitFor(() => {
      expect(dutyConfigApi.setExemptionDutyTypes).toHaveBeenCalledWith("et1", ["dt1"]);
      expect(dutyConfigApi.setExemptionDutyLocations).toHaveBeenCalledWith("et1", ["loc1"]);
      expect(onSaved).toHaveBeenCalled();
    });
  });
});
