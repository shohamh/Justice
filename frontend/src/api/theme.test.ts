import { describe, it, expect, vi } from "vitest";

const mockPatch = vi.fn();
vi.mock("./client", () => ({
  api: { patch: (...args: unknown[]) => mockPatch(...args) },
}));

describe("updateThemePreference", () => {
  it("PATCHes /me/theme-preference and returns the saved value", async () => {
    mockPatch.mockResolvedValue({ data: { theme_preference: "dark" } });
    const { updateThemePreference } = await import("./theme");

    const result = await updateThemePreference("dark");

    expect(mockPatch).toHaveBeenCalledWith("/me/theme-preference", { theme_preference: "dark" });
    expect(result).toBe("dark");
  });
});
