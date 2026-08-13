import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ImportSessionReviewPage from "./ImportSessionReviewPage";
import * as importSessionsApi from "../api/importSessions";
import * as hierarchyApi from "../api/hierarchy";
import * as soldiersApi from "../api/soldiers";
import type { SessionDetail } from "../api/importSessions";

vi.mock("../api/importSessions");
// The duty_type fields modal renders SubHierarchySelector and
// DutyTypeRequirementsEditor, which fetch real hierarchy/soldiers data on
// mount (fetchTree / getRanks). Left unmocked, those calls hit jsdom's real
// XHR with no server behind it, producing unhandled rejections that surface
// (often misattributed to whatever test happens to be running next).
vi.mock("../api/hierarchy");
vi.mock("../api/soldiers");

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
      duty_locations: [],
      hierarchy: [],
      duty_types: [],
      exemption_types: [],
      system_settings: [],
      bug_reports: [],
      personal_constraints: [],
      soldier_field_updates: [],
      soldier_enrollment_requests: [],
      soldier_exemptions: [],
      exemption_requests: [],
      swap_requests: [],
      range_locations: [],
      range_events: [],
      range_assignments: [],
      soldier_range_qualifications: [],
      range_excusal_requests: [],
      parser_id: "p1",
      parser_warnings: [],
    },
    user_selections: {},
    created_links: {},
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ImportSessionReviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
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
    vi.mocked(hierarchyApi.fetchTree).mockResolvedValue([]);
    vi.mocked(soldiersApi.getRanks).mockResolvedValue({ enlisted: [], officers: [] });
  });

  it("loads and renders session data with correct tab counts", async () => {
    renderPage();

    expect(await screen.findByText("import.xlsx")).toBeInTheDocument();
    expect(screen.getByText("חיילים (2)")).toBeInTheDocument();
    expect(screen.getByText("משמרות (1)")).toBeInTheDocument();

    expect(screen.getByDisplayValue("יוסי כהן")).toBeInTheDocument();
    expect(screen.getByDisplayValue("דני לוי")).toBeInTheDocument();
  });

  it("renders an unresolved hierarchy node in red with a create button and picker combobox", async () => {
    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    const row = screen.getByDisplayValue("יוסי כהן").closest("tr")!;
    expect(within(row).getByText("פלוגה א")).toBeInTheDocument();
    expect(within(row).getByText("צור יחידה")).toBeInTheDocument();
    expect(row.querySelector('input[role="combobox"]')).toBeInTheDocument();
  });

  it("calls saveSelections when a row action select is changed to skip", async () => {
    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    const row = screen.getByDisplayValue("יוסי כהן").closest("tr")!;
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
    await screen.findByDisplayValue("יוסי כהן");

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
    await screen.findByDisplayValue("יוסי כהן");

    const row = screen.getByDisplayValue("יוסי כהן").closest("tr")!;
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
    await screen.findByDisplayValue("יוסי כהן");

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
    await screen.findByDisplayValue("יוסי כהן");

    const row = screen.getByDisplayValue("יוסי כהן").closest("tr")!;
    fireEvent.click(within(row).getByText("צור יחידה"));

    const dialog = await screen.findByTestId("add-root-node-dialog");
    expect(dialog.getAttribute("data-initial-name")).toBe("פלוגה א");
  });

  it("pre-fills the create-node dialog with the unresolved duty-shift quota name", async () => {
    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    fireEvent.click(screen.getByText("משמרות (1)"));
    await screen.findByText("שמירה");

    const createButton = await screen.findByText("צור", { selector: "button" });
    fireEvent.click(createButton);

    const dialog = await screen.findByTestId("add-root-node-dialog");
    expect(dialog.getAttribute("data-initial-name")).toBe("פלוגה א");
  });

  it("pre-fills the create-duty-type dialog with the unresolved duty-shift duty_type_name", async () => {
    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    fireEvent.click(screen.getByText("משמרות (1)"));
    await screen.findByText("שמירה");

    fireEvent.click(screen.getByText("צור סוג תורנות"));

    const dialog = await screen.findByTestId("duty-type-form-modal");
    expect(dialog.getAttribute("data-initial-name")).toBe("שמירה");
  });

  it("reparses after creating a duty type from the duty-shifts tab", async () => {
    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    fireEvent.click(screen.getByText("משמרות (1)"));
    await screen.findByText("שמירה");

    fireEvent.click(screen.getByText("צור סוג תורנות"));

    const dialog = await screen.findByTestId("duty-type-form-modal");
    fireEvent.click(within(dialog).getByText("save-duty-type"));

    await waitFor(() => {
      expect(importSessionsApi.reparseSession).toHaveBeenCalledWith("session-1");
    });
  });

  it("renders the duty_locations tab with row action controls", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.duty_locations = [
      {
        row: 2,
        action: "new",
        errors: [],
        name: "שער חדש",
        base: null,
        active: true,
        existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    fireEvent.click(screen.getByText("מיקומי תורנות (1)"));
    const row = (await screen.findByDisplayValue("שער חדש")).closest("tr")!;
    expect(within(row).getByText("אישור")).toBeInTheDocument();
  });

  it("renders a range_locations row and toggles it to skip", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_locations = [
      { row: 2, action: "new", errors: [], name: "מטווח דרומי", active: true, existing_id: null },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("מיקומי מטווח (1)"));

    const row = await screen.findByDisplayValue("מטווח דרומי");
    const select = row.closest("tr")!.querySelector("select")!;
    fireEvent.change(select, { target: { value: "skip" } });

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({ range_locations: expect.objectContaining({ "2": "skip" }) }),
      );
    });
  });

  it("renders a range_events row with editable required_count", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_events = [{
      row: 2, action: "new", errors: [],
      hierarchy_node_name: "מדור א", resolved_hierarchy_node_id: "node-1",
      range_type: "live", date: "2024-06-15",
      range_location_name: "מטווח דרומי", resolved_range_location_id: "loc-1",
      required_count: 10, reserve_count: 2, start_time: null, end_time: null,
      arrival_instructions: null, contact_name: null, contact_phone: null,
      notes: null, status: "planned",
    }];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("מטווחים (1)"));

    const countInput = await screen.findByDisplayValue("10");
    fireEvent.blur(countInput, { target: { value: "12" } });

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          _field_overrides: expect.objectContaining({
            range_events: expect.objectContaining({ "2": expect.objectContaining({ required_count: 12 }) }),
          }),
        }),
      );
    });
  });

  it("shows an unresolved range_events hierarchy_node_name in red", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_events = [{
      row: 2, action: "error", errors: ["יחידה לא מזוהה 'לא קיים'"],
      hierarchy_node_name: "לא קיים", resolved_hierarchy_node_id: null,
      range_type: "live", date: "2024-06-15",
      range_location_name: "מטווח דרומי", resolved_range_location_id: "loc-1",
      required_count: 10, reserve_count: 0, start_time: null, end_time: null,
      arrival_instructions: null, contact_name: null, contact_phone: null,
      notes: null, status: "planned",
    }];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("מטווחים (1)"));

    await screen.findByText("שגיאה");
    expect(screen.getByText("לא קיים")).toHaveClass("text-red-600");
  });

  it("renders a range_assignments row with an editable attendance_status", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_assignments = [{
      row: 2, action: "new", errors: [], warnings: [],
      personal_number: "12345", full_name: "ישראל ישראלי",
      range_type: "live", date: "2024-06-15", range_location_name: "מטווח דרומי",
      is_reserve: false, is_draft: false, attendance_status: "pending", note: null,
      resolved_soldier_id: "soldier-1", resolved_range_event_id: "event-1", matched_session_row: null,
    }];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("שיבוצי מטווח (1)"));

    await screen.findByText("ישראל ישראלי");
    const select = screen.getByText("ישראל ישראלי").closest("tr")!.querySelectorAll("select")[0];
    fireEvent.change(select, { target: { value: "present" } });

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          _field_overrides: expect.objectContaining({
            range_assignments: expect.objectContaining({ "2": expect.objectContaining({ attendance_status: "present" }) }),
          }),
        }),
      );
    });
  });

  it("renders the system_settings and bug_reports tabs with row counts", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.system_settings = [
      { row: 2, action: "new", errors: [], key: "telegram.enabled", value_json: "true", parsed_value: true },
    ];
    detail.parsed_state.bug_reports = [
      {
        row: 2, action: "new", errors: [], id: null,
        reporter_personal_number: "1234567", resolved_reporter_id: "s-1",
        description: "בעיה", severity: "low", route: "/x", status: "open",
        created_at: null, nav_history: null, audit_snapshot: null, user_snapshot: null,
        existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    expect(screen.getByText("הגדרות מערכת (1)")).toBeInTheDocument();
    expect(screen.getByText("דוחות תקלות (1)")).toBeInTheDocument();

    fireEvent.click(screen.getByText("הגדרות מערכת (1)"));
    expect(await screen.findByText("telegram.enabled")).toBeInTheDocument();

    fireEvent.click(screen.getByText("דוחות תקלות (1)"));
    expect(await screen.findByDisplayValue("בעיה")).toBeInTheDocument();
  });

  it("renders the hierarchy tab showing commander and duty manager names", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.hierarchy = [
      {
        row: 2,
        action: "new",
        errors: [],
        name: "מדור א",
        level: "group",
        parent_name: null,
        resolved_parent_id: null,
        commander_personal_number: "12345",
        commander_name: "ישראל ישראלי",
        resolved_commander_id: "uuid-1",
        duty_manager_refs: [{ ref: "23456:משה כהן", resolved_soldier_id: "uuid-2" }],
        existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    fireEvent.click(screen.getByText("היררכיה (1)"));
    expect(await screen.findByDisplayValue("מדור א")).toBeInTheDocument();
    expect(screen.getByText("ישראל ישראלי")).toBeInTheDocument();
  });

  it("renders the duty_types tab and exemption_types tab", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.duty_types = [
      {
        row: 2,
        action: "new",
        errors: [],
        name: "שמירה",
        score_per_day: "1.50",
        description: "שמירה בשער",
        active: true,
        reserve_ratio: "0.200",
        reserve_minimum: 2,
        is_external: false,
        contact_name: "דני",
        contact_phone: "050-1234567",
        start_time: "20:00",
        end_time: "06:00",
        instructions: "הצטיידות במקלע",
        resolved_eligible_node_ids: [],
        requirements: null,
        existing_id: null,
      },
    ];
    detail.parsed_state.exemption_types = [
      {
        row: 2,
        action: "new",
        errors: [],
        name: "פטור",
        description: "פטור רפואי",
        is_global: false,
        is_medical: true,
        is_commander_exemption: false,
        resolved_duty_type_ids: [],
        existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    fireEvent.click(screen.getByText("סוגי תורנות (1)"));
    expect(await screen.findByDisplayValue("שמירה")).toBeInTheDocument();

    fireEvent.click(screen.getByText("פטורים (1)"));
    expect(await screen.findByDisplayValue("פטור")).toBeInTheDocument();
  });

  it("shows full duty_type detail fields", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.duty_types = [
      {
        row: 2,
        action: "new",
        errors: [],
        name: "שמירה",
        score_per_day: "1.50",
        description: "שמירה בשער",
        active: true,
        reserve_ratio: "0.200",
        reserve_minimum: 2,
        is_external: false,
        contact_name: "דני",
        contact_phone: "050-1234567",
        start_time: "20:00",
        end_time: "06:00",
        instructions: "הצטיידות במקלע",
        resolved_eligible_node_ids: [],
        requirements: null,
        existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("סוגי תורנות (1)"));

    expect(await screen.findByDisplayValue("שמירה בשער")).toBeInTheDocument();
    expect(screen.getByDisplayValue("דני")).toBeInTheDocument();
    expect(screen.getByDisplayValue("050-1234567")).toBeInTheDocument();
    expect(screen.getByDisplayValue("הצטיידות במקלע")).toBeInTheDocument();
  });

  it("shows full exemption_type detail fields", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.exemption_types = [
      {
        row: 2,
        action: "new",
        errors: [],
        name: "פטור",
        description: "פטור רפואי",
        is_global: false,
        is_medical: true,
        is_commander_exemption: false,
        resolved_duty_type_ids: [],
        existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("פטורים (1)"));

    expect(await screen.findByDisplayValue("פטור רפואי")).toBeInTheDocument();
  });

  it("edits a duty_type field inline and saves it as a field override", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const detail = makeDraftDetail();
    detail.parsed_state.duty_types = [
      {
        row: 2, action: "new", errors: [], name: "שמירה", score_per_day: "1.50",
        description: "ישן", active: true, reserve_ratio: null, reserve_minimum: null,
        is_external: false, contact_name: null, contact_phone: null,
        start_time: null, end_time: null, instructions: null,
        resolved_eligible_node_ids: [], requirements: null, existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);
    vi.mocked(importSessionsApi.saveSelections).mockResolvedValue(undefined);
    vi.mocked(importSessionsApi.reparseSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("סוגי תורנות (1)"));

    const input = await screen.findByDisplayValue("ישן");
    fireEvent.change(input, { target: { value: "חדש" } });
    fireEvent.blur(input);
    await vi.advanceTimersByTimeAsync(600);

    expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
      "session-1",
      expect.objectContaining({
        _field_overrides: { duty_types: { "2": { description: "חדש" } } },
      }),
    );
    vi.useRealTimers();
  });

  it("opens the fields modal and edits eligible units for a duty_type row", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const detail = makeDraftDetail();
    detail.parsed_state.duty_types = [
      {
        row: 2, action: "new", errors: [], name: "שמירה", score_per_day: "1.50",
        description: null, active: true, reserve_ratio: null, reserve_minimum: null,
        is_external: false, contact_name: null, contact_phone: null,
        start_time: null, end_time: null, instructions: null,
        resolved_eligible_node_ids: [], requirements: null, existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);
    vi.mocked(importSessionsApi.saveSelections).mockResolvedValue(undefined);
    vi.mocked(importSessionsApi.reparseSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("סוגי תורנות (1)"));

    fireEvent.click(await screen.findByText("ערוך יחידות/דרישות"));
    expect(await screen.findByText("יחידות זכאיות")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("resyncs an open exemption_type fields modal to fresh data after a background reparse", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const detail = makeDraftDetail();
    detail.parsed_state.exemption_types = [
      {
        row: 2, action: "new", errors: [], name: "פטור רפואי", description: null,
        is_global: false, is_medical: true, is_commander_exemption: false,
        resolved_duty_type_ids: [], existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);
    vi.mocked(importSessionsApi.saveSelections).mockResolvedValue(undefined);
    vi.mocked(importSessionsApi.listDutyTypesForImport).mockResolvedValue([
      { id: "dt-1", name: "שמירה" },
    ]);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("פטורים (1)"));

    // open the fields modal for the row
    fireEvent.click(await screen.findByText("ערוך חל-על"));
    const checkbox = (await screen.findByText("שמירה")).closest("label")!.querySelector(
      "input[type=checkbox]",
    ) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);

    // simulate a background reparse (e.g. triggered by an inline edit elsewhere on the
    // page) returning a fresh version of the same row (matched by `row`) with the
    // duty-type association already resolved server-side
    const reparsedDetail = makeDraftDetail();
    reparsedDetail.parsed_state.exemption_types = [
      {
        row: 2, action: "new", errors: [], name: "פטור רפואי", description: null,
        is_global: false, is_medical: true, is_commander_exemption: false,
        resolved_duty_type_ids: ["dt-1"], existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.reparseSession).mockResolvedValue(reparsedDetail);

    // trigger handleReparse via the existing debounced field-override path: editing
    // the name field on the same row saves and then reparses ~500ms later
    const nameInput = screen.getByDisplayValue("פטור רפואי");
    fireEvent.blur(nameInput);
    await vi.advanceTimersByTimeAsync(600);

    await waitFor(() => expect(checkbox.checked).toBe(true));
    vi.useRealTimers();
  });

  it("does not revert the user's own edit inside an open exemption_type fields modal", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const detail = makeDraftDetail();
    detail.parsed_state.exemption_types = [
      {
        row: 2, action: "new", errors: [], name: "פטור רפואי", description: null,
        is_global: false, is_medical: true, is_commander_exemption: false,
        resolved_duty_type_ids: [], existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);
    vi.mocked(importSessionsApi.saveSelections).mockResolvedValue(undefined);
    vi.mocked(importSessionsApi.listDutyTypesForImport).mockResolvedValue([
      { id: "dt-1", name: "שמירה" },
    ]);
    // the debounced save+reparse hasn't landed yet when we assert below, so this
    // mock resolving is irrelevant to the assertion — it only matters that it
    // resolves with the SAME (still-stale) data a real in-flight reparse would
    // return before the user's edit has been persisted server-side.
    vi.mocked(importSessionsApi.reparseSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("פטורים (1)"));

    // open the fields modal for the row
    fireEvent.click(await screen.findByText("ערוך חל-על"));
    const checkbox = (await screen.findByText("שמירה")).closest("label")!.querySelector(
      "input[type=checkbox]",
    ) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);

    // simulate the user checking the box inside the modal: this fires the modal's
    // own onChange, which (1) queues a debounced field-override save+reparse and
    // (2) optimistically echoes the edit into the local dutyTypeFieldsRow-style
    // snapshot state. That local-state update must NOT be mistaken by the resync
    // effect for a genuine background reparse and reverted back to the stale value.
    fireEvent.click(checkbox);

    // assert immediately after the state update commits (before the debounce timer
    // has any chance to fire) that the edit is reflected and not reverted...
    await waitFor(() => expect(checkbox.checked).toBe(true));
    // ...and that it's still reflected after letting further render/effect cycles
    // flush, as long as we stay below the debounce threshold so no real reparse
    // has landed yet.
    await vi.advanceTimersByTimeAsync(100);
    expect(checkbox.checked).toBe(true);

    vi.useRealTimers();
  });

  it("renders full shift_template detail and allows inline edits", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const detail = makeDraftDetail();
    detail.parsed_state.shift_templates = [
      {
        row: 2, action: "new", errors: [],
        name: "שמירה לילה", duty_type_name: "שמירה", resolved_duty_type_id: "dt-1",
        duty_location_name: "שער ראשי", resolved_duty_location_id: "loc-1",
        recurrence_type: "weekly", weekdays: [1, 3],
        start_time: "20:00", end_time: "06:00", required_count: 2,
        auto_roll: false, auto_roll_until: null, duration_days: 1,
        notes: null, resolved_eligible_node_ids: [], existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);
    vi.mocked(importSessionsApi.saveSelections).mockResolvedValue(undefined);
    vi.mocked(importSessionsApi.reparseSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("תבניות (1)"));

    const countInput = await screen.findByDisplayValue("2");
    fireEvent.change(countInput, { target: { value: "5" } });
    fireEvent.blur(countInput);
    await vi.advanceTimersByTimeAsync(600);

    expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
      "session-1",
      expect.objectContaining({
        _field_overrides: { shift_templates: { "2": { required_count: 5 } } },
      }),
    );
    vi.useRealTimers();
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

  it("shows tab counts for the new range sheets", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_locations = [
      { row: 2, action: "new", errors: [], name: "מטווח דרומי", active: true, existing_id: null },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    expect(screen.getByText("מיקומי מטווח (1)")).toBeInTheDocument();
    expect(screen.getByText("מטווחים (0)")).toBeInTheDocument();
    expect(screen.getByText("שיבוצי מטווח (0)")).toBeInTheDocument();
    expect(screen.getByText("כשירויות מטווח (0)")).toBeInTheDocument();
    expect(screen.getByText("בקשות פטור ממטווח (0)")).toBeInTheDocument();
  });

  it("renders a soldier_range_qualifications row with an editable valid_until", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.soldier_range_qualifications = [{
      row: 2, action: "new", errors: [], id: null,
      soldier_personal_number: "12345", resolved_soldier_id: "soldier-1",
      range_type: "live", valid_until: "2025-01-01", existing_id: null,
    }];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("כשירויות מטווח (1)"));

    const dateInput = await screen.findByDisplayValue("01/01/2025");
    fireEvent.change(dateInput, { target: { value: "01/01/2026" } });
    fireEvent.blur(dateInput);

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          _field_overrides: expect.objectContaining({
            soldier_range_qualifications: expect.objectContaining({ "2": expect.objectContaining({ valid_until: "2026-01-01" }) }),
          }),
        }),
      );
    });
  });
});
