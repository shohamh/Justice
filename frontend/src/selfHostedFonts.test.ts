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

  it("declares Hebrew and Latin subsets for every weight the Google stylesheet provided", () => {
    const faces = heeboFaces();
    for (const weight of ["300", "400", "500", "700"]) {
      const forWeight = faces.filter((face) => face.weight === weight);
      expect(forWeight.map((face) => face.src).sort()).toEqual([
        "/fonts/Heebo-v28-hebrew.woff2",
        "/fonts/Heebo-v28-latin.woff2",
      ]);
      expect(forWeight.find((face) => face.src.endsWith("hebrew.woff2"))!.range).toContain("U+0590-05FF");
      expect(forWeight.find((face) => face.src.endsWith("latin.woff2"))!.range).toContain("U+0000-00FF");
    }
    expect(globalsCss.match(/@font-face\s*{[^}]*Heebo[^}]*}/g)!.every((b) => /font-display:\s*swap/.test(b))).toBe(true);
  });

  it("ships real woff2 files with the OFL licence next to them", () => {
    for (const file of ["Heebo-v28-hebrew.woff2", "Heebo-v28-latin.woff2"]) {
      expect(read(`public/fonts/${file}`).subarray(0, 4).toString("latin1")).toBe("wOF2");
    }
    expect(read("public/fonts/Heebo-OFL.txt").toString("utf8")).toContain("SIL OPEN FONT LICENSE Version 1.1");
  });

  it("preloads the Hebrew subset from index.html as a CORS font request", () => {
    const preload = indexHtml.match(/<link[^>]*rel="preload"[^>]*>/g)?.find((tag) => tag.includes("Heebo"));
    expect(preload).toBeDefined();
    expect(preload).toContain('href="/fonts/Heebo-v28-hebrew.woff2"');
    expect(preload).toContain('as="font"');
    expect(preload).toContain('type="font/woff2"');
    expect(preload).toMatch(/\scrossorigin(\s|>|=)/);
  });
});
