import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { useInvalidateNavCounts } from "./useInvalidateNavCounts";
import { queryKeys } from "../queryKeys";

describe("useInvalidateNavCounts", () => {
  it("invalidates the nav counts prefix", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useInvalidateNavCounts(), { wrapper });
    result.current();
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.navCountsAll() });
  });
});
