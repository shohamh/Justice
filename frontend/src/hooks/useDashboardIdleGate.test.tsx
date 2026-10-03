import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useDashboardIdleGate } from "./useDashboardIdleGate";

function setup(withBlockingQuery = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let finishBlockingQuery!: () => void;
  if (withBlockingQuery) {
    void client.fetchQuery({
      queryKey: ["blocking"],
      queryFn: () => new Promise<string>((resolve) => { finishBlockingQuery = () => resolve("done"); }),
    });
  }
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  const hook = renderHook(({ scope, ready }) => useDashboardIdleGate(ready, scope), {
    wrapper,
    initialProps: { scope: "scope-a", ready: true },
  });
  return { client, finishBlockingQuery, ...hook };
}

afterEach(() => vi.useRealTimers());

describe("useDashboardIdleGate", () => {
  it("waits 400 ms after app-wide queries become idle", async () => {
    vi.useFakeTimers();
    const { finishBlockingQuery, result } = setup(true);
    await act(async () => {
      finishBlockingQuery();
      await vi.advanceTimersByTimeAsync(0);
      await Promise.resolve();
    });
    expect(result.current).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(399); });
    expect(result.current).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(result.current).toBe(true);
  });

  it("restarts the idle window when another shared query begins", async () => {
    vi.useFakeTimers();
    const { client, result } = setup();
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    let finish!: () => void;
    act(() => {
      void client.fetchQuery({
        queryKey: ["interruption"],
        queryFn: () => new Promise<string>((resolve) => { finish = () => resolve("done"); }),
      });
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    expect(result.current).toBe(false);
    await act(async () => { finish(); await vi.advanceTimersByTimeAsync(0); });
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    expect(result.current).toBe(true);
  });

  it("opens after the 1200 ms maximum wait while a query remains in flight", async () => {
    vi.useFakeTimers();
    const { result } = setup(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(1199); });
    expect(result.current).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(result.current).toBe(true);
  });

  it("resets the idle and maximum timers when readiness or authorization scope changes", async () => {
    vi.useFakeTimers();
    const { result, rerender } = setup();
    await act(async () => { await vi.advanceTimersByTimeAsync(399); });
    rerender({ scope: "scope-b", ready: true });
    expect(result.current).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(399); });
    expect(result.current).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(result.current).toBe(true);

    rerender({ scope: "scope-b", ready: false });
    expect(result.current).toBe(false);
    rerender({ scope: "scope-b", ready: true });
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    expect(result.current).toBe(true);
  });
});
