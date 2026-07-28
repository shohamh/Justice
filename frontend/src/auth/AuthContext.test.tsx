import { render, screen, act } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext";

const mockRefresh = vi.fn();
const mockFetchMe = vi.fn();

vi.mock("../api/client", () => ({
  api: { post: (...args: unknown[]) => mockRefresh(...args) },
  setAccessToken: vi.fn(),
}));
vi.mock("../api/auth", () => ({
  fetchMe: (...args: unknown[]) => mockFetchMe(...args),
}));

function Probe() {
  const { enrollmentPending } = useAuth();
  return <div data-testid="pending">{String(enrollmentPending)}</div>;
}

describe("AuthContext — enrollment_pending polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockRefresh.mockReset();
    mockFetchMe.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls fetchMe every 30s while enrollment_pending is true and picks up the flip to false", async () => {
    mockRefresh.mockResolvedValue({ data: { access_token: "t" } });
    mockFetchMe
      .mockResolvedValueOnce({ id: "1", enrollment_pending: true })
      .mockResolvedValueOnce({ id: "1", enrollment_pending: false });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId("pending").textContent).toBe("true");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });

    expect(screen.getByTestId("pending").textContent).toBe("false");
    expect(mockFetchMe).toHaveBeenCalledTimes(2);
  });

  it("does not poll once enrollment_pending is already false", async () => {
    mockRefresh.mockResolvedValue({ data: { access_token: "t" } });
    mockFetchMe.mockResolvedValue({ id: "1", enrollment_pending: false });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId("pending").textContent).toBe("false");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });

    expect(mockFetchMe).toHaveBeenCalledTimes(1);
  });
});
