import { render, screen, waitFor } from "@testing-library/react";

const mockGetPublicSettings = vi.fn(() => Promise.resolve({}));

vi.mock("../api/publicSettings", () => ({
  getPublicSettings: (...args: unknown[]) => mockGetPublicSettings(...args),
}));

describe("TelegramBadge", () => {
  beforeEach(() => {
    // usePublicSettings caches its result at module scope, so each test
    // needs a fresh module graph to pick up a different mocked response.
    vi.resetModules();
    mockGetPublicSettings.mockReset();
  });

  it("renders nothing when telegram.enabled is absent (default disabled)", async () => {
    mockGetPublicSettings.mockResolvedValue({});
    const { default: TelegramBadge } = await import("./TelegramBadge");
    const { container } = render(<TelegramBadge linked={true} />);
    await waitFor(() => {
      expect(container.firstChild).toBeNull();
    });
  });

  it("renders the badge when telegram.enabled is true", async () => {
    mockGetPublicSettings.mockResolvedValue({ "telegram.enabled": true });
    const { default: TelegramBadge } = await import("./TelegramBadge");
    render(<TelegramBadge linked={true} />);
    await waitFor(() => {
      expect(screen.getByTitle("Telegram מקושר")).toBeInTheDocument();
    });
  });

  it("renders nothing when telegram.enabled is false", async () => {
    mockGetPublicSettings.mockResolvedValue({ "telegram.enabled": false });
    const { default: TelegramBadge } = await import("./TelegramBadge");
    const { container } = render(<TelegramBadge linked={true} />);
    await waitFor(() => {
      expect(container.firstChild).toBeNull();
    });
  });

  it("recovers after a failed fetch (e.g. unauthenticated at /login) and uses the next successful fetch's real data", async () => {
    // Simulates: usePublicSettings is called once from /login before auth exists
    // (rejects, e.g. 401), then again later from a logged-in TelegramBadge. The
    // module-level cache/inflight state must not stay poisoned with {} forever.
    mockGetPublicSettings.mockRejectedValueOnce(new Error("401"));
    const { default: TelegramBadge } = await import("./TelegramBadge");

    const first = render(<TelegramBadge linked={true} />);
    await waitFor(() => {
      // Failed fetch falls back to {} -> telegram.enabled is absent -> hidden by default.
      expect(first.container.firstChild).toBeNull();
    });
    first.unmount();

    mockGetPublicSettings.mockResolvedValueOnce({ "telegram.enabled": true });
    render(<TelegramBadge linked={true} />);
    await waitFor(() => {
      // Real (second) fetch result must be observed, not the stale poisoned {}.
      expect(screen.getByTitle("Telegram מקושר")).toBeInTheDocument();
    });
  });
});
