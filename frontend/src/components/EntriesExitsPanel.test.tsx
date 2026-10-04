import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import EntriesExitsPanel from "./EntriesExitsPanel";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";
import type { SoldierWithStatus } from "../api/commanderDashboard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("../api/hierarchyTransfers", () => ({
  createTransferRequest: vi.fn().mockResolvedValue({ id: "t1", status: "pending" }),
}));
vi.mock("../api/soldiers", () => ({ softDeleteSoldier: vi.fn(), updateSoldier: vi.fn() }));
vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn().mockResolvedValue([
    { id: "n1", name: "Node One", parent_id: null },
  ]),
}));
vi.mock("./HierarchyNodePickerModal", () => ({
  default: ({ onClose, onPicked }: {
    onClose: () => void;
    onPicked: (nodeId: string, nodeName: string, path?: string[]) => void;
  }) => (
    <div role="dialog" aria-label="hierarchy picker test">
      <button type="button" data-testid="choose-move-destination" onClick={() => onPicked("n1", "Node One", ["Root", "Node One"])}>choose destination</button>
      <button type="button" onClick={onClose}>close picker</button>
    </div>
  ),
}));
vi.mock("../api/exemptions", () => ({ grantExemption: vi.fn() }));
vi.mock("../api/dutyConfig", () => ({ listExemptionTypes: vi.fn().mockResolvedValue([]) }));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("EntriesExitsPanel - move flow", () => {
  it("defers the hierarchy picker until the move selector is opened without requesting the full tree", async () => {
    const { fetchTree } = await import("../api/hierarchy");
    const soldier = {
      id: "s1",
      personal_number: "123",
      full_name: "test",
      role: "soldier",
      hierarchy_node_id: null,
      status: "active",
      cumulative_score: "0",
      normalised_score: "0",
      enrolled_at: "2026-01-01",
      left_at: null,
    } satisfies SoldierWithStatus;

    render(
      <SoldierModalProvider>
        <EntriesExitsPanel soldiers={[soldier]} onRefresh={() => {}} />
      </SoldierModalProvider>,
    );
    await act(async () => {
      await Promise.resolve();
    });

    expect(fetchTree).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "hierarchy picker test" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("command_dashboard.move"));
    expect(screen.queryByRole("dialog", { name: "hierarchy picker test" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("move-select-destination"));
    expect(screen.getByRole("dialog", { name: "hierarchy picker test" })).toBeInTheDocument();
    expect(fetchTree).not.toHaveBeenCalled();
  });

  it("keeps the selected destination after cancel and reopen, then submits it through the transfer request flow", async () => {
    const { createTransferRequest } = await import("../api/hierarchyTransfers");
    const { updateSoldier } = await import("../api/soldiers");
    const soldier = {
      id: "s1",
      personal_number: "123",
      full_name: "test",
      role: "soldier",
      hierarchy_node_id: null,
      status: "active",
      cumulative_score: "0",
      normalised_score: "0",
      enrolled_at: "2026-01-01",
      left_at: null,
    } satisfies SoldierWithStatus;
    const onRefresh = vi.fn();
    render(
      <SoldierModalProvider>
        <EntriesExitsPanel soldiers={[soldier]} onRefresh={onRefresh} />
      </SoldierModalProvider>,
    );

    fireEvent.click(screen.getAllByText("command_dashboard.move")[0]);
    fireEvent.click(screen.getByTestId("move-select-destination"));
    fireEvent.click(screen.getByTestId("choose-move-destination"));

    expect(screen.getByTestId("move-selected-destination")).toHaveTextContent("Root / Node One");
    fireEvent.click(screen.getByText("command_dashboard.cancel"));
    expect(screen.queryByText("command_dashboard.move_soldier - test")).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByText("command_dashboard.move")[0]);
    expect(screen.getByTestId("move-selected-destination")).toHaveTextContent("Root / Node One");

    fireEvent.click(screen.getByText("command_dashboard.move_confirm"));

    await waitFor(() => expect(createTransferRequest).toHaveBeenCalledWith("s1", "n1"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(updateSoldier).not.toHaveBeenCalled();
  });
});

describe("EntriesExitsPanel - release flow", () => {
  it("clicking release opens a modal with a date field defaulting to today, then submits that date", async () => {
    const { softDeleteSoldier } = await import("../api/soldiers");
    const soldier = {
      id: "s1",
      personal_number: "123",
      full_name: "test",
      role: "soldier",
      hierarchy_node_id: null,
      status: "active",
      cumulative_score: "0",
      normalised_score: "0",
      enrolled_at: "2026-01-01",
      left_at: null,
    } satisfies SoldierWithStatus;
    const onRefresh = vi.fn();
    render(
      <SoldierModalProvider>
        <EntriesExitsPanel soldiers={[soldier]} onRefresh={onRefresh} />
      </SoldierModalProvider>
    );

    fireEvent.click(screen.getByText("command_dashboard.release"));

    // Local calendar day, matching the component — toISOString() is UTC and
    // differs from the local date between local midnight and the UTC offset.
    const now = new Date();
    const todayY = String(now.getFullYear());
    const todayM = String(now.getMonth() + 1).padStart(2, "0");
    const todayD = String(now.getDate()).padStart(2, "0");
    const dateInput = await screen.findByTestId("release-date-input");
    expect(dateInput).toHaveValue(`${todayD}/${todayM}/${todayY}`);

    expect(softDeleteSoldier).not.toHaveBeenCalled();

    fireEvent.change(dateInput, { target: { value: "10/02/2026" } });
    fireEvent.click(screen.getByText("command_dashboard.confirm_release"));

    await waitFor(() => expect(softDeleteSoldier).toHaveBeenCalledWith("s1", "2026-02-10"));
    expect(onRefresh).toHaveBeenCalled();
  });
});

describe("EntriesExitsPanel - exemption flow", () => {
  it("disables the exempt-confirm button until a reason is entered", async () => {
    const soldier = {
      id: "s1",
      personal_number: "123",
      full_name: "test",
      role: "soldier",
      hierarchy_node_id: null,
      status: "active",
      cumulative_score: "0",
      normalised_score: "0",
      enrolled_at: "2026-01-01",
      left_at: null,
    } satisfies SoldierWithStatus;

    render(
      <SoldierModalProvider>
        <EntriesExitsPanel soldiers={[soldier]} onRefresh={() => {}} />
      </SoldierModalProvider>,
    );
    await act(async () => {
      await Promise.resolve();
    });

    fireEvent.click(screen.getByText("command_dashboard.exempt"));
    const confirmButton = screen.getAllByText("command_dashboard.exempt")[1];
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getByTestId("exempt-reason"), { target: { value: "מחלה" } });
    expect(confirmButton).not.toBeDisabled();
  });
});
