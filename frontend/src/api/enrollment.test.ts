import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listPendingEnrollments } from "./enrollment";

vi.mock("./client");

describe("enrollment APIs", () => {
  it("rejects a malformed pending enrollments payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listPendingEnrollments()).rejects.toThrow("Invalid pending enrollments response");
  });

  it("drops a non-object row and normalizes a row's malformed exemption_requests field to []", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [
        "not-a-request-object",
        {
          id: "req-1",
          soldier_id: "soldier-1",
          soldier_name: "Soldier One",
          soldier_personal_number: "1234567",
          requested_node_id: "node-1",
          requested_node_name: "Unit A",
          status: "pending",
          decided_by: null,
          decision_note: null,
          phone: null,
          email: null,
          rank: null,
          rank_track: null,
          is_officer: null,
          is_career: false,
          can_edit_rank_advancement: false,
          gender: null,
          enlistment_date: null,
          mandatory_end_date: null,
          discharge_date: null,
          last_mitvahim_date: null,
          last_alal_date: null,
          exemption_requests: "not-an-array",
          nearest_commander: null,
          nearest_duty_manager: null,
        },
      ],
    });

    const result = await listPendingEnrollments();

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ id: "req-1", exemption_requests: [] });
  });
});
