import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAdminIneligibleSoldierCount } from "./useAdminIneligibleSoldierCount";

const mockGetIneligibleSoldierCount = vi.hoisted(() => vi.fn());

vi.mock("../api/ineligibleSoldiers", () => ({
  getIneligibleSoldierCount: (...args: unknown[]) => mockGetIneligibleSoldierCount(...args),
}));

function Count({ id, actorId, scope }: { id: string; actorId: string; scope: string }) {
  const query = useAdminIneligibleSoldierCount({ actorId, authorizationScope: scope, enabled: true });
  return <span data-testid={id}>{query.data?.count ?? "pending"}</span>;
}

function renderCounts(scopes: Array<{ id: string; actorId: string; scope: string }>, queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const result = render(
    <QueryClientProvider client={queryClient}>
      {scopes.map(scope => <Count key={scope.id} {...scope} />)}
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

describe("useAdminIneligibleSoldierCount", () => {
  beforeEach(() => {
    mockGetIneligibleSoldierCount.mockReset();
    mockGetIneligibleSoldierCount.mockResolvedValue({ count: 7 });
  });

  it("shares one fresh count between consumers with the same admin and authorization scope", async () => {
    const { queryClient, rerender } = renderCounts([
      { id: "home", actorId: "admin-1", scope: "scope-a" },
    ]);

    await waitFor(() => expect(screen.getByTestId("home")).toHaveTextContent("7"));
    rerender(
      <QueryClientProvider client={queryClient}>
        <Count id="home" actorId="admin-1" scope="scope-a" />
        <Count id="nav" actorId="admin-1" scope="scope-a" />
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("nav")).toHaveTextContent("7");
    expect(mockGetIneligibleSoldierCount).toHaveBeenCalledTimes(1);
    expect(mockGetIneligibleSoldierCount).toHaveBeenCalledWith("commander");
  });

  it("keeps counts isolated across actors and authorization scopes", async () => {
    renderCounts([
      { id: "home", actorId: "admin-1", scope: "scope-a" },
      { id: "other-actor", actorId: "admin-2", scope: "scope-a" },
      { id: "other-scope", actorId: "admin-1", scope: "scope-b" },
    ]);

    await waitFor(() => expect(screen.getByTestId("home")).toHaveTextContent("7"));
    await waitFor(() => expect(screen.getByTestId("other-actor")).toHaveTextContent("7"));
    await waitFor(() => expect(screen.getByTestId("other-scope")).toHaveTextContent("7"));
    expect(mockGetIneligibleSoldierCount).toHaveBeenCalledTimes(3);
  });
});
