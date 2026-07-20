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
