import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ImportSessionReviewPage from "./ImportSessionReviewPage";
import * as importSessionsApi from "../api/importSessions";
import type { SessionDetail } from "../api/importSessions";

vi.mock("../api/importSessions");

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
      shift_templates: [],
      assignments: [],
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
    vi.mocked(importSessionsApi.listDutyTypesForImport).mockResolvedValue([]);
    vi.mocked(importSessionsApi.listNodesForImport).mockResolvedValue([]);
  });

  it("loads and renders session data with correct tab counts", async () => {
    renderPage();

    expect(await screen.findByText("import.xlsx")).toBeInTheDocument();
    expect(screen.getByText("חיילים (2)")).toBeInTheDocument();
    expect(screen.getByText("משמרות (1)")).toBeInTheDocument();

    expect(screen.getByText("יוסי כהן")).toBeInTheDocument();
    expect(screen.getByText("דני לוי")).toBeInTheDocument();
  });

  it("renders an unresolved hierarchy node in red with a create button and picker combobox", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    const row = screen.getByText("יוסי כהן").closest("tr")!;
    expect(within(row).getByText("פלוגה א")).toBeInTheDocument();
    expect(within(row).getByText("צור יחידה")).toBeInTheDocument();
    expect(row.querySelector('input[role="combobox"]')).toBeInTheDocument();
  });

  it("calls saveSelections when a row action select is changed to skip", async () => {
    renderPage();
    await screen.findByText("יוסי כהן");

    const row = screen.getByText("יוסי כהן").closest("tr")!;
    const select = row.querySelector("select")!;
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

  it("picking an existing node for the unresolved soldier row saves a name mapping and reparses", async () => {
    // Both the soldier row and the duty-shift quota below share the excel name
    // "פלוגה א", so picking here has sameNameCount === 2 and surfaces the
    // PendingPickBanner rather than applying immediately.
    vi.mocked(importSessionsApi.listNodesForImport).mockResolvedValue([
      { id: "node-99", name: "פלוגה א", parent_id: null },
    ]);

    renderPage();
    await screen.findByText("יוסי כהן");

    const row = screen.getByText("יוסי כהן").closest("tr")!;
    const input = row.querySelector('input[role="combobox"]') as HTMLInputElement;
    // The node lookup for the picker loads asynchronously in a separate effect;
    // retry focusing until its items have arrived and the option renders.
    await waitFor(() => {
      fireEvent.focus(input);
      expect(screen.getByRole("option", { name: /פלוגה א/ })).toBeInTheDocument();
    });
    fireEvent.pointerUp(within(screen.getByRole("option", { name: /פלוגה א/ })).getByRole("button"));

    fireEvent.click(await screen.findByText("רק שורה זו"));

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          _name_mappings: expect.objectContaining({
            hierarchy_node: expect.objectContaining({
              by_row: expect.objectContaining({ "soldiers:2": "node-99" }),
            }),
          }),
        }),
      );
    });
    await waitFor(() => {
      expect(importSessionsApi.reparseSession).toHaveBeenCalledWith("session-1");
    });
  });

  it("picking an existing node for the unresolved duty-shift quota saves a name mapping and reparses", async () => {
    vi.mocked(importSessionsApi.listNodesForImport).mockResolvedValue([
      { id: "node-99", name: "פלוגה א", parent_id: null },
    ]);

    renderPage();
    await screen.findByText("יוסי כהן");

    fireEvent.click(screen.getByText("משמרות (1)"));
    await screen.findByText("שמירה");

    const quotaRow = screen.getByText("שמירה").closest("tr")!;
    // The row has two pickers: duty-type (first) and node quota (second) — the
    // duty_type_name here is also unresolved, so both combobox inputs are present.
    const input = quotaRow.querySelectorAll('input[role="combobox"]')[1] as HTMLInputElement;
    await waitFor(() => {
      fireEvent.focus(input);
      expect(screen.getByRole("option", { name: /פלוגה א/ })).toBeInTheDocument();
    });
    fireEvent.pointerUp(within(screen.getByRole("option", { name: /פלוגה א/ })).getByRole("button"));

    fireEvent.click(await screen.findByText("רק שורה זו"));

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          _name_mappings: expect.objectContaining({
            hierarchy_node: expect.objectContaining({
              by_row: expect.objectContaining({ "duty_shifts:2:פלוגה א": "node-99" }),
            }),
          }),
        }),
      );
    });
    await waitFor(() => {
      expect(importSessionsApi.reparseSession).toHaveBeenCalledWith("session-1");
    });
  });

  it("shows the row's error messages next to an error status chip", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.soldiers[0] = {
      ...detail.parsed_state.soldiers[0],
      action: "error",
      errors: ["personal_number is required", "full_name is required"],
    };
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByText("שגיאה");

    expect(screen.getByText("personal_number is required")).toBeInTheDocument();
    expect(screen.getByText("full_name is required")).toBeInTheDocument();
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
