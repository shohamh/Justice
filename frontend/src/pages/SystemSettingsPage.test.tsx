import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "../i18n";
import { SystemSettingsContent } from "./SystemSettingsPage";
import * as systemSettingsApi from "../api/systemSettings";
import * as rankAdvancementApi from "../api/rankAdvancement";

vi.mock("../api/systemSettings", async () => {
  const actual = await vi.importActual<typeof import("../api/systemSettings")>("../api/systemSettings");
  return {
    ...actual,
    getSystemSettings: vi.fn(),
    updateSystemSettings: vi.fn(),
    exportSystemSettings: vi.fn(),
    importSystemSettings: vi.fn(),
  };
});

vi.mock("../api/rankAdvancement", async () => {
  const actual = await vi.importActual<typeof import("../api/rankAdvancement")>("../api/rankAdvancement");
  return {
    ...actual,
    getRankLadder: vi.fn(),
    updateRankAdvancementIntervals: vi.fn(),
  };
});

vi.mock("../hooks/useLevelTypes", () => ({
  useLevelTypes: () => ({
    levelTypes: [
      { id: "lt1", key: "branch", label: "חטיבה", rank: 1 },
      // "מדור" is a real hierarchy level key (production DBs use Hebrew keys)
      // and the default value of transparency.min_visible_level, so it must be
      // present for the select to render its default instead of falling back
      // to the first option.
      { id: "lt2", key: "מדור", label: "מדור", rank: 2 },
    ],
    loading: false,
    refresh: vi.fn(),
  }),
}));

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("SystemSettingsContent export/import", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(systemSettingsApi.getSystemSettings).mockResolvedValue({
      "eligibility.mitvahim_months": 6,
    });
    vi.mocked(rankAdvancementApi.getRankLadder).mockResolvedValue({
      enlisted: [
        { rank: "טוראי", months_to_next: 4, advance_on_career_entry: false },
        { rank: "רבט", months_to_next: null, advance_on_career_entry: false },
      ],
      officer: [
        { rank: "סגן", months_to_next: 12, advance_on_career_entry: false },
      ],
      officer_academic: [
        { rank: "קאב", months_to_next: null, advance_on_career_entry: false },
      ],
    });
  });

  it("renders export and import buttons", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());
    expect(screen.getByText("ייצוא הגדרות")).toBeInTheDocument();
    expect(screen.getByText("ייבוא הגדרות")).toBeInTheDocument();
  });

  it("renders the mitvachim toggle and reminder setting with fetched values", async () => {
    vi.mocked(systemSettingsApi.getSystemSettings).mockResolvedValue({
      "mitvachim.enabled": true,
      "mitvachim.reminder_days_before": 5,
    });
    renderWithProviders(<SystemSettingsContent />);
    expect(await screen.findByDisplayValue("5")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { pressed: true }).length).toBeGreaterThan(0);
  });

  it("calls exportSystemSettings when the export button is clicked", async () => {
    vi.mocked(systemSettingsApi.exportSystemSettings).mockResolvedValue({
      "eligibility.mitvahim_months": 6,
    });
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    URL.revokeObjectURL = vi.fn();

    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());

    fireEvent.click(screen.getByText("ייצוא הגדרות"));

    await waitFor(() => {
      expect(systemSettingsApi.exportSystemSettings).toHaveBeenCalled();
    });

    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("reads the selected JSON file and calls importSystemSettings with its parsed contents", async () => {
    vi.mocked(systemSettingsApi.importSystemSettings).mockResolvedValue({
      "eligibility.mitvahim_months": 9,
    });
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(
      [JSON.stringify({ "eligibility.mitvahim_months": 9 })],
      "settings.json",
      { type: "application/json" },
    );
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(systemSettingsApi.importSystemSettings).toHaveBeenCalled();
    });
    expect(vi.mocked(systemSettingsApi.importSystemSettings).mock.calls[0][0]).toEqual({
      "eligibility.mitvahim_months": 9,
    });
  });

  it("renders the hierarchy-level restriction dropdown populated from level types", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());

    expect(screen.getByText("הגבלת החלפות לרמת היררכיה")).toBeInTheDocument();
    expect(screen.getAllByText("חטיבה").length).toBeGreaterThan(0);
    expect(screen.getByText("ללא הגבלה")).toBeInTheDocument();
  });

  it("renders the transparency min-visible-level select populated from level types, defaulting to מדור", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());

    expect(screen.getByText("החל ממפקדים/אחראי תורנויות באיזה דרג ניתן לראות נתוני שקיפות במערכת")).toBeInTheDocument();
    const select = screen.getByText("החל ממפקדים/אחראי תורנויות באיזה דרג ניתן לראות נתוני שקיפות במערכת").closest("div")!.parentElement!.parentElement!.querySelector("select") as HTMLSelectElement;
    expect(select).toBeTruthy();
    // Every soldier option plus each configured hierarchy level; the field
    // defaults to מדור when no value has been saved yet.
    expect(select.value).toBe("מדור");
    const optionLabels = Array.from(select.options).map((o) => o.textContent);
    expect(optionLabels).toEqual(["כל חייל", "חטיבה", "מדור"]);
  });

  it("saves the transparency min-visible-level selection and the levels-above numbers", async () => {
    // A distinguishing value (differs from the field's default) lets us wait for the
    // fetched settings to actually land in component state before interacting —
    // otherwise the load-sync effect can fire after our click and clobber the draft.
    vi.mocked(systemSettingsApi.getSystemSettings).mockResolvedValue({
      "eligibility.mitvahim_months": 42,
    });
    vi.mocked(systemSettingsApi.updateSystemSettings).mockResolvedValue({
      "eligibility.mitvahim_months": 42,
    });
    renderWithProviders(<SystemSettingsContent />);
    await screen.findByDisplayValue("42");

    const select = screen.getByText("החל ממפקדים/אחראי תורנויות באיזה דרג ניתן לראות נתוני שקיפות במערכת").closest("div")!.parentElement!.parentElement!.querySelector("select") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "branch" } });

    const commanderInput = screen.getByText("כמה דרגים מעל תחום הפיקוד יכול מפקד לראות (לצורך השוואה)").closest("div")!.parentElement!.parentElement!.querySelector("input") as HTMLInputElement;
    fireEvent.change(commanderInput, { target: { value: "2" } });

    const dutyManagerInput = screen.getByText("כמה דרגים מעל תחום האחריות יכול אחראי תורנויות לראות (לצורך השוואה)").closest("div")!.parentElement!.parentElement!.querySelector("input") as HTMLInputElement;
    fireEvent.change(dutyManagerInput, { target: { value: "3" } });

    fireEvent.click(screen.getByText("שמור שינויים"));

    await waitFor(() => expect(systemSettingsApi.updateSystemSettings).toHaveBeenCalled());
    expect(vi.mocked(systemSettingsApi.updateSystemSettings).mock.calls[0][0]).toMatchObject({
      "eligibility.mitvahim_months": 42,
      "transparency.min_visible_level": "branch",
      "transparency.commander_levels_above": 2,
      "transparency.duty_manager_levels_above": 3,
    });
  });

  it("renders the constraints reset-period select with the three expected options, defaulting to quarter", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());

    expect(screen.getByText("תקופת איפוס ימי אילוץ")).toBeInTheDocument();
    const select = screen.getByText("תקופת איפוס ימי אילוץ").closest("div")!.parentElement!.parentElement!.querySelector("select") as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect(select.value).toBe("quarter");
    const optionLabels = Array.from(select.options).map((o) => o.textContent);
    expect(optionLabels).toEqual(["רבעון", "חצי שנה", "שנה"]);
  });

  it("shows an error banner when the selected file is not valid JSON", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["not json"], "settings.json", { type: "application/json" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText("קובץ לא תקין")).toBeInTheDocument();
    expect(systemSettingsApi.importSystemSettings).not.toHaveBeenCalled();
  });

  it("renders the rank advancement warning-days setting in its own group", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());

    expect(screen.getByText("עליית דרגה")).toBeInTheDocument();
    expect(screen.getByText("ימי אזהרה לפני עליית דרגה")).toBeInTheDocument();
  });

  it("renders the rank interval table with all ranks from both tracks, empty for unconfigured ranks", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(rankAdvancementApi.getRankLadder).toHaveBeenCalled());

    expect(await screen.findByText("מרווחי עליית דרגה")).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    const turaiRow = rows.find(r => r.textContent?.includes("טוראי"));
    expect(turaiRow?.querySelector("input")?.value).toBe("4");
    const seganRow = rows.find(r => r.textContent?.includes("סגן"));
    expect(seganRow?.querySelector("input")?.value).toBe("12");
    // רבט has no configured interval (months_to_next: null) so its input is empty.
    const rabatRow = rows.find(r => r.textContent?.includes("רבט"));
    expect(rabatRow?.querySelector("input")?.value).toBe("");
  });

  it("shows an alert and no crash when the rank ladder response is malformed", async () => {
    vi.mocked(rankAdvancementApi.getRankLadder).mockRejectedValue(new Error("Invalid rank ladder response"));
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(rankAdvancementApi.getRankLadder).toHaveBeenCalled());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("שגיאה בטעינת סולם הדרגות");
  });

  it("places the rank interval table directly after the rank advancement settings group", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(rankAdvancementApi.getRankLadder).toHaveBeenCalled());

    const headings = Array.from(document.querySelectorAll("h2"));
    const rankSettingsIndex = headings.findIndex(h => h.textContent === "עליית דרגה");
    const rankIntervalsIndex = headings.findIndex(h => h.textContent === "מרווחי עליית דרגה");
    const scoringIndex = headings.findIndex(h => h.textContent === "ניקוד");

    expect(rankSettingsIndex).toBeGreaterThanOrEqual(0);
    expect(rankIntervalsIndex).toBe(rankSettingsIndex + 1);
    expect(rankIntervalsIndex).toBeLessThan(scoringIndex);
  });

  it("saves edited rank intervals for all rows", async () => {
    vi.mocked(rankAdvancementApi.updateRankAdvancementIntervals).mockResolvedValue({
      enlisted: [
        { rank: "טוראי", months_to_next: 4, advance_on_career_entry: false },
        { rank: "רבט", months_to_next: 5, advance_on_career_entry: false },
      ],
      officer: [{ rank: "סגן", months_to_next: 12, advance_on_career_entry: false }],
      officer_academic: [{ rank: "קאב", months_to_next: null, advance_on_career_entry: false }],
    });
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(rankAdvancementApi.getRankLadder).toHaveBeenCalled());
    await screen.findByText("מרווחי עליית דרגה");

    const rows = screen.getAllByRole("row");
    const rabatRow = rows.find(r => r.textContent?.includes("רבט"));
    const rabatInput = rabatRow!.querySelector("input") as HTMLInputElement;
    fireEvent.change(rabatInput, { target: { value: "5" } });

    fireEvent.click(screen.getByText("שמור"));

    await waitFor(() => expect(rankAdvancementApi.updateRankAdvancementIntervals).toHaveBeenCalled());
    expect(vi.mocked(rankAdvancementApi.updateRankAdvancementIntervals).mock.calls[0][0]).toEqual([
      { track: "enlisted", rank: "טוראי", months_to_next: 4, advance_on_career_entry: false },
      { track: "enlisted", rank: "רבט", months_to_next: 5, advance_on_career_entry: false },
      { track: "officer", rank: "סגן", months_to_next: 12, advance_on_career_entry: false },
      { track: "officer_academic", rank: "קאב", months_to_next: null, advance_on_career_entry: false },
    ]);
  });

  it("renders a group for the academic officer track", async () => {
    renderWithProviders(<SystemSettingsContent />);

    expect(await screen.findByText("קאב")).toBeInTheDocument();
  });

  it("toggling the career-entry checkbox and saving includes it in the PUT payload", async () => {
    vi.mocked(rankAdvancementApi.updateRankAdvancementIntervals).mockResolvedValue({
      enlisted: [
        { rank: "טוראי", months_to_next: 4, advance_on_career_entry: false },
        { rank: "רבט", months_to_next: null, advance_on_career_entry: false },
      ],
      officer: [{ rank: "סגן", months_to_next: 12, advance_on_career_entry: false }],
      officer_academic: [{ rank: "קאב", months_to_next: null, advance_on_career_entry: true }],
    });
    renderWithProviders(<SystemSettingsContent />);

    const kabRow = (await screen.findByText("קאב")).closest("tr")!;
    fireEvent.click(kabRow.querySelector('input[type="checkbox"]')!);
    fireEvent.click(screen.getByText("שמור"));

    await waitFor(() => expect(rankAdvancementApi.updateRankAdvancementIntervals).toHaveBeenCalled());
    expect(vi.mocked(rankAdvancementApi.updateRankAdvancementIntervals).mock.calls[0][0]).toContainEqual({
      track: "officer_academic",
      rank: "קאב",
      months_to_next: null,
      advance_on_career_entry: true,
    });
  });

  it("career-entry tooltip icon is present with explanatory text", async () => {
    renderWithProviders(<SystemSettingsContent />);

    expect((await screen.findAllByTitle("אם מסומן, החייל יקודם אוטומטית לדרגה הבאה ברגע שהוא נכנס לשירות קבע, גם אם התאריך המתוכנן לקידום לדרגה זו עדיין לא הגיע.")).length).toBeGreaterThan(0);
  });
});
