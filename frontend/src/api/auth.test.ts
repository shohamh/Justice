import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { fetchMe } from "./auth";

vi.mock("./client");

const baseMe = {
  id: "s-1",
  personal_number: "123",
  full_name: "Yossi",
  role: "soldier" as const,
  is_commander: false,
  is_duty_manager: false,
  must_change_password: false,
  hierarchy_node_id: null,
  telegram_linked: false,
  telegram_required: false,
  enrollment_pending: false,
  theme_preference: "system" as const,
};

describe("fetchMe", () => {
  it("normalizes a malformed active_deputy_grants field to an empty array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { ...baseMe, active_deputy_grants: { not: "an array" } } });

    const me = await fetchMe();

    expect(me.active_deputy_grants).toEqual([]);
  });

  it("passes through a well-formed active_deputy_grants field", async () => {
    const grants = [{ principal_id: "p-1", principal_name: "Cmdr", role: "commander" as const, end_date: "2026-01-01" }];
    vi.mocked(api.get).mockResolvedValue({ data: { ...baseMe, active_deputy_grants: grants } });

    const me = await fetchMe();

    expect(me.active_deputy_grants).toEqual(grants);
  });
});
