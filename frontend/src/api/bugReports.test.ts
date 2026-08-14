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
