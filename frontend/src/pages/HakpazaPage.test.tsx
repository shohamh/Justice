import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import HakpazaPage from "./HakpazaPage";
import * as soldiersApi from "../api/soldiers";
import * as assignmentsApi from "../api/assignments";
import * as dutyConfigApi from "../api/dutyConfig";

vi.mock("../api/soldiers");
vi.mock("../api/assignments");
vi.mock("../api/dutyConfig");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const soldier = { id: "sol-1", full_name: "דני כהן", rank: null } as soldiersApi.SoldierDTO;
const publishedAssignment = {
  id: "asg-1",
  soldier_id: "sol-1",
  duty_type_id: "dt-1",
  duty_location_id: "loc-1",
  start_date: "2099-01-10",
  end_date: "2099-01-15",
  status: "published",
  notes: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([soldier]);
  vi.mocked(soldiersApi.getSoldier).mockResolvedValue(soldier);
  vi.mocked(assignmentsApi.listAssignments).mockResolvedValue([publishedAssignment]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
});

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <HakpazaPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("HakpazaPage query-param pre-fill", () => {
  it("skips to step 2 with the soldier and assignment pre-selected when valid query params are present", async () => {
    renderAt("/commander/hakpaza?soldierId=sol-1&assignmentId=asg-1");
    await waitFor(() => expect(soldiersApi.getSoldier).toHaveBeenCalledWith("sol-1"));
    await waitFor(() => expect(screen.getByText("דני כהן")).toBeInTheDocument());
    // Step 2 is loaded asynchronously after the soldier and assignment queries.
    await waitFor(() => expect(screen.getByText("10.01.2099 – 14.01.2099")).toBeInTheDocument());
  });

  it("falls back to step 1 with an error when assignmentId does not match any published assignment", async () => {
    renderAt("/commander/hakpaza?soldierId=sol-1&assignmentId=does-not-exist");
    await waitFor(() => expect(soldiersApi.getSoldier).toHaveBeenCalledWith("sol-1"));
    await waitFor(() => expect(screen.getByText("לא נמצאה התורנות המבוקשת — בחר חייל ידנית")).toBeInTheDocument());
    expect(screen.getByText("שלב 1 — בחר חייל להקפיץ")).toBeInTheDocument();
  });

  it("falls back to step 1 with an error when the pre-fill soldier fetch fails (e.g. malformed response)", async () => {
    vi.mocked(soldiersApi.getSoldier).mockRejectedValue(new Error("Invalid soldier response"));
    renderAt("/commander/hakpaza?soldierId=sol-1&assignmentId=asg-1");
    await waitFor(() => expect(soldiersApi.getSoldier).toHaveBeenCalledWith("sol-1"));
    await waitFor(() => expect(screen.getByText("לא נמצאה התורנות המבוקשת — בחר חייל ידנית")).toBeInTheDocument());
    expect(screen.getByText("שלב 1 — בחר חייל להקפיץ")).toBeInTheDocument();
  });

  it("behaves as before (step 1, no pre-fill) when no query params are present", async () => {
    renderAt("/commander/hakpaza");
    await waitFor(() => expect(soldiersApi.listSoldiers).toHaveBeenCalled());
    expect(soldiersApi.getSoldier).not.toHaveBeenCalled();
    expect(screen.getByText("שלב 1 — בחר חייל להקפיץ")).toBeInTheDocument();
  });
});
