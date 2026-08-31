import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { previewGimelim } from "./gimelim";

vi.mock("./client");

describe("previewGimelim", () => {
  it("rejects a non-object response", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: "unexpected" });

    await expect(
      previewGimelim("shift-1", { primary_assignment_id: "a-1", rest_days: 1, from_date: "2026-01-01" })
    ).rejects.toThrow("Invalid gimelim preview response");
  });

  it("rejects a response missing preview_token", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { warnings: [] } });

    await expect(
      previewGimelim("shift-1", { primary_assignment_id: "a-1", rest_days: 1, from_date: "2026-01-01" })
    ).rejects.toThrow("Invalid gimelim preview response");
  });

  it("normalizes a malformed warnings field to an empty array", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        preview_token: "tok-1",
        preview_token_expires_at: "2026-01-01T00:00:00Z",
        current_shift: { shift_id: "s-1", duty_type_name: "Guard", duty_location_name: "Gate", start_date: "", end_date: "" },
        soldier_a: { id: "sol-1", name: "Yossi", rank: null },
        primary_assignment_id: "a-1",
        reserve_assignment_id: "a-2",
        reserve_soldier: { id: "sol-2", name: "Moshe", rank: null },
        future_assignment: null,
        warnings: "not-an-array",
      },
    });

    const result = await previewGimelim("shift-1", { primary_assignment_id: "a-1", rest_days: 1, from_date: "2026-01-01" });

    expect(result.warnings).toEqual([]);
  });

  it("passes through a well-formed response", async () => {
    const payload = {
      preview_token: "tok-1",
      preview_token_expires_at: "2026-01-01T00:00:00Z",
      current_shift: { shift_id: "s-1", duty_type_name: "Guard", duty_location_name: "Gate", start_date: "", end_date: "" },
      soldier_a: { id: "sol-1", name: "Yossi", rank: null },
      primary_assignment_id: "a-1",
      reserve_assignment_id: "a-2",
      reserve_soldier: { id: "sol-2", name: "Moshe", rank: null },
      future_assignment: null,
      warnings: ["no_future_slot_found"],
    };
    vi.mocked(api.post).mockResolvedValue({ data: payload });

    await expect(
      previewGimelim("shift-1", { primary_assignment_id: "a-1", rest_days: 1, from_date: "2026-01-01" })
    ).resolves.toEqual(payload);
  });
});
