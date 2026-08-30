import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listTemplates, previewGeneration } from "./shiftTemplates";

vi.mock("./client");

describe("listTemplates", () => {
  it("normalizes a malformed response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(listTemplates()).resolves.toEqual([]);
  });
});

describe("previewGeneration", () => {
  it("rejects a malformed response", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(previewGeneration("template-1", "2026-09-01", "2026-09-08")).rejects.toThrow(
      "Invalid shift template preview response",
    );
  });

  it("passes through a well-formed preview list", async () => {
    const rows = [{ date: "2026-09-01", exists: false }];
    vi.mocked(api.post).mockResolvedValue({ data: rows });

    await expect(previewGeneration("template-1", "2026-09-01", "2026-09-08")).resolves.toEqual(rows);
  });
});
