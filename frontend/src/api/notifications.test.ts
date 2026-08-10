import { describe, it, expect } from "vitest";
import { getNotificationLink } from "./notifications";

describe("getNotificationLink", () => {
  it("routes swap_offer_incoming to the incoming tab", () => {
    const link = getNotificationLink({ type: "swap_offer_incoming", reference_type: "swap_request", reference_id: "r1" });
    expect(link).toBe("/swaps?tab=incoming");
  });
});