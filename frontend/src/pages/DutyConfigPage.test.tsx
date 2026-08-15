import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DutyConfigContent } from "./DutyConfigPage";
import * as dutyConfigApi from "../api/dutyConfig";
import * as soldiersApi from "../api/soldiers";

vi.mock("../api/dutyConfig");
vi.mock("../api/soldiers");
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(soldiersApi.getRanks).mockResolvedValue({ enlisted: [], officers: [], officer_academic: [] });
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([
    { id: "loc1", name: "שער צפוני", base: null, active: true },
  ]);
  vi.mocked(dutyConfigApi.listExemptionTypes).mockResolvedValue([
    { id: "et1", name: "רפואי", description: null, is_global: false, is_medical: true, is_commander_exemption: false, active: true },
  ]);
  vi.mocked(dutyConfigApi.getAllExemptionDutyTypeMaps).mockResolvedValue({});
  vi.mocked(dutyConfigApi.getAllExemptionDutyLocationMaps).mockResolvedValue({ et1: ["loc1"] });
  vi.mocked(dutyConfigApi.setExemptionDutyLocations).mockResolvedValue(["loc1"]);
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <DutyConfigContent />
    </QueryClientProvider>
  );
}

describe("DutyConfigPage - exemption-duty-location matrix", () => {
  it("shows existing duty-location mappings as checked and toggling calls setExemptionDutyLocations", async () => {
    renderPage();
    const checkbox = await screen.findByTestId("loc-map-רפואי-שער צפוני");
    expect(checkbox).toBeChecked();

    fireEvent.click(checkbox);

    await waitFor(() => {
      expect(dutyConfigApi.setExemptionDutyLocations).toHaveBeenCalledWith("et1", []);
    });
  });
});
