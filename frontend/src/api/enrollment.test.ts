import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listPendingEnrollments } from "./enrollment";

vi.mock("./client");

describe("enrollment APIs", () => {
  it("returns an empty list when pending enrollments are not an array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listPendingEnrollments()).resolves.toEqual([]);
  });
});
