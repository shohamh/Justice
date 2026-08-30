import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listPendingEnrollments } from "./enrollment";

vi.mock("./client");

describe("enrollment APIs", () => {
  it("rejects a malformed pending enrollments payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listPendingEnrollments()).rejects.toThrow("Invalid pending enrollments response");
  });
});
