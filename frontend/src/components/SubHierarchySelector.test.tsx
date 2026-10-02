import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as hierarchyApi from "../api/hierarchy";
import SubHierarchySelector from "./SubHierarchySelector";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn(),
  fetchHierarchyBranchPage: vi.fn(),
  isStaleHierarchyCursorError: vi.fn(() => false),
}));
vi.mock("../api/auth", () => ({ getTransparencyAuthorizationScope: () => "viewer-scope" }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { id: "viewer", role: "admin", scope_root_ids: [] }, authScopeReady: true }) }));

const node = (id: string, name: string, hasChildren: boolean) => ({
  id,
  level: "unit" as const,
  name,
  parent_id: null,
  commander_id: null,
  commander_name: null,
  path_ids: [id],
  duty_managers: [],
  dm_manageable: false,
  can_edit: false,
  has_children: hasChildren,
});

function renderSelector(value: string[] = [], onChange = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <SubHierarchySelector value={value} onChange={onChange} />
    </QueryClientProvider>,
  );
  return { ...rendered, onChange, queryClient };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hierarchyApi.fetchTree).mockResolvedValue([node("root", "Root", true)]);
  vi.mocked(hierarchyApi.fetchHierarchyBranchPage).mockResolvedValue({
    items: [node("root", "Root", true)], next_cursor: null, has_more: false,
  });
});

describe("SubHierarchySelector", () => {
  it("loads only roots on mount and fetches one branch when expanded", async () => {
    renderSelector();

    expect(await screen.findByRole("checkbox", { name: "Root" })).toBeInTheDocument();
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(1);
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledWith(expect.objectContaining({ parentId: null }));

    fireEvent.click(screen.getByRole("button", { name: /hierarchy_expand Root/ }));
    await waitFor(() => expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenCalledTimes(2));
    expect(hierarchyApi.fetchHierarchyBranchPage).toHaveBeenLastCalledWith(expect.objectContaining({ parentId: "root" }));
  });

  it("appends cursor pages and keeps already loaded siblings after a page error", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage)
      .mockResolvedValueOnce({ items: [node("root", "Root", true)], next_cursor: null, has_more: false })
      .mockResolvedValueOnce({ items: [node("child-1", "First child", false)], next_cursor: "next", has_more: true })
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({ items: [node("child-2", "Second child", false)], next_cursor: null, has_more: false });
    renderSelector();
    fireEvent.click(await screen.findByRole("button", { name: /hierarchy_expand Root/ }));

    expect(await screen.findByRole("checkbox", { name: "First child" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "team.hierarchy_load_more" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("team.hierarchy_load_failed");
    expect(screen.getByRole("checkbox", { name: "First child" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "team.hierarchy_retry" }));
    expect(await screen.findByRole("checkbox", { name: "Second child" })).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  });

  it("appends additional roots without duplicating IDs", async () => {
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage)
      .mockResolvedValueOnce({ items: [node("root", "Root", false)], next_cursor: "next", has_more: true })
      .mockResolvedValueOnce({ items: [node("root", "Root", false), node("root-2", "Second root", false)], next_cursor: null, has_more: false });
    renderSelector();
    expect(await screen.findByRole("checkbox", { name: "Root" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "team.hierarchy_load_more" }));
    expect(await screen.findByRole("checkbox", { name: "Second root" })).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });

  it("retains explicit selected IDs across collapse and reopen", async () => {
    const onChange = vi.fn();
    vi.mocked(hierarchyApi.fetchHierarchyBranchPage)
      .mockResolvedValueOnce({ items: [node("root", "Root", true)], next_cursor: null, has_more: false })
      .mockResolvedValue({ items: [node("child", "Child", false)], next_cursor: null, has_more: false });
    renderSelector(["hidden-selection"], onChange);
    const expand = await screen.findByRole("button", { name: /hierarchy_expand Root/ });
    fireEvent.click(expand);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Child" }));
    expect(onChange).toHaveBeenLastCalledWith(["hidden-selection", "child"]);
    fireEvent.click(screen.getByRole("button", { name: /hierarchy_collapse Root/ }));
    expect(screen.queryByRole("checkbox", { name: "Child" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /hierarchy_expand Root/ }));
    expect(await screen.findByRole("checkbox", { name: "Child" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Child" })).not.toBeChecked();
  });
});
