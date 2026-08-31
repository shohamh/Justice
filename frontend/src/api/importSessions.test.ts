import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listSessions } from "./importSessions";

vi.mock("./client");

describe("listSessions", () => {
  it("rejects a malformed response", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(listSessions()).rejects.toThrow("Invalid import sessions response");
  });

  it("passes through a well-formed list", async () => {
    const sessions = [
      {
        id: "session-1",
        status: "draft" as const,
        filename: "import.xlsx",
        created_at: "2026-08-30T00:00:00Z",
        row_summary: {
          soldiers: 0,
          duty_shifts: 0,
          assignments: 0,
          duty_locations: 0,
          hierarchy: 0,
          duty_types: 0,
          exemption_types: 0,
          personal_constraints: 0,
          soldier_field_updates: 0,
          soldier_enrollment_requests: 0,
          soldier_exemptions: 0,
          exemption_requests: 0,
          swap_requests: 0,
          range_locations: 0,
          range_events: 0,
          range_assignments: 0,
          soldier_range_qualifications: 0,
          range_excusal_requests: 0,
        },
      },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: sessions });

    await expect(listSessions()).resolves.toEqual(sessions);
  });
});
