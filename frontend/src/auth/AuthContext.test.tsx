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

describe("AuthContext — periodic refresh while logged in", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockRefresh.mockReset();
    mockFetchMe.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls fetchMe every 60s while logged in and picks up server-side changes (e.g. an approved profile field update)", async () => {
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
      await vi.advanceTimersByTimeAsync(60000);
    });

    expect(screen.getByTestId("pending").textContent).toBe("false");
    expect(mockFetchMe).toHaveBeenCalledTimes(2);
  });

  it("does not poll before the initial login/mount fetch resolves", async () => {
    mockRefresh.mockReturnValue(new Promise(() => {})); // never resolves
    mockFetchMe.mockResolvedValue({ id: "1", enrollment_pending: false });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });

    expect(mockFetchMe).toHaveBeenCalledTimes(0);
  });
});
