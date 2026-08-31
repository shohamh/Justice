import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGet = vi.fn();

vi.mock("./client", () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("bugReports api", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("requests the all-active export by default", async () => {
    mockGet.mockResolvedValue({
      data: new Blob(["zip"]),
      headers: {},
    });

    const { downloadBugReportExport } = await import("./bugReports");
    const result = await downloadBugReportExport();

    expect(mockGet).toHaveBeenCalledWith("/admin/bug-reports/export", {
      params: { scope: "all_active" },
      responseType: "blob",
    });
    expect(result.filename).toBeNull();
  });

  it("requests the filtered export with only active status filters and preserves the server filename", async () => {
    const blob = new Blob(["zip"]);
    mockGet.mockResolvedValue({
      data: blob,
      headers: {
        "content-disposition": 'attachment; filename="bug-reports-2026-08-14-1015.zip"',
      },
    });

    const { downloadBugReportExport } = await import("./bugReports");
    const result = await downloadBugReportExport({
      scope: "filtered",
      severity: "high",
      status: "resolved",
    });

    expect(mockGet).toHaveBeenCalledWith("/admin/bug-reports/export", {
      params: {
        scope: "filtered",
        severity: "high",
      },
      responseType: "blob",
    });
    expect(result).toEqual({
      blob,
      filename: "bug-reports-2026-08-14-1015.zip",
    });
  });
});

describe("listBugReports", () => {
  it("rejects a malformed page response", async () => {
    mockGet.mockResolvedValue({ data: "not-an-object" });

    const { listBugReports } = await import("./bugReports");

    await expect(listBugReports({ limit: 50, offset: 0 })).rejects.toThrow(
      "Invalid bug reports response",
    );
  });

  it("drops a non-object row and normalizes malformed nav_history/audit_snapshot fields to []", async () => {
    mockGet.mockResolvedValue({
      data: {
        items: [
          42,
          {
            id: "report-1",
            reporter_id: null,
            description: "desc",
            severity: "low",
            status: "open",
            route: "/",
            nav_history: "not-an-array",
            audit_snapshot: "not-an-array",
            user_snapshot: null,
            has_screenshot: false,
            created_at: "2026-08-30T00:00:00Z",
            updated_at: "2026-08-30T00:00:00Z",
            comment_count: 0,
            last_comment_at: null,
            has_unseen_activity: false,
            unread: false,
          },
        ],
        total: 1,
      },
    });

    const { listBugReports } = await import("./bugReports");
    const result = await listBugReports({ limit: 50, offset: 0 });

    expect(result.items).toHaveLength(1);
    expect(result.items[0].nav_history).toEqual([]);
    expect(result.items[0].audit_snapshot).toEqual([]);
  });

  it("preserves a null nav_history/audit_snapshot field", async () => {
    mockGet.mockResolvedValue({
      data: {
        items: [
          {
            id: "report-1",
            reporter_id: null,
            description: "desc",
            severity: "low",
            status: "open",
            route: "/",
            nav_history: null,
            audit_snapshot: null,
            user_snapshot: null,
            has_screenshot: false,
            created_at: "2026-08-30T00:00:00Z",
            updated_at: "2026-08-30T00:00:00Z",
            comment_count: 0,
            last_comment_at: null,
            has_unseen_activity: false,
            unread: false,
          },
        ],
        total: 1,
      },
    });

    const { listBugReports } = await import("./bugReports");
    const result = await listBugReports({ limit: 50, offset: 0 });

    expect(result.items[0].nav_history).toBeNull();
    expect(result.items[0].audit_snapshot).toBeNull();
  });
});

describe("listAdminErrors", () => {
  it("rejects a malformed page response", async () => {
    mockGet.mockResolvedValue({ data: "not-an-object" });

    const { listAdminErrors } = await import("./bugReports");

    await expect(listAdminErrors()).rejects.toThrow("Invalid admin errors response");
  });

  it("normalizes a malformed items field to []", async () => {
    mockGet.mockResolvedValue({ data: { items: "not-an-array", total: 0 } });

    const { listAdminErrors } = await import("./bugReports");

    await expect(listAdminErrors()).resolves.toEqual({ items: [], total: 0 });
  });
});

describe("listComments", () => {
  it("rejects a malformed comments response", async () => {
    mockGet.mockResolvedValue({ data: "not-an-object" });

    const { listComments } = await import("./bugReports");

    await expect(listComments("report-1")).rejects.toThrow(
      "Invalid bug report comments response",
    );
  });

  it("drops a non-object row and normalizes a row's malformed attachments field to []", async () => {
    mockGet.mockResolvedValue({
      data: [
        42,
        {
          id: "comment-1",
          bug_report_id: "report-1",
          author_id: "soldier-1",
          author_name: "Soldier One",
          body: "hi",
          created_at: "2026-08-30T00:00:00Z",
          attachments: "not-an-array",
        },
      ],
    });

    const { listComments } = await import("./bugReports");
    const result = await listComments("report-1");

    expect(result).toHaveLength(1);
    expect(result[0].attachments).toEqual([]);
  });
});
