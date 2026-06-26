import { test, expect } from "vitest";
import { dfsOrder } from "./ExportPage";
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
