import { describe, expect, it, vi } from "vitest";
import { installChunkLoadRecovery } from "./chunkLoadRecovery";

function fakeWindow(storage: Storage | "throws") {
  const listeners: Record<string, ((e: Event) => void)[]> = {};
  const reload = vi.fn();
  const win = {
    addEventListener: (type: string, fn: (e: Event) => void) => {
      (listeners[type] ??= []).push(fn);
    },
    location: { reload },
    get sessionStorage(): Storage {
      if (storage === "throws") throw new Error("denied");
      return storage;
    },
  } as unknown as Window;
  const fire = () => {
    const event = { preventDefault: vi.fn() } as unknown as Event;
    (listeners["vite:preloadError"] ?? []).forEach((fn) => fn(event));
    return event;
  };
  return { win, reload, fire };
}

function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
  } as unknown as Storage;
}

describe("installChunkLoadRecovery", () => {
  it("prevents the error and reloads once on vite:preloadError", () => {
    const { win, reload, fire } = fakeWindow(memoryStorage());
    installChunkLoadRecovery(win);
    const event = fire();
    expect(event.preventDefault).toHaveBeenCalled();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("does not reload again within 60 seconds", () => {
    const { win, reload, fire } = fakeWindow(memoryStorage());
    installChunkLoadRecovery(win);
    fire();
    fire();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("reloads again after the guard window has passed", () => {
    vi.useFakeTimers();
    try {
      const { win, reload, fire } = fakeWindow(memoryStorage());
      installChunkLoadRecovery(win);
      fire();
      vi.advanceTimersByTime(61_000);
      fire();
      expect(reload).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("still reloads once without crashing when storage throws", () => {
    const { win, reload, fire } = fakeWindow("throws");
    installChunkLoadRecovery(win);
    expect(() => fire()).not.toThrow();
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
