// @vitest-environment node
import { describe, expect, it } from "vitest";

import config from "../vite.config";

type Group = { name: string; test: RegExp };

function chunkGroups(): Group[] {
  const output = config.build?.rolldownOptions?.output;
  const codeSplitting = (Array.isArray(output) ? output[0] : output)?.codeSplitting as { groups: Group[] };
  return codeSplitting.groups;
}

describe("build chunk groups", () => {
  it("keeps katex's globally imported stylesheet out of the katex chunk", () => {
    // main.tsx imports katex.min.css for the whole app. If the katex group captured
    // that CSS module, the entry would statically import the full katex chunk.
    const katex = chunkGroups().find((group) => group.name === "katex")!;
    for (const sep of ["/", "\\"]) {
      const root = ["C:", "app", "node_modules"].join(sep);
      expect(katex.test.test([root, "katex", "dist", "katex.min.css"].join(sep))).toBe(false);
      expect(katex.test.test([root, "katex", "dist", "katex.mjs"].join(sep))).toBe(true);
      expect(katex.test.test([root, "react-katex", "dist", "react-katex.js"].join(sep))).toBe(true);
    }
  });
});
