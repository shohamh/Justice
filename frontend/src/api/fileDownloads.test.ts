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

describe("protected file downloads", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ data: new Blob(["file"]) });
  });

  it("downloads exemption request files through the authenticated gateway", async () => {
    const { downloadExemptionRequestFile } = await import("./exemptions");
    const blob = await downloadExemptionRequestFile("request-1", "file-2");
    expect(blob).toBeInstanceOf(Blob);
    expect(mockGet).toHaveBeenCalledWith(
      "/file-download/exemption-requests/request-1/files/file-2",
      { responseType: "blob" },
    );
  });

  it("downloads soldier exemption files through the authenticated gateway", async () => {
    const { downloadSoldierExemptionFile } = await import("./exemptions");
    const blob = await downloadSoldierExemptionFile("exemption-1", "file-2");
    expect(blob).toBeInstanceOf(Blob);
    expect(mockGet).toHaveBeenCalledWith(
      "/file-download/exemptions/exemption-1/files/file-2",
      { responseType: "blob" },
    );
  });

  it("downloads Gimelim attachments through the authenticated gateway", async () => {
    const { downloadGimelimAttachment } = await import("./gimelim");
    const blob = await downloadGimelimAttachment("dismissal-1", "attachment-2");
    expect(blob).toBeInstanceOf(Blob);
    expect(mockGet).toHaveBeenCalledWith(
      "/file-download/gimelim/dismissal-1/attachments/attachment-2",
      { responseType: "blob" },
    );
  });

  it("downloads bug report screenshots through the authenticated gateway", async () => {
    const { fetchBugReportScreenshot } = await import("./bugReports");
    const blob = await fetchBugReportScreenshot("report-1");
    expect(blob).toBeInstanceOf(Blob);
    expect(mockGet).toHaveBeenCalledWith(
      "/file-download/bug-reports/report-1/screenshot",
      { responseType: "blob" },
    );
  });

  it("downloads comment attachments through the authenticated gateway", async () => {
    const { downloadBugReportCommentAttachment } = await import("./bugReports");
    const blob = await downloadBugReportCommentAttachment("report-1", "comment-2", "attachment-3");
    expect(blob).toBeInstanceOf(Blob);
    expect(mockGet).toHaveBeenCalledWith(
      "/file-download/bug-reports/report-1/comments/comment-2/attachments/attachment-3",
      { responseType: "blob" },
    );
  });

  it("downloads original import workbooks through the authenticated gateway", async () => {
    const { downloadImportWorkbook } = await import("./importSessions");
    const blob = await downloadImportWorkbook("session-1");
    expect(blob).toBeInstanceOf(Blob);
    expect(mockGet).toHaveBeenCalledWith(
      "/file-download/import-sessions/session-1/workbook",
      { responseType: "blob" },
    );
  });
});
