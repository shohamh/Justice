import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import HierarchyTreeDropdown from "./HierarchyTreeDropdown";

const nodes = [
  { id: "a", name: "פיקוד צפון", parent_id: null, path_ids: ["a"], children: [
    { id: "a1", name: "גדוד 1", parent_id: "a", path_ids: ["a", "a1"], children: [] },
  ] },
];

describe("HierarchyTreeDropdown", () => {
  it("shows top-level nodes expanded by default (matching HierarchyNodeFilter's own default), toggling collapse hides children", () => {
    render(<HierarchyTreeDropdown nodes={nodes} selected={[]} onChange={() => {}} triggerLabel="יחידה" />);
    fireEvent.click(screen.getByText("יחידה"));
    expect(screen.getByText("פיקוד צפון")).toBeInTheDocument();
    // HierarchyNodeFilter's per-node expand state defaults to expanded=true, so the
    // child is visible immediately — this differs from a naive "collapsed by default"
    // tree, but matches the real component's actual behavior.
    expect(screen.getByText("גדוד 1")).toBeInTheDocument();
    // Both the parent node and its leaf child default to expanded=true, so both
    // toggle buttons render aria-label="כווץ" (the leaf's glyph is just blank).
    // Click the first match — the top-level node's own toggle.
    fireEvent.click(screen.getAllByLabelText("כווץ")[0]);
    expect(screen.queryByText("גדוד 1")).not.toBeInTheDocument();
  });

  it("checking a node calls onChange with that node's id", () => {
    let selected: string[] = [];
    render(<HierarchyTreeDropdown nodes={nodes} selected={[]} onChange={(ids) => { selected = ids; }} triggerLabel="יחידה" />);
    fireEvent.click(screen.getByText("יחידה"));
    fireEvent.click(screen.getByLabelText("פיקוד צפון"));
    expect(selected).toEqual(["a"]);
  });
});
