import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { queryKeys } from "./queryKeys";

describe("queryKeys.navCountsAll", () => {
  it("is a prefix of every scoped navCounts key", async () => {
    const client = new QueryClient();
    client.setQueryData(queryKeys.navCounts("scope-a", true), { approvals: 1 });
    client.setQueryData(queryKeys.navCounts("scope-b", false), { approvals: 2 });
    client.setQueryData(queryKeys.mySwaps(), []);

    await client.invalidateQueries({ queryKey: queryKeys.navCountsAll(), refetchType: "none" });

    expect(client.getQueryState(queryKeys.navCounts("scope-a", true))?.isInvalidated).toBe(true);
    expect(client.getQueryState(queryKeys.navCounts("scope-b", false))?.isInvalidated).toBe(true);
    expect(client.getQueryState(queryKeys.mySwaps())?.isInvalidated).toBe(false);
  });
});
