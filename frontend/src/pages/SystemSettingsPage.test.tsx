import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "../i18n";
import { SystemSettingsContent } from "./SystemSettingsPage";
import * as systemSettingsApi from "../api/systemSettings";

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

vi.mock("../hooks/useLevelTypes", () => ({
  useLevelTypes: () => ({ levelTypes: [{ id: "lt1", key: "branch", label: "חטיבה", rank: 1 }], loading: false, refresh: vi.fn() }),
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
  });

  it("renders export and import buttons", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());
    expect(screen.getByText("ייצוא הגדרות")).toBeInTheDocument();
    expect(screen.getByText("ייבוא הגדרות")).toBeInTheDocument();
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

  it("renders a checkbox per level type for the transparency visibility setting, unchecked by default", async () => {
    renderWithProviders(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());

    expect(screen.getByText("אילו רמות פיקוד רשאיות לצפות בדף השקיפות (בנוסף לאחראי תורנויות ומנהל)")).toBeInTheDocument();
    const checkbox = screen.getAllByText("חטיבה").find((el) => el.closest("label"))!.closest("label")!.querySelector("input[type=checkbox]") as HTMLInputElement;
    expect(checkbox).not.toBeChecked();
  });

  it("saves the transparency setting as an array of selected level keys, and as [] when unchecked", async () => {
    // A distinguishing value (differs from the field's default) lets us wait for the
    // fetched settings to actually land in component state before interacting —
    // otherwise the load-sync effect can fire after our click and clobber the draft.
    vi.mocked(systemSettingsApi.getSystemSettings).mockResolvedValue({
      "eligibility.mitvahim_months": 42,
    });
    vi.mocked(systemSettingsApi.updateSystemSettings).mockResolvedValue({
      "eligibility.mitvahim_months": 42,
      "transparency.visible_commander_levels": ["branch"],
    });
    renderWithProviders(<SystemSettingsContent />);
    await screen.findByDisplayValue("42");

    const checkbox = screen.getAllByText("חטיבה").find((el) => el.closest("label"))!.closest("label")!.querySelector("input[type=checkbox]") as HTMLInputElement;

    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText("שמור שינויים"));

    await waitFor(() => expect(systemSettingsApi.updateSystemSettings).toHaveBeenCalled());
    expect(vi.mocked(systemSettingsApi.updateSystemSettings).mock.calls[0][0]).toMatchObject({
      "transparency.visible_commander_levels": ["branch"],
    });

    // Unchecking again should reproduce an empty array, not drop the key or leave it truthy.
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText("שמור שינויים"));
    await waitFor(() => expect(systemSettingsApi.updateSystemSettings).toHaveBeenCalledTimes(2));
    expect(vi.mocked(systemSettingsApi.updateSystemSettings).mock.calls[1][0]).toMatchObject({
      "transparency.visible_commander_levels": [],
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
});
