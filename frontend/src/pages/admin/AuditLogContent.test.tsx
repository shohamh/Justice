import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi, beforeEach, test, expect } from "vitest";
import "../../i18n";
import AuditLogContent from "./AuditLogContent";
import { AdminAuditLogPageDTO } from "../../api/adminAuditLogs";

vi.mock("../../api/adminAuditLogs", () => ({
  listAdminAuditLogs: vi.fn(),
}));

import { listAdminAuditLogs } from "../../api/adminAuditLogs";
const mockList = vi.mocked(listAdminAuditLogs);

function makePage(overrides: Partial<AdminAuditLogPageDTO> = {}): AdminAuditLogPageDTO {
  return {
    items: [
      {
        id: "log-1",
        created_at: "2026-08-23T10:00:00Z",
        actor_id: "actor-1",
        actor_name: "דני כהן",
        action: "exemption.grant",
        entity_type: "soldier_exemption",
        entity_id: "ent-1",
        entity_exists: true,
        entity_link: "/planning/config",
        before: { status: "pending_commander" },
        after: { status: "approved", exemption_type: "פטור מבחן" },
        context: { reason: "בקשה אושרה" },
      },
      {
        id: "log-2",
        created_at: "2026-08-23T09:00:00Z",
        actor_id: null,
        actor_name: null,
        action: "duty_config.update",
        entity_type: "duty_type",
        entity_id: "ent-2",
        entity_exists: false,
        entity_link: "/planning/config",
        before: null,
        after: null,
        context: null,
      },
    ],
    total: 2,
    facets: {
      actions: ["exemption.grant", "duty_config.update"],
      entity_types: ["soldier_exemption", "duty_type"],
      actors: [{ id: "actor-1", full_name: "דני כהן" }],
    },
    ...overrides,
  };
}

function renderContent() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <AuditLogContent />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  mockList.mockReset();
  mockList.mockResolvedValue(makePage());
});

test("renders entries with resolved actor names and system fallback", async () => {
  renderContent();
  await waitFor(() => expect(screen.getByTestId("audit-log-table")).toBeInTheDocument());
  const table = screen.getByTestId("audit-log-table");
  expect(within(table).getAllByText("דני כהן").length).toBeGreaterThan(0);
  expect(screen.getByText("exemption.grant")).toBeInTheDocument();
  expect(screen.getByText("duty_config.update")).toBeInTheDocument();
  expect(within(table).getByText("מערכת")).toBeInTheDocument();
});

test("sends filters to the API and resets pagination", async () => {
  renderContent();
  await waitFor(() => expect(mockList).toHaveBeenCalled());
  // wait for facets to load so the select is populated
  await waitFor(() =>
    expect(screen.getByTestId("audit-log-filter-entity-type")).toBeInTheDocument()
  );

  const actionInput = screen.getByTestId("audit-log-filter-action");
  actionInput.setAttribute("value", "");
  fireEvent.change(screen.getByTestId("audit-log-filter-entity-type"), {
    target: { value: "duty_type" },
  });

  await waitFor(() =>
    expect(mockList).toHaveBeenLastCalledWith(
      expect.objectContaining({ entity_type: "duty_type", offset: 0 })
    )
  );
});

test("shows empty state and pagination info", async () => {
  mockList.mockResolvedValue(makePage({ items: [], total: 0 }));
  renderContent();
  await waitFor(() => expect(screen.getByText("לא נמצאו רשומות")).toBeInTheDocument());
  expect(screen.getByTestId("audit-log-pagination")).toBeInTheDocument();
});


test("clicking an action opens a detail modal with before/after payloads", async () => {
  renderContent();
  const table = await screen.findByTestId("audit-log-table");
  expect(within(table).getByText("exemption.grant")).toBeInTheDocument();

  fireEvent.click(within(table).getByText("exemption.grant"));

  const modal = screen.getByTestId("audit-log-detail-modal");
  console.log("DEBUG selected before:", JSON.stringify(mockList.mock.results));
  expect(modal).toBeInTheDocument();
  expect(screen.getByTestId("audit-log-detail-before")).toHaveTextContent("pending_commander");
  expect(screen.getByTestId("audit-log-detail-after")).toHaveTextContent("approved");
  expect(screen.getByTestId("audit-log-detail-context")).toHaveTextContent("בקשה אושרה");

  // close
  fireEvent.click(screen.getByTestId("audit-log-detail-close"));
  expect(screen.queryByTestId("audit-log-detail-modal")).not.toBeInTheDocument();
});


test("entity id renders as link when it exists and struck-through when deleted", async () => {
  renderContent();
  const table = await screen.findByTestId("audit-log-table");
  const link = within(table).getByTestId("audit-log-entity-link-log-1");
  expect(link).toHaveAttribute("href", "/planning/config");
  const deleted = within(table).getByText(/נמחק/);
  expect(deleted).toBeInTheDocument();
  expect(within(table).getByText(/ent-1/)).toBeInTheDocument();
  expect(within(table).getByText(/ent-2/)).toBeInTheDocument();
});
