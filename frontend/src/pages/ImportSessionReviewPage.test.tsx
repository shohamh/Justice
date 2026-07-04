import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ImportSessionReviewPage from "./ImportSessionReviewPage";
import * as importSessionsApi from "../api/importSessions";
import type { SessionDetail } from "../api/importSessions";
import * as hierarchyApi from "../api/hierarchy";

vi.mock("../api/importSessions");
vi.mock("../api/hierarchy");

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useParams: () => ({ id: "session-1" }),
  };
});

vi.mock("../components/DutyTypeFormModal", () => ({
  default: ({
    onSaved,
    onClose,
    initialName,
  }: {
    onSaved: (dt: unknown) => void;
    onClose: () => void;
    initialName?: string;
  }) => (
    <div data-testid="duty-type-form-modal" data-initial-name={initialName ?? ""}>
      <button onClick={() => onSaved({ id: "new-dt" })}>save-duty-type</button>
      <button onClick={onClose}>close-duty-type</button>
    </div>
  ),
}));

vi.mock("../components/AddRootNodeDialog", () => ({
  default: ({
    onCreated,
    onClose,
    initialName,
  }: {
    onCreated: () => void;
    onClose: () => void;
    initialName?: string;
  }) => (
    <div data-testid="add-root-node-dialog" data-initial-name={initialName ?? ""}>
      <button onClick={() => { onCreated(); onClose(); }}>create-node</button>
      <button onClick={onClose}>close-node</button>
    </div>
  ),
}));

vi.mock("../components/HierarchyNodePickerModal", () => ({
  default: ({ onPicked, onClose }: { onPicked: (id: string) => void; onClose: () => void }) => (
    <div data-testid="hierarchy-node-picker-modal">
      <button onClick={() => { onPicked("picked-node-id"); onClose(); }}>pick-node</button>
      <button onClick={onClose}>close-picker</button>
    </div>
  ),
}));

function makeDraftDetail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: "session-1",
    status: "draft",
    filename: "import.xlsx",
    parsed_state: {
      soldiers: [
        {
          row: 2,
          action: "new",
          errors: [],
          personal_number: "1234567",
          full_name: "יוסי כהן",
          rank: null,
          gender: null,
          is_officer: null,
          hierarchy_node_id: null,
          hierarchy_node_name: "פלוגה א",
          enrolled_at: null,
          enlistment_date: null,
          phone: null,
          email: null,
          existing_id: null,
        },
        {
          row: 3,
          action: "update",
          errors: [],
          personal_number: "7654321",
          full_name: "דני לוי",
          rank: null,
          gender: null,
          is_officer: null,
          hierarchy_node_id: "node-1",
          hierarchy_node_name: "פלוגה ב",
          enrolled_at: null,
          enlistment_date: null,
          phone: null,
          email: null,
          existing_id: "existing-1",
        },
      ],
      duty_shifts: [
        {
          row: 2,
          action: "new",
          errors: [],
          duty_type_name: "שמירה",
          resolved_duty_type_id: null,
          duty_location_name: "שער",
          resolved_duty_location_id: "loc-1",
          start_date: "2026-07-01",
          end_date: "2026-07-02",
          start_time: null,
          end_time: null,
          required_count: 2,
          node_quotas: [{ node_name: "פלוגה א", node_id: null, count: 1, resolved: false }],
          notes: null,
        },
      ],
      shift_templates: [
        {
          row: 2,
          action: "new",
          errors: [],
          name: "תבנית שבועית",
          duty_type_name: "שמירה",
          resolved_duty_type_id: "dt-1",
          days_of_week: [0, 3],
          required_primary: 1,
          required_reserve: 1,
        },
      ],
      parser_id: "p1",
      parser_warnings: [],
    },
    user_selections: {},
    created_links: {},
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ImportSessionReviewPage />
    </MemoryRouter>,
  );
}

describe("ImportSessionReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(makeDraftDetail());
    vi.mocked(importSessionsApi.saveSelections).mockResolvedValue(undefined);
    vi.mocked(importSessionsApi.reparseSession).mockResolvedValue(makeDraftDetail());
    vi.mocked(importSessionsApi.confirmSession).mockResolvedValue({
      created: 2,
      updated: 1,
      skipped: 0,
      errors: [],
    });
    vi.mocked(hierarchyApi.renameNode).mockResolvedValue({
      id: "picked-node-id",
      level: "team",
      name: "פלוגה א",
      parent_id: null,
      commander_id: null,
      commander_name: null,
      path_ids: [],
      duty_managers: [],
      dm_manageable: true,
    });
  });

  it("loads and renders session data with correct tab counts", async () => {
    renderPage();

    expect(await screen.findByText("import.xlsx")).toBeInTheDocument();
    expect(screen.getByText("חיילים (2)")).toBeInTheDocument();
    expect(screen.getByText("משמרות (1)")).toBeInTheDocument();
    expect(screen.getByText("תבניות (1)")).toBeInTheDocument();

    expect(screen.getByText("יוסי כהן")).toBeInTheDocument();
    expect(screen.getByText("דני לוי")).toBeInTheDocument();
  });

  it("renders an unresolved hierarchy node in red with create/change buttons", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    const row = screen.getByText("יוסי כהן").closest("tr")!;
    expect(within(row).getByText("פלוגה א")).toBeInTheDocument();
    expect(within(row).getByText("צור יחידה")).toBeInTheDocument();
    expect(within(row).getByText("שנה")).toBeInTheDocument();
  });

  it("calls saveSelections when a row action select is changed to skip", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    const row = screen.getByText("יוסי כהן").closest("tr")!;
    const select = within(row).getByRole("combobox");
    fireEvent.change(select, { target: { value: "skip" } });

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          soldiers: expect.objectContaining({ "2": "skip" }),
        }),
      );
    });
  });

  it("confirms a session and displays result counts", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    fireEvent.click(screen.getByText("אשר וייבא"));

    await waitFor(() => {
      expect(importSessionsApi.confirmSession).toHaveBeenCalledWith("session-1");
    });

    expect(await screen.findByText(/נוצרו: 2/)).toBeInTheDocument();
    expect(screen.getByText(/עודכנו: 1/)).toBeInTheDocument();
    expect(screen.getByText(/דולגו: 0/)).toBeInTheDocument();
  });

  it("renames the picked node to the unresolved soldier row name, then reparses", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    const row = screen.getByText("יוסי כהן").closest("tr")!;
    fireEvent.click(within(row).getByText("שנה"));

    expect(await screen.findByTestId("hierarchy-node-picker-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByText("pick-node"));

    await waitFor(() => {
      expect(hierarchyApi.renameNode).toHaveBeenCalledWith("picked-node-id", "פלוגה א");
    });
    await waitFor(() => {
      expect(importSessionsApi.reparseSession).toHaveBeenCalledWith("session-1");
    });
  });

  it("renames the picked node to the unresolved duty-shift quota name, then reparses", async () => {
    // Structurally identical to the soldier-row picker above: same nodePickerContext
    // state, same onPicked handler. Verifying here mainly confirms the quota row's
    // "שנה" button wires the correct unresolved name (q.node_name) into the context.
    renderPage();
    await screen.findByText("יוסי כהן");

    fireEvent.click(screen.getByText("משמרות (1)"));
    await screen.findByText("שמירה");

    const quotaButton = await screen.findByText("שנה", { selector: "button" });
    fireEvent.click(quotaButton);

    expect(await screen.findByTestId("hierarchy-node-picker-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByText("pick-node"));

    await waitFor(() => {
      expect(hierarchyApi.renameNode).toHaveBeenCalledWith("picked-node-id", "פלוגה א");
    });
    await waitFor(() => {
      expect(importSessionsApi.reparseSession).toHaveBeenCalledWith("session-1");
    });
  });

  it("pre-fills the create-node dialog with the unresolved soldier row name", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    const row = screen.getByText("יוסי כהן").closest("tr")!;
    fireEvent.click(within(row).getByText("צור יחידה"));

    const dialog = await screen.findByTestId("add-root-node-dialog");
    expect(dialog.getAttribute("data-initial-name")).toBe("פלוגה א");
  });

  it("pre-fills the create-node dialog with the unresolved duty-shift quota name", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    fireEvent.click(screen.getByText("משמרות (1)"));
    await screen.findByText("שמירה");

    const createButton = await screen.findByText("צור", { selector: "button" });
    fireEvent.click(createButton);

    const dialog = await screen.findByTestId("add-root-node-dialog");
    expect(dialog.getAttribute("data-initial-name")).toBe("פלוגה א");
  });

  it("pre-fills the create-duty-type dialog with the unresolved duty-shift duty_type_name", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    fireEvent.click(screen.getByText("משמרות (1)"));
    await screen.findByText("שמירה");

    fireEvent.click(screen.getByText("צור סוג תורנות"));

    const dialog = await screen.findByTestId("duty-type-form-modal");
    expect(dialog.getAttribute("data-initial-name")).toBe("שמירה");
  });

  it("reparses after creating a duty type from the duty-shifts tab", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    fireEvent.click(screen.getByText("משמרות (1)"));
    await screen.findByText("שמירה");

    fireEvent.click(screen.getByText("צור סוג תורנות"));

    const dialog = await screen.findByTestId("duty-type-form-modal");
    fireEvent.click(within(dialog).getByText("save-duty-type"));

    await waitFor(() => {
      expect(importSessionsApi.reparseSession).toHaveBeenCalledWith("session-1");
    });
  });

  it("hides selects and confirm button when session is not in draft status", async () => {
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(
      makeDraftDetail({ status: "confirmed" }),
    );
    renderPage();
    await screen.findByText("יוסי כהן");

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText("אשר וייבא")).not.toBeInTheDocument();
  });
});
