import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as hierarchyApi from "../api/hierarchy";
import type { Me } from "../api/auth";
import HierarchyNodePickerModal from "./HierarchyNodePickerModal";

const mockUseAuth = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../auth/AuthContext", () => ({ useAuth: mockUseAuth }));
vi.mock("../api/hierarchy");

const observers: MockIntersectionObserver[] = [];

class MockIntersectionObserver {
  readonly targets = new Set<Element>();

  constructor(private readonly callback: IntersectionObserverCallback) {
    observers.push(this);
  }

  observe = (target: Element) => { this.targets.add(target); };
  unobserve = (target: Element) => { this.targets.delete(target); };
  disconnect = () => { this.targets.clear(); };
  takeRecords = () => [];

  notify(target: Element, isIntersecting: boolean) {
    this.callback(
      [{ target, isIntersecting, intersectionRatio: isIntersecting ? 1 : 0 } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }
}

function notifyIntersection(target: Element, isIntersecting: boolean) {
  const observer = [...observers].reverse().find((candidate) => candidate.targets.has(target));
  if (!observer) throw new Error("No observer is watching the near-end sentinel");
  act(() => observer.notify(target, isIntersecting));
}

const user = {
  id: "viewer-1",
  role: "commander",
  hierarchy_node_id: "root-1",
  scope_root_ids: ["root-1"],
  is_commander: true,
  is_duty_manager: false,
  active_deputy_grants: [],
} as unknown as Me;

function makeNode(id: string, name: string, parentId: string | null, hasChildren = false): hierarchyApi.NodeDTO {
  return {
    id,
    name,
    level: "unit",
    parent_id: parentId,
    commander_id: null,
    commander_name: null,
    path_ids: parentId ? [parentId, id] : [id],
    duty_managers: [],
    dm_manageable: false,
    can_edit: false,
    has_children: hasChildren,
    has_soldiers: false,
  };
}

function renderPicker(onPicked = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <HierarchyNodePickerModal onClose={vi.fn()} onPicked={onPicked} />
    </QueryClientProvider>,
  );
  return { ...result, onPicked };
}

beforeEach(() => {
  vi.resetAllMocks();
  observers.length = 0;
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
  mockUseAuth.mockReturnValue({ user });
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HierarchyNodePickerModal", () => {
  it("loads only the first root page and leaves children unopened", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage).mockResolvedValue({
      items: [makeNode("root-1", "Root", null, true)],
      next_cursor: null,
      has_more: false,
    });

    renderPicker();

    expect(await screen.findByText("Root")).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(1);
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledWith(
      expect.objectContaining({ parentId: null }),
    );
    expect(hierarchyApi.fetchFullTree).not.toHaveBeenCalled();
    expect(screen.queryByTestId("picker-tree-toggle-root-1")).toHaveAttribute("aria-expanded", "false");
  });

  it("loads children only when expanded and lets the user select a child", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage).mockImplementation(async ({ parentId }) => ({
      items: parentId === null
        ? [makeNode("root-1", "Root", null, true)]
        : [makeNode("unit-1", "Unit Alpha", "root-1")],
      next_cursor: null,
      has_more: false,
    }));
    const { onPicked } = renderPicker();

    await screen.findByText("Root");
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("picker-tree-toggle-root-1"));

    expect(await screen.findByText("Unit Alpha")).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenLastCalledWith(
      expect.objectContaining({ parentId: "root-1" }),
    );
    fireEvent.click(screen.getByTestId("picker-select-node-unit-1"));
    expect(onPicked).toHaveBeenCalledWith("unit-1", "Unit Alpha", ["Root", "Unit Alpha"]);
  });

  it("continues a branch page with an accessible load-more control", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage).mockImplementation(async ({ parentId, cursor }) => {
      if (parentId === null) {
        return { items: [makeNode("root-1", "Root", null, true)], next_cursor: null, has_more: false };
      }
      if (!cursor) {
        return { items: [makeNode("unit-1", "Unit Alpha", "root-1")], next_cursor: "child-cursor", has_more: true };
      }
      return { items: [makeNode("unit-2", "Unit Beta", "root-1")], next_cursor: null, has_more: false };
    });
    renderPicker();

    await screen.findByText("Root");
    fireEvent.click(screen.getByTestId("picker-tree-toggle-root-1"));
    await screen.findByText("Unit Alpha");
    const loadMore = await screen.findByRole("button", { name: "team.hierarchy_load_more" });
    expect(loadMore).toBeEnabled();

    fireEvent.click(loadMore);

    expect(await screen.findByText("Unit Beta")).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenLastCalledWith(
      expect.objectContaining({ parentId: "root-1", cursor: "child-cursor" }),
    );
  });

  it("prefetches one root page near the end, then waits for the sentinel to leave before prefetching again", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage).mockImplementation(async ({ cursor }) => {
      if (cursor === "root-2") {
        return { items: [makeNode("root-3", "Root Three", null)], next_cursor: null, has_more: false };
      }
      if (cursor === "root-1") {
        return { items: [makeNode("root-2", "Root Two", null)], next_cursor: "root-2", has_more: true };
      }
      return { items: [makeNode("root-1", "Root One", null)], next_cursor: "root-1", has_more: true };
    });
    renderPicker();

    await screen.findByText("Root One");
    const sentinel = screen.getByTestId("picker-root-prefetch-sentinel");
    await waitFor(() => expect([...observers].some((observer) => observer.targets.has(sentinel))).toBe(true));
    notifyIntersection(sentinel, true);

    expect(await screen.findByText("Root Two")).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(2);
    notifyIntersection(sentinel, true);
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(2);

    notifyIntersection(sentinel, false);
    notifyIntersection(sentinel, true);
    expect(await screen.findByText("Root Three")).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(3);
  });

  it("prefetches an expanded child branch near its end while keeping manual paging available", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage).mockImplementation(async ({ parentId, cursor }) => {
      if (parentId === null) {
        return { items: [makeNode("root-1", "Root", null, true)], next_cursor: null, has_more: false };
      }
      if (cursor === "child-1") {
        return { items: [makeNode("unit-2", "Unit Beta", "root-1")], next_cursor: null, has_more: false };
      }
      return { items: [makeNode("unit-1", "Unit Alpha", "root-1")], next_cursor: "child-1", has_more: true };
    });
    renderPicker();

    await screen.findByText("Root");
    fireEvent.click(screen.getByTestId("picker-tree-toggle-root-1"));
    await screen.findByText("Unit Alpha");
    const sentinel = screen.getByTestId("picker-branch-prefetch-sentinel-root-1");
    await waitFor(() => expect([...observers].some((observer) => observer.targets.has(sentinel))).toBe(true));
    expect(screen.getByRole("button", { name: "team.hierarchy_load_more" })).toBeEnabled();

    notifyIntersection(sentinel, true);

    expect(await screen.findByText("Unit Beta")).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenLastCalledWith(
      expect.objectContaining({ parentId: "root-1", cursor: "child-1" }),
    );
  });

  it("does not automatically retry a failed page and leaves retry to the user", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage)
      .mockResolvedValueOnce({
        items: [makeNode("root-1", "Root One", null)],
        next_cursor: "root-1",
        has_more: true,
      })
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({
        items: [makeNode("root-2", "Root Two", null)],
        next_cursor: null,
        has_more: false,
      });
    renderPicker();

    await screen.findByText("Root One");
    const sentinel = screen.getByTestId("picker-root-prefetch-sentinel");
    await waitFor(() => expect([...observers].some((observer) => observer.targets.has(sentinel))).toBe(true));
    const observer = [...observers].reverse().find((candidate) => candidate.targets.has(sentinel))!;
    notifyIntersection(sentinel, true);
    const retry = await screen.findByRole("button", { name: "team.hierarchy_retry" });

    act(() => observer.notify(sentinel, true));
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(2);
    fireEvent.click(retry);

    expect(await screen.findByText("Root Two")).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(3);
  });

  it("offers retry after a child branch request fails", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage)
      .mockResolvedValueOnce({
        items: [makeNode("root-1", "Root", null, true)],
        next_cursor: null,
        has_more: false,
      })
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({
        items: [makeNode("unit-1", "Unit Alpha", "root-1")],
        next_cursor: null,
        has_more: false,
      });
    renderPicker();

    await screen.findByText("Root");
    fireEvent.click(screen.getByTestId("picker-tree-toggle-root-1"));
    const retry = await screen.findByRole("button", { name: "team.hierarchy_retry" });
    fireEvent.click(retry);

    expect(await screen.findByText("Unit Alpha")).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(3);
  });

  it("uses server search and shows each result's ancestor path and capped-results hint", async () => {
    const division = makeNode("division-1", "Division", null);
    const match = makeNode("unit-1", "Echo", "division-1");
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage).mockResolvedValue({
      items: [makeNode("root-1", "Root", null, true)],
      next_cursor: null,
      has_more: false,
    });
    vi.mocked(hierarchyApi.searchHierarchyNodes).mockResolvedValue({
      matches: [{ node: match, path: [division] }],
      has_more: true,
    });
    renderPicker();

    await screen.findByText("Root");
    fireEvent.change(screen.getByPlaceholderText("חיפוש..."), { target: { value: "Echo" } });

    expect(await screen.findByText("Division › Echo")).toBeInTheDocument();
    expect(hierarchyApi.searchHierarchyNodes).toHaveBeenCalledWith("Echo", expect.any(AbortSignal));
    expect(screen.getByText("team.hierarchy_search_more")).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(1);
  });

  it("shows a minimum-length hint for a settled one-character query without searching", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage).mockResolvedValue({
      items: [makeNode("root-1", "Root", null)],
      next_cursor: null,
      has_more: false,
    });
    renderPicker();

    fireEvent.change(screen.getByPlaceholderText("חיפוש..."), { target: { value: "א" } });

    expect(await screen.findByText("יש להקליד לפחות 2 תווים כדי לחפש")).toBeInTheDocument();
    expect(hierarchyApi.searchHierarchyNodes).not.toHaveBeenCalled();
  });
});
