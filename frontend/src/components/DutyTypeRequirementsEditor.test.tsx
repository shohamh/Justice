import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DutyTypeRequirementsEditor from "./DutyTypeRequirementsEditor";
import { updateDutyTypeRequirements } from "../api/dutyConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../api/dutyConfig", () => ({
  updateDutyTypeRequirements: vi.fn(() => Promise.resolve({})),
}));

vi.mock("../api/soldiers", () => ({
  getRanks: vi.fn(() => Promise.resolve({ enlisted: ["רב\"ט"], officers: ["סג\"ם"], officer_academic: [] })),
}));

const dutyType = {
  id: "d1",
  name: "duty1",
  requirements: { officers_allowed: true },
} as never;

describe("DutyTypeRequirementsEditor", () => {
  beforeEach(() => {
    vi.mocked(updateDutyTypeRequirements).mockClear();
  });

  it("renders in uncontrolled mode and saves via the API", async () => {
    const onSaved = vi.fn();
    render(<DutyTypeRequirementsEditor dutyType={dutyType} onSaved={onSaved} />);

    const maleCheckbox = await screen.findByLabelText(/soldier_profile.gender_male/i);
    fireEvent.click(maleCheckbox);

    const saveButton = screen.getByRole("button", { name: /eligibility.save/i });
    fireEvent.click(saveButton);

    await waitFor(() => expect(updateDutyTypeRequirements).toHaveBeenCalled());
    expect(onSaved).toHaveBeenCalled();
  });

  it("renders in controlled mode without calling the API", async () => {
    const onChange = vi.fn();
    render(<DutyTypeRequirementsEditor value={{ officers_allowed: true }} onChange={onChange} />);

    const maleCheckbox = await screen.findByLabelText(/soldier_profile.gender_male/i);
    fireEvent.click(maleCheckbox);

    expect(onChange).toHaveBeenCalled();
    expect(updateDutyTypeRequirements).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /eligibility.save/i })).not.toBeInTheDocument();
  });
});
