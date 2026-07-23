import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DutyTypeFormModal from "./DutyTypeFormModal";
import {
  listExemptionTypes,
  getAllExemptionDutyTypeMaps,
  setExemptionDutyTypes,
  createDutyType,
  updateDutyType,
  updateDutyTypeRequirements,
  DutyType,
} from "../api/dutyConfig";

const TRANSLATIONS: Record<string, string> = {
  "duty_config.add": "הוסף",
  "duty_config.save": "שמור",
  "duty_config.duty_types": "סוגי תורנויות",
  "duty_config.name": "שם",
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => TRANSLATIONS[key] ?? fallback ?? key,
  }),
}));

vi.mock("../api/dutyConfig", () => ({
  listExemptionTypes: vi.fn(() => Promise.resolve([])),
  getAllExemptionDutyTypeMaps: vi.fn(() => Promise.resolve({})),
  setExemptionDutyTypes: vi.fn(() => Promise.resolve([])),
  createDutyType: vi.fn(() => Promise.resolve({ id: "dt-new" })),
  updateDutyType: vi.fn(() => Promise.resolve({ id: "dt-existing" })),
  updateDutyTypeRequirements: vi.fn((id: string) => Promise.resolve({ id })),
}));

vi.mock("../api/soldiers", () => ({
  getRanks: vi.fn(() => Promise.resolve({ enlisted: [], officers: [] })),
}));

vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn(() => Promise.resolve([])),
}));

const existingDutyType: DutyType = {
  id: "dt-existing",
  name: "משמר",
  score_per_day: "1.00",
  description: null,
  active: true,
  contact_name: null,
  contact_phone: null,
  start_time: null,
  end_time: null,
  instructions: null,
  is_external: false,
  eligible_node_ids: null,
};

beforeEach(() => {
  vi.mocked(listExemptionTypes).mockReset().mockResolvedValue([]);
  vi.mocked(getAllExemptionDutyTypeMaps).mockReset().mockResolvedValue({});
  vi.mocked(setExemptionDutyTypes).mockReset().mockResolvedValue([]);
  vi.mocked(createDutyType).mockReset().mockResolvedValue({ id: "dt-new" } as DutyType);
  vi.mocked(updateDutyType).mockReset().mockResolvedValue({ id: "dt-existing" } as DutyType);
  vi.mocked(updateDutyTypeRequirements).mockReset().mockImplementation((id: string) => Promise.resolve({ id } as DutyType));
});

describe("DutyTypeFormModal - create-only exemption review gate", () => {
  it("requires reviewing exemption types and checking the confirmation box before allowing submit", async () => {
    vi.mocked(listExemptionTypes).mockResolvedValue([
      { id: "et1", name: "רפואי", description: null, active: true },
    ]);
    render(<DutyTypeFormModal onSaved={vi.fn()} onClose={vi.fn()} />);

    const submitBtn = await screen.findByRole("button", { name: /הוסף|שמור/ });
    expect(submitBtn).toBeDisabled();

    fireEvent.click(await screen.findByLabelText(/רפואי/));
    fireEvent.click(screen.getByLabelText(/עברתי על הרשימה ומאשר/));

    expect(submitBtn).not.toBeDisabled();
  });

  it("allows submit with the confirmation box checked and zero exemption types selected", async () => {
    vi.mocked(listExemptionTypes).mockResolvedValue([
      { id: "et1", name: "רפואי", description: null, active: true },
    ]);
    render(<DutyTypeFormModal onSaved={vi.fn()} onClose={vi.fn()} />);

    const submitBtn = await screen.findByRole("button", { name: /הוסף|שמור/ });
    expect(submitBtn).toBeDisabled();

    // Don't tick the "רפואי" exemption checkbox at all — no applicable exemptions is valid.
    fireEvent.click(await screen.findByLabelText(/עברתי על הרשימה ומאשר/));

    expect(submitBtn).not.toBeDisabled();
  });

  it("does not gate submit on the review checkbox when editing an existing duty type", async () => {
    vi.mocked(listExemptionTypes).mockResolvedValue([
      { id: "et1", name: "רפואי", description: null, active: true },
    ]);
    render(<DutyTypeFormModal initial={existingDutyType} onSaved={vi.fn()} onClose={vi.fn()} />);

    const submitBtn = await screen.findByRole("button", { name: /הוסף|שמור/ });
    // No review section, no confirmation checkbox required — edit keeps today's behavior.
    expect(screen.queryByLabelText(/עברתי על הרשימה ומאשר/)).not.toBeInTheDocument();
    expect(submitBtn).not.toBeDisabled();
  });

  it("maps the selected exemption types onto the newly created duty type after submit", async () => {
    vi.mocked(listExemptionTypes).mockResolvedValue([
      { id: "et1", name: "רפואי", description: null, active: true },
    ]);
    vi.mocked(getAllExemptionDutyTypeMaps).mockResolvedValue({ et1: ["dt-old"] });

    render(<DutyTypeFormModal onSaved={vi.fn()} onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/שם/), { target: { value: "תורנות חדשה" } });
    fireEvent.change(screen.getByLabelText(/duty_config.is_external/), { target: { value: "false" } });
    fireEvent.click(await screen.findByLabelText(/רפואי/));
    fireEvent.click(screen.getByLabelText(/עברתי על הרשימה ומאשר/));

    const submitBtn = await screen.findByRole("button", { name: /הוסף|שמור/ });
    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);

    await waitFor(() => expect(createDutyType).toHaveBeenCalled());
    await waitFor(() =>
      expect(setExemptionDutyTypes).toHaveBeenCalledWith("et1", ["dt-old", "dt-new"])
    );
  });
});
