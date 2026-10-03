import { fireEvent, render, screen } from "@testing-library/react";
import HelpModal from "./HelpModal";
import { fetchTree } from "../api/hierarchy";
import { listTemplates, type ShiftTemplate } from "../api/shiftTemplates";

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../api/scoring", () => ({ getBurdenShareBreakdown: vi.fn() }));
vi.mock("../api/dutyConfig", () => ({ listDutyTypes: vi.fn() }));

vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn(() => Promise.resolve([
    { id: "n1", level: "unit", name: "פלוגה א", parent_id: null, commander_id: null, commander_name: null, path_ids: ["n1"], duty_managers: [], dm_manageable: false, can_edit: false, children: [
      { id: "n2", level: "team", name: "כיתה 1", parent_id: "n1", commander_id: null, commander_name: null, path_ids: ["n1", "n2"], duty_managers: [], dm_manageable: false, can_edit: false },
    ] },
  ])),
}));
vi.mock("../api/shiftTemplates", () => ({
  listTemplates: vi.fn(() => Promise.resolve([
    { id: "t1", name: "שמירה", duty_type_id: "d1", duty_location_id: "l1", recurrence_type: "daily", weekdays: [], duration_days: 1, start_time: "00:00", end_time: "23:59", required_count: 1, active: true, auto_roll: false, auto_roll_until: null, notes: null, eligible_node_ids: ["n1"] },
  ])),
}));

vi.mock("./HierarchyNodePickerModal", () => ({
  default: ({ onPicked }: { onPicked: (id: string, name: string, path?: string[], pathIds?: string[]) => void }) => (
    <div role="dialog" aria-label="Hierarchy picker test double">
      <button type="button" onClick={() => onPicked("n2", "Team 1", ["Platoon A", "Team 1"], ["n1", "n2"])}>
        Pick nested node
      </button>
      <button type="button" onClick={() => onPicked("n3", "Other node", ["Other node"], ["n3"])}>
        Pick unrelated node
      </button>
    </div>
  ),
}));

function setUser(role: "soldier" | "commander" | "duty_manager" | "admin", overrides: Partial<{ is_commander: boolean; is_duty_manager: boolean }> = {}) {
  mockUseAuth.mockReturnValue({
    user: { id: "u1", role, is_commander: false, is_duty_manager: false, ...overrides },
  });
}

function makeTemplate(eligible_node_ids: string[] | null | undefined): ShiftTemplate {
  return {
    id: "t1", name: "Template", duty_type_id: "d1", duty_location_id: "l1", recurrence_type: "daily",
    weekdays: [], duration_days: 1, start_time: "00:00", end_time: "23:59", required_count: 1,
    active: true, auto_roll: false, auto_roll_until: null, notes: null,
    eligible_node_ids: eligible_node_ids as string[] | null,
  };
}

describe("HelpModal tab visibility", () => {
  it("hides Approvals and Import tabs from a plain soldier", () => {
    setUser("soldier");
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    expect(screen.queryByText(/אישורים/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ייבוא/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "🔄 החלפות" })).toBeInTheDocument();
  });

  it("shows Approvals but not Import to a commander", () => {
    setUser("commander", { is_commander: true });
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    expect(screen.getByText(/אישורים/)).toBeInTheDocument();
    expect(screen.queryByText(/ייבוא/)).not.toBeInTheDocument();
  });

  it("shows Import to a duty manager", () => {
    setUser("duty_manager", { is_duty_manager: true });
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    expect(screen.getByText(/ייבוא/)).toBeInTheDocument();
  });

  it("shows every tab to admin", () => {
    setUser("admin");
    render(<HelpModal onClose={() => {}} gimelimEnabled />);
    expect(screen.getByText(/אישורים/)).toBeInTheDocument();
    expect(screen.getByText(/ייבוא/)).toBeInTheDocument();
    expect(screen.getByText(/גימלים/)).toBeInTheDocument();
  });
});

it("shows corrected gimelim reason-visibility copy and undocumented-behavior callouts", () => {
  setUser("admin");
  render(<HelpModal onClose={() => {}} gimelimEnabled initialTab="gimelim" />);
  expect(screen.getByText(/מנהל תורנויות או מפקד שבתחום אחריותם/)).toBeInTheDocument();
});

it("Approvals tab explains each approval type for a commander", () => {
  setUser("commander", { is_commander: true });
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="approvals" />);
  expect(screen.getByText(/בקשות החלפה/)).toBeInTheDocument();
  expect(screen.getByText(/בקשות פטור/)).toBeInTheDocument();
});

it("opens the lazy hierarchy picker and accepts a matching ancestor path", async () => {
  vi.mocked(listTemplates).mockResolvedValue([makeTemplate(["n1"])]);
  setUser("duty_manager", { is_duty_manager: true });
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="hierarchy" />);

  expect(fetchTree).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("eligibility-open-picker"));
  fireEvent.click(screen.getByRole("button", { name: "Pick nested node" }));
  expect(screen.getByTestId("eligibility-selected-path")).toHaveTextContent(/Platoon A.*Team 1/);
  expect(screen.getByRole("button", { name: /Platoon A.*Team 1/ })).toBeInTheDocument();
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "t1" } });
  expect(await screen.findByText((_text, element) => Boolean(element?.className.includes("text-green-700")))).toBeInTheDocument();
});

it.each([
  ["unrelated configured node IDs", ["n3"]],
  ["an empty configured scope", []],
])("marks the selected node ineligible for %s", async (_description, eligibleNodeIds) => {
  vi.mocked(listTemplates).mockResolvedValue([makeTemplate(eligibleNodeIds)]);
  setUser("duty_manager", { is_duty_manager: true });
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="hierarchy" />);

  fireEvent.click(screen.getByTestId("eligibility-open-picker"));
  fireEvent.click(screen.getByRole("button", { name: "Pick nested node" }));
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "t1" } });
  expect(await screen.findByText((_text, element) => Boolean(element?.className.includes("text-red-600")))).toBeInTheDocument();
});

it.each([null, undefined])("treats an unrestricted template scope as eligible (%s)", async (eligibleNodeIds) => {
  vi.mocked(listTemplates).mockResolvedValue([makeTemplate(eligibleNodeIds)]);
  setUser("duty_manager", { is_duty_manager: true });
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="hierarchy" />);

  fireEvent.click(screen.getByTestId("eligibility-open-picker"));
  fireEvent.click(screen.getByRole("button", { name: "Pick nested node" }));
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "t1" } });
  expect(await screen.findByText((_text, element) => Boolean(element?.className.includes("text-green-700")))).toBeInTheDocument();
});

it("hides template controls and template requests from a plain soldier", () => {
  vi.mocked(listTemplates).mockClear();
  setUser("soldier");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="hierarchy" />);
  expect(screen.getByTestId("eligibility-open-picker")).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(listTemplates).not.toHaveBeenCalled();
});

it("expands a swap step's detail on click and collapses on second click", () => {
  setUser("soldier");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="swaps" />);
  const step = screen.getByText(/חייל מגיש בקשת החלפה/);
  expect(screen.queryByText(/הבקשה יכולה להיות פתוחה/)).not.toBeInTheDocument();
  fireEvent.click(step);
  expect(screen.getByText(/הבקשה יכולה להיות פתוחה/)).toBeInTheDocument();
  fireEvent.click(step);
  expect(screen.queryByText(/הבקשה יכולה להיות פתוחה/)).not.toBeInTheDocument();
});

it("Hakpaza tab is visible to commander, hidden from soldier", () => {
  setUser("commander", { is_commander: true });
  const { unmount } = render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="hakpaza" />);
  expect(screen.getByRole("button", { name: /הקפצה פיקודית/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /הקפצה פיקודית/ })).toBeInTheDocument();

  unmount();
  setUser("soldier");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
  expect(screen.queryByRole("button", { name: /הקפצה פיקודית/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /הקפצה פיקודית/ })).not.toBeInTheDocument();
});

it("Import tab is visible to duty_manager, hidden from commander", () => {
  setUser("duty_manager", { is_duty_manager: true });
  const { rerender } = render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="import" />);
  expect(screen.getByText(/ייבוא מקובץ אקסל/)).toBeInTheDocument();
  setUser("commander", { is_commander: true });
  rerender(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
  expect(screen.queryByText(/ייבוא מקובץ אקסל/)).not.toBeInTheDocument();
});

it("fairness tab recomputes burden_share live when the what-if slider changes", async () => {
  const { getBurdenShareBreakdown } = await import("../api/scoring");
  (getBurdenShareBreakdown as ReturnType<typeof vi.fn>).mockResolvedValue({
    quarters: [], burden_share: "0.05", A_i: "0.20", W_i: "4.0",
  });
  setUser("soldier");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="fairness" />);
  const slider = await screen.findByLabelText("תורנויות נוספות היפותטיות");
  fireEvent.change(slider, { target: { value: "2" } });
  expect(await screen.findByText(/חלק בנטל לאחר התוספת/)).toBeInTheDocument();
});

it("fairness tab explains active days and why a new soldier's score-per-day starts high", async () => {
  const { getBurdenShareBreakdown } = await import("../api/scoring");
  (getBurdenShareBreakdown as ReturnType<typeof vi.fn>).mockResolvedValue({
    quarters: [], burden_share: "0.05", A_i: "0.20", W_i: "4.0",
  });
  setUser("soldier");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="fairness" />);
  expect(await screen.findByText(/מה זה "ימים פעילים"/)).toBeInTheDocument();
  expect(screen.getByText(/חייל שבדיוק הצטרף/)).toBeInTheDocument();
});

it("Algorithm tab shows draft/publish mode section only for canPlan roles", () => {
  setUser("soldier");
  const { rerender } = render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="algorithm" />);
  expect(screen.queryByText(/מצב פרסום ישיר/)).not.toBeInTheDocument();
  setUser("duty_manager", { is_duty_manager: true });
  rerender(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="algorithm" />);
  expect(screen.getByText(/מצב פרסום ישיר/)).toBeInTheDocument();
});

it("shows the scoring tab to a plain soldier", () => {
  setUser("soldier");
  render(<HelpModal onClose={() => {}} />);
  expect(screen.getByText("🏅 ניקוד")).toBeInTheDocument();
});

it("scoring tab lists duty types with their score_per_day", async () => {
  setUser("soldier");
  const { listDutyTypes } = await import("../api/dutyConfig");
  (listDutyTypes as ReturnType<typeof vi.fn>).mockResolvedValue([
    { id: "1", name: "שמירה", score_per_day: "1.50", description: "שמירה בשער", active: true },
    { id: "2", name: "ישן", score_per_day: "0.50", description: null, active: false },
  ]);
  render(<HelpModal onClose={() => {}} initialTab="scoring" />);
  expect(await screen.findByText("שמירה")).toBeInTheDocument();
  expect(screen.getByText("1.50")).toBeInTheDocument();
  expect(screen.getByText("ישן")).toBeInTheDocument();
});

it("scoring tab's fairness mention is a link that switches to the fairness tab", async () => {
  setUser("soldier");
  const { listDutyTypes } = await import("../api/dutyConfig");
  (listDutyTypes as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  render(<HelpModal onClose={() => {}} initialTab="scoring" />);

  fireEvent.click(screen.getByTestId("scoring-tab-fairness-link"));

  expect(screen.getByText("הוגנות ושקיפות")).toBeInTheDocument();
});

it("Deep Dive worked example toggles between assignment A and B instead of showing both at once", () => {
  setUser("admin");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="deep" />);
  expect(screen.getByText(/שיבוץ א׳/)).toBeInTheDocument();
  expect(screen.queryByText(/סה"כ = 520,000/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("שיבוץ ב׳ (גרוע יותר)"));
  expect(screen.getByText(/סה"כ = 520,000/)).toBeInTheDocument();
  expect(screen.queryByText(/סה"כ = 213,333/)).not.toBeInTheDocument();
});
