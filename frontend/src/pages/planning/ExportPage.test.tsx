import { describe, test, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as XLSX from "xlsx";
import "../../i18n";
import { dfsOrder } from "./ExportPage";
import ExportPage from "./ExportPage";
import type { NodeDTO } from "../../api/hierarchy";

function mockNode(id: string, name: string, parent_id: string | null): NodeDTO {
  return {
    id,
    name,
    parent_id,
    level: "unit",
    commander_id: null,
    commander_name: null,
    path_ids: [],
    duty_managers: [],
    dm_manageable: true,
  };
}

test("dfsOrder groups children under their parent, not globally alphabetically", () => {
  // Root B comes before Root A alphabetically as siblings, but each root's
  // own children must stay nested under it, not interleaved globally.
  const nodes = [
    mockNode("root-a", "Alpha HQ", null),
    mockNode("root-b", "Bravo HQ", null),
    mockNode("a-child-2", "Zulu Squad", "root-a"),
    mockNode("a-child-1", "Echo Squad", "root-a"),
    mockNode("b-child-1", "Delta Squad", "root-b"),
  ];
  const order = dfsOrder(nodes);
  expect(order).toEqual(["root-a", "a-child-1", "a-child-2", "root-b", "b-child-1"]);
  // If the old buggy implementation were still in place, this would instead
  // produce a flat alphabetical-by-name order across ALL nodes regardless of
  // parent, e.g. interleaving "b-child-1" (Delta) between root-a's children.
});

vi.mock("../../api/scoring", () => ({ getTransparency: vi.fn().mockResolvedValue({ rows: [] }) }));
vi.mock("../../api/hierarchy", () => ({ fetchFullTree: vi.fn().mockResolvedValue([]) }));
vi.mock("../../api/client", () => ({ getAccessToken: vi.fn().mockReturnValue("test-token") }));
vi.mock("../../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

global.fetch = vi.fn().mockResolvedValue({
  ok: true,
  arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
});

describe("ExportPage", () => {
  it("renders one checkbox per exportable data type and a single export button", async () => {
    render(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    expect(screen.getByLabelText(/שקיפות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/תתי-יחידות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/סוגי תורנות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/מיקומי תורנות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/היררכיה/)).toBeInTheDocument();
    expect(screen.getByLabelText(/פטורים/)).toBeInTheDocument();
  });

  it("calls /config/export with only the checked config sheets when export is clicked", async () => {
    render(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    fireEvent.click(screen.getByLabelText(/סוגי תורנות/));
    fireEvent.click(screen.getByText("ייצוא"));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/config/export?sheets=duty_types"),
        expect.anything(),
      );
    });
  });

  it("merges /api/import/export sheets when the data checkbox is checked", async () => {
    const importWb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(importWb, XLSX.utils.aoa_to_sheet([["personal_number"], ["123"]]), "soldiers");
    const importBuf = XLSX.write(importWb, { type: "array", bookType: "xlsx" });

    const fetchMock = vi.fn().mockResolvedValue({
      arrayBuffer: () => Promise.resolve(importBuf),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ExportPage />);
    fireEvent.click(await screen.findByLabelText(/נתוני מערכת/));
    fireEvent.click(screen.getByText("ייצוא"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/import/export",
        expect.objectContaining({ headers: expect.any(Object) }),
      );
    });
  });
});
