import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import "../i18n";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";
import SwapApprovalColumns, { computeColumnStatus, SwapApprovalColumn } from "./SwapApprovalColumns";

function baseColumn(overrides: Partial<SwapApprovalColumn>): SwapApprovalColumn {
  return {
    label: "עמודה",
    commanderApprovals: [],
    dutyManagerApprovals: [],
    showDutyManagerRow: false,
    ...overrides,
  };
}

describe("computeColumnStatus", () => {
  test("neutral when nothing is applicable", () => {
    expect(computeColumnStatus(baseColumn({}))).toBe("neutral");
  });

  test("pending when soldier hasn't decided yet", () => {
    expect(computeColumnStatus(baseColumn({ soldierApproved: null }))).toBe("pending");
  });

  test("approved only when every applicable requirement is approved", () => {
    const column = baseColumn({
      soldierApproved: true,
      commanderApprovals: [{ commander_id: "c1", approved: true, approver_kind: "commander" }],
      dutyManagerApprovals: [{ commander_id: "d1", approved: false, approver_kind: "duty_manager" }],
      showDutyManagerRow: true,
    });
    // duty manager not yet approved -> whole column still pending, not approved
    expect(computeColumnStatus(column)).toBe("pending");
  });

  test("approved when soldier and all present chains are satisfied", () => {
    const column = baseColumn({
      soldierApproved: true,
      commanderApprovals: [{ commander_id: "c1", approved: true, approver_kind: "commander" }],
    });
    expect(computeColumnStatus(column)).toBe("approved");
  });

  test("rejected if any requirement was rejected, even if others are approved", () => {
    const column = baseColumn({
      soldierApproved: true,
      commanderApprovals: [{ commander_id: "c1", approved: false, rejected: true, approver_kind: "commander" }],
    });
    expect(computeColumnStatus(column)).toBe("rejected");
  });
});

describe("SwapApprovalColumns rendering", () => {
  test("renders one bullet per applicable line, labeled and separated by column", () => {
    render(
      <SoldierModalProvider>
        <SwapApprovalColumns
          columns={[
            baseColumn({
              label: "אני",
              soldierApprovalLabel: "אישור מכסה",
              soldierApproved: true,
              commanderApprovals: [{ commander_id: "c1", commander_name: "רשצ מארס", approved: false, approver_kind: "commander" }],
            }),
            baseColumn({
              label: "מבקש",
              soldierApprovalLabel: "אישור מבקש",
              soldierApproved: null,
              showDutyManagerRow: true,
              dutyManagerApprovals: [],
            }),
          ]}
        />
      </SoldierModalProvider>
    );
    expect(screen.getByText("אני")).toBeInTheDocument();
    expect(screen.getByText("מבקש")).toBeInTheDocument();
    expect(screen.getByText(/אישור מכסה/)).toBeInTheDocument();
    expect(screen.getByText(/אישור מבקש/)).toBeInTheDocument();
    expect(screen.getByText("אין אחראי תורנויות משויך למסגרת")).toBeInTheDocument();
  });
});
