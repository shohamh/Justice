import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getAnnounceScope, getAnnouncementRecipients, listAnnouncements } from "./announcements";

vi.mock("./client");

describe("announcement APIs", () => {
  it("returns an empty list when announce scope is not an array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(getAnnounceScope()).resolves.toEqual([]);
  });

  it("rejects a malformed announcements page payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: { detail: "unexpected response" }, total: 1 } });

    await expect(listAnnouncements()).rejects.toThrow("Invalid announcements response");
  });

  it("rejects a malformed announcement recipients payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: { detail: "unexpected response" }, total: 1 } });

    await expect(getAnnouncementRecipients("announcement-1")).rejects.toThrow("Invalid announcement recipients response");
  });
});
