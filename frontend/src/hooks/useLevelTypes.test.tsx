import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLevelTypes } from "./useLevelTypes";

const mockListLevelTypes = vi.hoisted(() => vi.fn());

vi.mock("../api/levelTypes", () => ({
  listLevelTypes: (...args: unknown[]) => mockListLevelTypes(...args),
}));

let refreshFromConsumer: (() => Promise<void>) | null = null;

function Consumer({ id }: { id: string }) {
  const { levelTypes, loading, refresh } = useLevelTypes();
  refreshFromConsumer = refresh;
  return <span data-testid={id}>{loading ? "loading" : levelTypes.map((t) => t.label).join(",")}</span>;
}

function renderConsumers(ids: string[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      {ids.map((id) => <Consumer key={id} id={id} />)}
    </QueryClientProvider>,
  );
}

describe("useLevelTypes", () => {
  beforeEach(() => {
    mockListLevelTypes.mockReset();
    mockListLevelTypes.mockResolvedValue([{ id: "1", key: "team", label: "Team", rank: 1 }]);
  });

  it("makes one request for two simultaneous consumers", async () => {
    renderConsumers(["home", "panel"]);

    await waitFor(() => expect(screen.getByTestId("home")).toHaveTextContent("Team"));
    expect(screen.getByTestId("panel")).toHaveTextContent("Team");
    expect(mockListLevelTypes).toHaveBeenCalledTimes(1);
  });

  it("refresh refetches and updates every consumer", async () => {
    renderConsumers(["tree", "dialog"]);
    await waitFor(() => expect(screen.getByTestId("tree")).toHaveTextContent("Team"));

    mockListLevelTypes.mockResolvedValue([{ id: "1", key: "team", label: "Squad", rank: 1 }]);
    await act(async () => {
      await refreshFromConsumer?.();
    });

    await waitFor(() => expect(screen.getByTestId("tree")).toHaveTextContent("Squad"));
    expect(screen.getByTestId("dialog")).toHaveTextContent("Squad");
    expect(mockListLevelTypes).toHaveBeenCalledTimes(2);
  });

  it("refresh rejects when the refetch fails", async () => {
    renderConsumers(["dialog"]);
    await waitFor(() => expect(screen.getByTestId("dialog")).toHaveTextContent("Team"));

    mockListLevelTypes.mockRejectedValue(new Error("down"));
    await expect(refreshFromConsumer?.()).rejects.toThrow("down");
  });
});
