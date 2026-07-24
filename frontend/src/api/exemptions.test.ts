import { describe, it, expect } from "vitest";
import { exemptionFileDownloadUrl } from "./exemptions";

describe("exemptionFileDownloadUrl", () => {
  it("returns a path relative to the api client's baseURL, without a duplicate /api prefix", () => {
    expect(exemptionFileDownloadUrl("req-1", "file-1")).toBe("/exemption-requests/req-1/files/file-1");
  });
});
