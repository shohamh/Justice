import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "../i18n";
import AuditHistoryBlock from "./AuditHistoryBlock";
import * as auditLogsApi from "../api/auditLogs";

describe("AuditHistoryBlock", () => {
  it("is collapsed by default and does not fetch until expanded", () => {
    const spy = vi.spyOn(auditLogsApi, "listAuditLogs").mockResolvedValue([]);
    render(<AuditHistoryBlock entityType="soldier_exemption" entityId="ex-1" />);
    expect(screen.queryByTestId("audit-history-list-ex-1")).not.toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches and renders entries on expand", async () => {
    vi.spyOn(auditLogsApi, "listAuditLogs").mockResolvedValue([
      {
        id: "log-1", action: "exemption.grant", actor_id: "u-1", actor_name: "יוסי כהן",
        entity_type: "soldier_exemption", entity_id: "ex-1",
        before: null, after: { soldier_id: "s-1" }, context: null,
        created_at: "2026-01-01T10:00:00Z",
      },
    ]);
    render(<AuditHistoryBlock entityType="soldier_exemption" entityId="ex-1" />);
    fireEvent.click(screen.getByTestId("audit-history-toggle-ex-1"));
    await waitFor(() => expect(screen.getByTestId("audit-history-entry-log-1")).toBeInTheDocument());
    expect(screen.getByText(/יוסי כהן/)).toBeInTheDocument();
  });

  it("shows a fallback actor label when actor_id is null", async () => {
    vi.spyOn(auditLogsApi, "listAuditLogs").mockResolvedValue([
      {
        id: "log-2", action: "constraint.cancel", actor_id: null, actor_name: null,
        entity_type: "personal_constraint", entity_id: "c-1",
        before: { status: "pending_commander" }, after: { deleted: true }, context: null,
        created_at: "2026-01-02T10:00:00Z",
      },
    ]);
    render(<AuditHistoryBlock entityType="personal_constraint" entityId="c-1" />);
    fireEvent.click(screen.getByTestId("audit-history-toggle-c-1"));
    await waitFor(() => expect(screen.getByTestId("audit-history-entry-log-2")).toBeInTheDocument());
    expect(screen.getByText(/מערכת/)).toBeInTheDocument();
  });

  it("shows an empty-state message when there is no history", async () => {
    vi.spyOn(auditLogsApi, "listAuditLogs").mockResolvedValue([]);
    render(<AuditHistoryBlock entityType="soldier_exemption" entityId="ex-2" />);
    fireEvent.click(screen.getByTestId("audit-history-toggle-ex-2"));
    await waitFor(() => expect(screen.getByTestId("audit-history-list-ex-2")).toBeInTheDocument());
    expect(screen.getByText("אין היסטוריה")).toBeInTheDocument();
  });
});
