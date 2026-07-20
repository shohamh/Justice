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

  it("renders the badge when telegram.enabled is absent (default enabled)", async () => {
    mockGetPublicSettings.mockResolvedValue({});
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
});
