import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import "./i18n";
import he from "./i18n/he.json";
import ProtectedRoute from "./auth/ProtectedRoute";

const mockUseAuth = vi.fn();
vi.mock("./auth/AuthContext", () => ({ useAuth: () => mockUseAuth() }));

const indexHtml = readFileSync(resolve(__dirname, "../index.html"), "utf8");

function rootMarkup(): string {
  const match = /<div id="root">([\s\S]*?)<\/div>\s*<script type="module"/.exec(indexHtml);
  if (!match) throw new Error("#root not found in index.html");
  return match[1];
}

describe("static boot placeholder in index.html", () => {
  it("paints a neutral loading status inside #root before any script runs", () => {
    const container = document.createElement("div");
    container.innerHTML = rootMarkup();
    const status = container.querySelector('[data-testid="boot-placeholder"]');
    expect(status).not.toBeNull();
    expect(status!.getAttribute("role")).toBe("status");
    expect(status!.getAttribute("aria-live")).toBe("polite");
    expect(status!.textContent!.trim()).toBe(he.app.loading);
    // No nav chrome: auth state is unknown before JS, and the login page must not flash a shell.
    expect(container.querySelector("nav, header, aside")).toBeNull();
    // CSP-safe and inert: no inline script inside the placeholder.
    expect(container.querySelector("script")).toBeNull();
  });

  it("needs no Heebo glyph outside the preloaded Hebrew subset before the JS runs", () => {
    // Anything else (even the "..." of the text) would make the browser fetch the
    // 30 kB Latin subset while the JS entry is still downloading.
    const container = document.createElement("div");
    container.innerHTML = rootMarkup();
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const nonHebrew = [...(node.textContent ?? "")].filter((ch) => !/[֐-׿]/.test(ch));
      if (nonHebrew.length === 0) continue;
      const styled = (node.parentElement as HTMLElement).closest<HTMLElement>("[style*='font-family']");
      expect(styled, `"${nonHebrew.join("")}" would render in Heebo`).not.toBeNull();
      expect(styled!.style.fontFamily).not.toMatch(/heebo/i);
    }
  });

  it("looks like PageLoading so React's first render swaps it without a visible jump", async () => {
    const { default: PageLoading } = await import("./components/PageLoading");
    render(<PageLoading />);
    const reactStatus = screen.getByRole("status");
    const container = document.createElement("div");
    container.innerHTML = rootMarkup();
    const status = container.querySelector<HTMLElement>('[data-testid="boot-placeholder"]')!;
    expect(status.style.padding).toBe(reactStatus.style.padding);
    expect(status.style.textAlign).toBe(reactStatus.style.textAlign);
    expect(status.textContent!.trim()).toBe(reactStatus.textContent);
  });
});

describe("ProtectedRoute during the session restore", () => {
  it("keeps the loading status on screen instead of rendering nothing", () => {
    mockUseAuth.mockReturnValue({ loggedIn: false, authLoading: true });
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<div data-testid="page" />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(he.app.loading);
    expect(screen.queryByTestId("page")).not.toBeInTheDocument();
  });
});
