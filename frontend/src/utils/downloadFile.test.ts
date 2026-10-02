import { afterEach, describe, expect, it, vi } from "vitest";
import { createTemporaryBlobUrl, sanitizeFilename } from "./downloadFile";

describe("sanitizeFilename", () => {
  it("removes path traversal and unsafe filename characters", () => {
    expect(sanitizeFilename("../../report:<bad>|?.png")).toBe("report__bad___.png");
    expect(sanitizeFilename("..\\report?.xlsx")).toBe("report_.xlsx");
  });

  it("uses a safe fallback and protects Windows device names", () => {
    expect(sanitizeFilename("../")).toBe("download");
    expect(sanitizeFilename("CON.txt")).toBe("_CON.txt");
  });
});

describe("temporary Blob URLs", () => {
  afterEach(() => vi.restoreAllMocks());

  it("revokes its URL once when disposed", () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const temporary = createTemporaryBlobUrl(new Blob(["image"]));

    expect(temporary.url).toBe("blob:preview");
    temporary.dispose();
    temporary.dispose();
    expect(revoke).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:preview");
  });
});
