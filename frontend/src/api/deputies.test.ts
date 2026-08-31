import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listDeputies } from "./deputies";

vi.mock("./client");

describe("listDeputies", () => {
  it("normalizes a malformed response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(listDeputies("principal-1")).resolves.toEqual([]);
  });

  it("passes through a well-formed list", async () => {
    const grants = [
      {
        id: "deputy-1",
        principal_id: "principal-1",
        principal_name: "Commander One",
        deputy_id: "soldier-1",
        deputy_name: "Soldier One",
        role: "commander" as const,
        start_date: "2026-08-01",
        end_date: "2026-09-01",
      },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: grants });

    await expect(listDeputies("principal-1")).resolves.toEqual(grants);
  });
});
