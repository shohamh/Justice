import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { search } from "./search";

vi.mock("./client");

describe("search", () => {
  it("normalizes a wholly malformed response to empty arrays", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: "unexpected" });

    await expect(search("abc")).resolves.toEqual({ soldiers: [], duties: [], units: [] });
  });

  it("normalizes a malformed individual field while keeping valid ones", async () => {
    const duties = [{ id: "d-1", duty_type_name: "Guard", start_date: "", end_date: "", location_name: null }];
    vi.mocked(api.get).mockResolvedValue({ data: { soldiers: { not: "an array" }, duties, units: null } });

    await expect(search("abc")).resolves.toEqual({ soldiers: [], duties, units: [] });
  });

  it("passes through a well-formed response", async () => {
    const payload = {
      soldiers: [{ id: "s-1", full_name: "Yossi", personal_number: "123", subtitle: null }],
      duties: [],
      units: [{ id: "u-1", name: "Alpha", level: "team" }],
    };
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    await expect(search("abc")).resolves.toEqual(payload);
  });
});
