import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  downloadBlob: vi.fn(),
}));

vi.mock("./client", () => ({
  api: {
    post: mocks.post,
  },
}));

vi.mock("../utils/downloadFile", () => ({
  downloadBlob: mocks.downloadBlob,
}));

describe("XLSX export API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts a table matrix as a blob and downloads it with the requested filename", async () => {
    const blob = new Blob(["table workbook"]);
    const request = {
      filename: "soldiers.xlsx",
      matrix: {
        sheet_name: "חיילים",
        headers: ["שם", "פעיל"],
        rows: [["דני", true]],
      },
    };
    mocks.post.mockResolvedValue({ data: blob });

    const { exportTable } = await import("./exports");
    await exportTable(request);

    expect(mocks.post).toHaveBeenCalledWith("/exports/xlsx", request, {
      responseType: "blob",
    });
    expect(mocks.downloadBlob).toHaveBeenCalledWith(blob, request.filename);
  });

  it("posts planning matrices and sheet selections as a blob and downloads the requested filename", async () => {
    const blob = new Blob(["planning workbook"]);
    const request = {
      filename: "export.xlsx",
      tables: [
        {
          sheet_name: "transparency",
          headers: ["שם"],
          rows: [["דני"]],
        },
      ],
      config_sheets: ["duty_types"],
      data_sheets: ["soldiers"],
    };
    mocks.post.mockResolvedValue({ data: blob });

    const { exportPlanning } = await import("./exports");
    await exportPlanning(request);

    expect(mocks.post).toHaveBeenCalledWith("/exports/planning-xlsx", request, {
      responseType: "blob",
    });
    expect(mocks.downloadBlob).toHaveBeenCalledWith(blob, request.filename);
  });
});
