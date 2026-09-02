import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import ExemptionsPanel from "./ExemptionsPanel";
import * as dutyConfigApi from "../api/dutyConfig";
import * as exemptionsApi from "../api/exemptions";
import { validateFileSignature } from "../utils/fileValidation";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

let mockUser = {
  id: "u-manager",
  role: "duty_manager",
  can_apply_commander_exemption_immediately: true,
};

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: mockUser }),
}));

vi.mock("../api/dutyConfig", () => ({
  listExemptionTypes: vi.fn(() => Promise.resolve([
    { id: "et-regular", name: "פטור רפואי", active: true, is_medical: true, is_commander_exemption: false },
    { id: "et-official", name: "פטור רשמי", active: true, is_medical: false, is_commander_exemption: false },
    { id: "et-commander", name: "פטור פיקודי", active: true, is_medical: false, is_commander_exemption: true },
  ])),
  getAllExemptionDutyTypeMaps: vi.fn(() => Promise.resolve({})),
  listDutyTypes: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/exemptions", () => ({
  listExemptions: vi.fn(() => Promise.resolve([
    { id: "ex1", soldier_id: "abc", exemption_type_id: null, start_date: "2020-01-01", end_date: null, reason: null, granted_by: null, revoke_reason: null, revoked_by_name: null },
    { id: "ex2", soldier_id: "abc", exemption_type_id: null, start_date: "2020-01-01", end_date: "2020-01-10", reason: null, granted_by: null, revoke_reason: null, revoked_by_name: null },
  ])),
  logExemptionForSoldier: vi.fn(() => Promise.resolve({
    id: "req-new",
    soldier_id: "abc",
    soldier_name: "X",
    node_name: null,
    exemption_type_id: "et-official",
    start_date: "2026-08-30",
    end_date: null,
    reason: "סיבה רגילה",
    status: "approved",
    commander_approved_by: null,
    commander_approved_at: null,
    waiting_on: null,
    decided_by: null,
    decided_at: null,
    requested_at: "2026-08-30T00:00:00Z",
    updated_at: "2026-08-30T00:00:00Z",
    decision_note: null,
    created_at: "2026-08-30T00:00:00Z",
    files: [],
    nearest_commander: null,
    nearest_duty_manager: null,
    can_approve_commander_step: false,
    can_approve_duty_manager_step: false,
  })),
  revokeExemption: vi.fn(() => Promise.resolve()),
  grantCommanderExemption: vi.fn(() => Promise.resolve()),
  escalateCommanderExemption: vi.fn(() => Promise.resolve({
    id: "req-new",
    soldier_id: "abc",
    soldier_name: "X",
    node_name: null,
    exemption_type_id: "et-official",
    start_date: "2026-08-30",
    end_date: null,
    reason: "סיבה",
    status: "pending_duty_manager",
    commander_approved_by: null,
    commander_approved_at: null,
    waiting_on: null,
    decided_by: null,
    decided_at: null,
    requested_at: "2026-08-30T00:00:00Z",
    updated_at: "2026-08-30T00:00:00Z",
    decision_note: null,
    created_at: "2026-08-30T00:00:00Z",
    files: [],
    nearest_commander: null,
    nearest_duty_manager: null,
    can_approve_commander_step: false,
    can_approve_duty_manager_step: false,
  })),
  listExemptionRequestsForSoldier: vi.fn(() => Promise.resolve([
    {
      id: "req-1",
      soldier_id: "abc",
      soldier_name: "X",
      node_name: null,
      exemption_type_id: "et-1",
      start_date: "2026-01-01",
      end_date: "2026-01-05",
      reason: "סיבה",
      status: "pending_duty_manager",
      commander_approved_by: null,
      commander_approved_at: null,
      waiting_on: null,
      decided_by: null,
      decided_at: null,
      requested_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      decision_note: null,
      created_at: "2026-01-01T00:00:00Z",
      files: [],
      nearest_commander: null,
      nearest_duty_manager: null,
      can_approve_commander_step: true,
      can_approve_duty_manager_step: true,
    },
  ])),
  approveExemptionRequestCommanderStep: vi.fn(() => Promise.resolve()),
  approveExemptionRequestDutyManagerStep: vi.fn(() => Promise.resolve()),
  rejectExemptionRequest: vi.fn(() => Promise.resolve({})),
  uploadSoldierExemptionFile: vi.fn(() => Promise.resolve({
    id: "file-1",
    file_name: "proof.pdf",
    content_type: "application/pdf",
    created_at: "2026-08-30T00:00:00Z",
  })),
  listSoldierExemptionFiles: vi.fn(() => Promise.resolve([])),
  soldierExemptionFileDownloadUrl: vi.fn((soldierId: string, exemptionId: string, fileId: string) => `/soldiers/${soldierId}/exemptions/${exemptionId}/files/${fileId}`),
}));

vi.mock("../utils/fileValidation", () => ({
  PDF_IMAGE_SIGNATURES: {},
  validateFileSignature: vi.fn(() => Promise.resolve(true)),
}));

async function selectLogExemptionType(name: string) {
  const input = screen.getByTestId("er-type");
  fireEvent.focus(input);
  const option = await screen.findByRole("button", { name });
  fireEvent.pointerDown(option);
  fireEvent.pointerUp(option);
}

async function selectGrantType(name: string) {
  const input = await screen.findByTestId("grant-type");
  fireEvent.focus(input);
  const option = await screen.findByRole("button", { name });
  fireEvent.pointerDown(option);
  fireEvent.pointerUp(option);
}

describe("ExemptionsPanel", () => {
  beforeEach(() => {
    mockUser = {
      id: "u-manager",
      role: "duty_manager",
      can_apply_commander_exemption_immediately: true,
    };
    vi.clearAllMocks();
    vi.mocked(dutyConfigApi.listExemptionTypes).mockResolvedValue([
      { id: "et-regular", name: "פטור רפואי", active: true, is_medical: true, is_commander_exemption: false },
      { id: "et-official", name: "פטור רשמי", active: true, is_medical: false, is_commander_exemption: false },
      { id: "et-commander", name: "פטור פיקודי", active: true, is_medical: false, is_commander_exemption: true },
    ]);
    vi.mocked(validateFileSignature).mockResolvedValue(true);
  });

  test("indefinite checkbox disables end-date picker", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
    const checkbox = await screen.findByTestId("grant-indefinite");
    const endInput = screen.getByTestId("grant-end");
    expect(endInput).not.toBeDisabled();
    fireEvent.click(checkbox);
    expect(endInput).toBeDisabled();
  });

  test("logs an exemption via the shared request form, requiring a file for a medical type", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);

    await selectLogExemptionType("פטור רשמי");
    fireEvent.change(screen.getByTestId("er-start"), { target: { value: "2026-08-30" } });
    fireEvent.change(screen.getByTestId("er-end"), { target: { value: "2026-08-30" } });
    fireEvent.change(screen.getByTestId("er-reason"), { target: { value: "סיבה רגילה" } });
    fireEvent.click(screen.getByTestId("er-medical-check"));

    expect(screen.getByTestId("er-submit")).toBeDisabled();

    const fileA = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], "proof-a.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByTestId("er-files"), { target: { files: [fileA] } });

    await waitFor(() => expect(screen.getByTestId("er-submit")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("er-submit"));

    await waitFor(() => {
      expect(exemptionsApi.logExemptionForSoldier).toHaveBeenCalledWith(
        "abc",
        {
          exemption_type_id: "et-official",
          start_date: "2026-08-30",
          end_date: "2026-08-30",
          reason: "סיבה רגילה",
        },
        [fileA],
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("er-reason")).toHaveValue("");
    });
    expect(screen.getByTestId("log-exemption-approved-note")).toBeInTheDocument();
  });

  test("shows who the request is waiting on when it does not fully auto-approve", async () => {
    vi.mocked(exemptionsApi.logExemptionForSoldier).mockResolvedValueOnce({
      id: "req-pending",
      soldier_id: "abc",
      soldier_name: "X",
      node_name: null,
      exemption_type_id: "et-official",
      start_date: "2026-08-30",
      end_date: null,
      reason: "סיבה רגילה",
      status: "pending_duty_manager",
      commander_approved_by: { soldier_id: "cmd-1", name: "מפקד המדור" },
      commander_approved_at: "2026-08-30T00:00:00Z",
      waiting_on: null,
      decided_by: null,
      decided_at: null,
      requested_at: "2026-08-30T00:00:00Z",
      updated_at: "2026-08-30T00:00:00Z",
      decision_note: null,
      created_at: "2026-08-30T00:00:00Z",
      files: [],
      nearest_commander: null,
      nearest_duty_manager: { id: "dm-1", name: "קצין תורנויות" },
      can_approve_commander_step: false,
      can_approve_duty_manager_step: false,
    });

    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);

    await selectLogExemptionType("פטור רשמי");
    fireEvent.change(screen.getByTestId("er-start"), { target: { value: "2026-08-30" } });
    fireEvent.change(screen.getByTestId("er-end"), { target: { value: "2026-08-30" } });
    fireEvent.change(screen.getByTestId("er-reason"), { target: { value: "סיבה רגילה" } });
    fireEvent.click(screen.getByTestId("er-submit"));

    const note = await screen.findByTestId("log-exemption-pending-note");
    expect(note.textContent).toContain("קצין תורנויות");
  });

  test("shows exemption request history with a pending duty-manager approve button for a duty manager viewer", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
    const row = await screen.findByTestId("exemption-request-row-req-1");
    expect(row).toBeTruthy();
    expect(screen.getByTestId("exemption-request-approve-req-1")).toBeTruthy();
  });

  test("shows an indicative error when approving a request from the soldier modal fails", async () => {
    vi.mocked(exemptionsApi.approveExemptionRequestDutyManagerStep).mockRejectedValueOnce({
      response: { status: 500, data: { detail: "internal_error" } },
    });
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);

    fireEvent.click(await screen.findByTestId("exemption-request-approve-req-1"));

    expect(await screen.findByTestId("exemption-request-action-error")).toHaveTextContent("שגיאה באישור הבקשה");
  });

  test("hides the duty-manager-step approve button for a commander-only viewer", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={false} />);
    await screen.findByTestId("exemption-request-row-req-1");
    expect(screen.queryByTestId("exemption-request-approve-req-1")).toBeNull();
  });

  test("shows a day-count badge next to expired and request-history date ranges", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);

    const pastList = await screen.findByTestId("exemptions-list-past");
    expect(within(pastList).getByText("(10 ימים)")).toBeTruthy();

    const requestRow = await screen.findByTestId("exemption-request-row-req-1");
    expect(within(requestRow).getByText("(5 ימים)")).toBeTruthy();
  });

  test("revoking an exemption requires a reason and calls revokeExemption with it", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
    const revokeButton = await screen.findByTestId("revoke-ex1");
    fireEvent.click(revokeButton);

    const confirmButton = screen.getByTestId("reason-modal-confirm");
    expect(confirmButton).toBeDisabled();

    const textarea = screen.getByTestId("reason-modal-textarea");
    fireEvent.change(textarea, { target: { value: "לא רלוונטי" } });
    expect(confirmButton).not.toBeDisabled();

    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(exemptionsApi.revokeExemption).toHaveBeenCalledWith("abc", "ex1", "לא רלוונטי");
    });
  });

  test("renders the exemption-request date range in start-then-end order, not reversed", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
    const row = await screen.findByTestId("exemption-request-row-req-1");
    expect(row.textContent).toMatch(/01\.01\.2026[\s\S]*05\.01\.2026/);
  });

  test("the revoke confirmation shows the extreme-action warning styling", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={false} />);
    const revokeButton = await screen.findByTestId("revoke-ex1");
    fireEvent.click(revokeButton);
    const warning = await screen.findByText((content, element) => {
      return element?.tagName.toLowerCase() === "p" && content.includes("exemptions.revoke_active_warning");
    });
    expect(warning.className).toContain("amber");
  });

  test("commander grant is blocked until the confirmation checkbox is ticked", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);

    await selectGrantType("פטור פיקודי");
    fireEvent.change(screen.getByTestId("grant-start"), { target: { value: "2026-08-30" } });
    fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
    fireEvent.click(screen.getByTestId("commander-exemption-submit"));

    const modalConfirm = screen.getByTestId("commander-exemption-confirm");
    expect(modalConfirm).toBeDisabled();
    fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
    expect(modalConfirm).not.toBeDisabled();
  });

  test("plain commander grant calls grantCommanderExemption when escalate is off", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);

    await selectGrantType("פטור פיקודי");
    fireEvent.change(screen.getByTestId("grant-start"), { target: { value: "2026-08-30" } });
    fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
    fireEvent.click(screen.getByTestId("commander-exemption-submit"));
    fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
    fireEvent.click(screen.getByTestId("commander-exemption-confirm"));

    await waitFor(() => expect(exemptionsApi.grantCommanderExemption).toHaveBeenCalledWith("abc", expect.objectContaining({
      exemption_type_id: "et-commander",
      reason: "סיבה",
    })));
    expect(exemptionsApi.escalateCommanderExemption).not.toHaveBeenCalled();
  });

  test("escalate on with apply-immediately calls escalateCommanderExemption with apply_immediately true", async () => {
    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);

    await selectGrantType("פטור פיקודי");
    fireEvent.change(screen.getByTestId("grant-start"), { target: { value: "2026-08-30" } });
    fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
    fireEvent.click(screen.getByTestId("commander-exemption-escalate-checkbox"));
    fireEvent.click(screen.getByTestId("commander-exemption-apply-immediately-checkbox"));
    fireEvent.click(screen.getByTestId("commander-exemption-submit"));
    fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
    fireEvent.click(screen.getByTestId("commander-exemption-confirm"));

    await waitFor(() => expect(exemptionsApi.escalateCommanderExemption).toHaveBeenCalledWith(
      "abc",
      expect.objectContaining({
        official_exemption_type_id: "et-regular",
        commander_exemption_type_id: "et-commander",
        apply_immediately: true,
      }),
    ));
  });

  test("hides the non-escalate path and apply-immediately checkbox when immediate apply is not allowed", async () => {
    mockUser = {
      id: "u-commander",
      role: "commander",
      can_apply_commander_exemption_immediately: false,
    };

    render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={false} />);
    await selectGrantType("פטור פיקודי");

    expect(screen.queryByTestId("commander-exemption-escalate-checkbox")).not.toBeInTheDocument();
    expect(screen.queryByTestId("commander-exemption-apply-immediately-checkbox")).not.toBeInTheDocument();
  });
});
