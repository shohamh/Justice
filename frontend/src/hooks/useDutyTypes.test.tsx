import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDutyTypes } from "./useDutyTypes";

const mockListDutyTypes = vi.hoisted(() => vi.fn());

vi.mock("../api/dutyConfig", () => ({
  listDutyTypes: (...args: unknown[]) => mockListDutyTypes(...args),
}));

function Consumer({ id }: { id: string }) {
  const { data } = useDutyTypes();
  return <span data-testid={id}>{data ? data.map((t: { name: string }) => t.name).join(",") : "loading"}</span>;
}

describe("useDutyTypes", () => {
  beforeEach(() => {
    mockListDutyTypes.mockReset();
    mockListDutyTypes.mockResolvedValue([{ id: "d1", name: "Guard", active: true }]);
  });

  it("makes one request for two simultaneous consumers", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <Consumer id="home" />
        <Consumer id="calendar" />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("home")).toHaveTextContent("Guard"));
    expect(screen.getByTestId("calendar")).toHaveTextContent("Guard");
    expect(mockListDutyTypes).toHaveBeenCalledTimes(1);
  });
});
