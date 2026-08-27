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

vi.mock("../constants/ranks", () => ({
  isRankTrackFlexible: (rank: string) => rank === "סמר" || rank === "סגן",
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

  it("shows a per-rank service-type override only for track-flexible ranks already selected", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <DutyTypeRequirementsEditor value={{ allowed_ranks: ["רב\"ט"] }} onChange={onChange} />
    );
    expect(screen.queryByTestId(/rank-service-type-/)).not.toBeInTheDocument();

    rerender(
      <DutyTypeRequirementsEditor value={{ allowed_ranks: ["רב\"ט", "סמר"] }} onChange={onChange} />
    );
    expect(screen.getByTestId("rank-service-type-סמר")).toBeInTheDocument();
    expect(screen.queryByTestId('rank-service-type-רב"ט')).not.toBeInTheDocument();
  });

  it("setting a per-rank override writes rank_service_types without touching other ranks", () => {
    const onChange = vi.fn();
    render(
      <DutyTypeRequirementsEditor value={{ allowed_ranks: ["סמר"] }} onChange={onChange} />
    );

    fireEvent.change(screen.getByTestId("rank-service-type-סמר"), { target: { value: "קבע" } });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ rank_service_types: { סמר: ["קבע"] } })
    );
  });

  it("preselects the single global service type for an un-overridden flexible rank", () => {
    const onChange = vi.fn();
    render(
      <DutyTypeRequirementsEditor
        value={{ allowed_ranks: ["סמר"], allowed_service_types: ["קבע"] }}
        onChange={onChange}
      />
    );
    expect(screen.getByTestId("rank-service-type-סמר")).toHaveValue("קבע");
  });

  it("explicitly selecting 'no restriction' overrides the global filter, not just clears the field", () => {
    const onChange = vi.fn();
    render(
      <DutyTypeRequirementsEditor
        value={{ allowed_ranks: ["סמר"], allowed_service_types: ["קבע"] }}
        onChange={onChange}
      />
    );

    fireEvent.change(screen.getByTestId("rank-service-type-סמר"), { target: { value: "" } });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ rank_service_types: { סמר: [] } })
    );
  });
});
