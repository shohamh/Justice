// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const frontendRoot = resolve(__dirname, "..");
const read = (path: string) => readFileSync(resolve(frontendRoot, path));
const globalsCss = read("src/styles/globals.css").toString("utf8");
const indexHtml = read("index.html").toString("utf8");

function heeboFaces(): { src: string; weight: string; range: string }[] {
  const blocks = globalsCss.match(/@font-face\s*{[^}]*}/g) ?? [];
  return blocks
    .filter((block) => /font-family:\s*["']Heebo["']/.test(block))
    .map((block) => ({
      src: /url\(["']?([^"')]+)["']?\)/.exec(block)?.[1] ?? "",
      weight: /font-weight:\s*([^;]+);/.exec(block)?.[1].trim() ?? "",
      range: /unicode-range:\s*([^;]+);/.exec(block)?.[1].trim() ?? "",
    }));
}

describe("self-hosted Heebo", () => {
  it("does not load any stylesheet or font from Google", () => {
    expect(globalsCss).not.toMatch(/fonts\.(googleapis|gstatic)\.com/);
    expect(indexHtml).not.toMatch(/fonts\.(googleapis|gstatic)\.com/);
  });

  it("declares every subset the Google stylesheet provided, for every weight it provided", () => {
    const faces = heeboFaces();
    const subsets = { hebrew: "U+0590-05FF", math: "U+1D400-1D7FF", symbols: "U+2800-28FF", "latin-ext": "U+0100-02BA", latin: "U+0000-00FF" };
    for (const weight of ["300", "400", "500", "700"]) {
      const forWeight = faces.filter((face) => face.weight === weight);
      expect(forWeight.map((face) => face.src).sort()).toEqual(
        Object.keys(subsets).map((subset) => `/fonts/Heebo-v28-${subset}.woff2`).sort(),
      );
      for (const [subset, range] of Object.entries(subsets)) {
        expect(forWeight.find((face) => face.src.endsWith(`-${subset}.woff2`))!.range).toContain(range);
      }
    }
    expect(globalsCss.match(/@font-face\s*{[^}]*Heebo[^}]*}/g)!.every((b) => /font-display:\s*swap/.test(b))).toBe(true);
  });

  it("ships real woff2 files with the OFL licence next to them", () => {
    for (const subset of ["hebrew", "math", "symbols", "latin-ext", "latin"]) {
      const file = `Heebo-v28-${subset}.woff2`;
      expect(read(`public/fonts/${file}`).subarray(0, 4).toString("latin1")).toBe("wOF2");
    }
    expect(read("public/fonts/Heebo-OFL.txt").toString("utf8")).toContain("SIL OPEN FONT LICENSE Version 1.1");
  });

  it("does not preload any font: a font fetched before the JS boots delays the shell", () => {
    // Measured in follow-up batch 6 (docs/benchmarks/2026-10-08-shell-load.md).
    expect(indexHtml).not.toMatch(/<link[^>]*rel="preload"[^>]*as="font"/);
    expect(indexHtml).not.toMatch(/<link[^>]*as="font"[^>]*rel="preload"/);
  });
});
