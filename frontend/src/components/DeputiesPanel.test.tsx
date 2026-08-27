import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DeputiesPanel from "./DeputiesPanel";

// A tiny stand-in dict for keys this suite needs resolved to their real
// translated text (e.g. so translateApiError's error-code mapping is
// actually exercised, not just its fallback path). Any key not present
// here falls through to the fallback/defaultValue behaviour the other
// tests in this file already rely on, matching real i18next's
// t(key, defaultValueString) shorthand.
const dict: Record<string, string> = {
  "errors.principal_lacks_role": "החייל שנבחר אינו מפקד/אחראי תורנויות כרגע",
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallbackOrOptions?: string | { defaultValue?: string }) => {
      if (key in dict) return dict[key];
      if (typeof fallbackOrOptions === "string") return fallbackOrOptions;
      if (fallbackOrOptions && typeof fallbackOrOptions === "object") {
        return fallbackOrOptions.defaultValue ?? key;
      }
      return key;
    },
  }),
}));

const mockListDeputies = vi.fn();
const mockCreateDeputy = vi.fn();
const mockRevokeDeputy = vi.fn();
vi.mock("../api/deputies", () => ({
  listDeputies: (...args: unknown[]) => mockListDeputies(...args),
  createDeputy: (...args: unknown[]) => mockCreateDeputy(...args),
  revokeDeputy: (...args: unknown[]) => mockRevokeDeputy(...args),
}));

vi.mock("../api/soldiers", () => ({
  listSoldiers: vi.fn(() =>
    Promise.resolve([
      { id: "s1", full_name: "יוסי כהן", personal_number: "1234567", role: "soldier" },
    ])
  ),
}));

const grant = {
  id: "g1", principal_id: "p1", principal_name: "מפקד", deputy_id: "s1", deputy_name: "יוסי כהן",
  role: "commander" as const, start_date: "2026-01-01", end_date: "2026-12-31",
};

beforeEach(() => {
  mockListDeputies.mockReset();
  mockCreateDeputy.mockReset();
  mockRevokeDeputy.mockReset();
  mockListDeputies.mockResolvedValue([grant]);
});

test("lists existing deputy grants", async () => {
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  expect(await screen.findByText("יוסי כהן")).toBeInTheDocument();
});

test("creates a new deputy grant", async () => {
  mockCreateDeputy.mockResolvedValue({ ...grant, id: "g2" });
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  await screen.findByText("יוסי כהן");

  fireEvent.change(screen.getByPlaceholderText("חיפוש חייל..."), { target: { value: "יוסי" } });
  fireEvent.click(await screen.findByText(/יוסי כהן/));
  fireEvent.change(screen.getByLabelText("מתאריך"), { target: { value: "2026-02-01" } });
  fireEvent.change(screen.getByLabelText("עד תאריך"), { target: { value: "2026-02-28" } });
  fireEvent.click(screen.getByText("הוסף ממלא מקום"));

  await waitFor(() =>
    expect(mockCreateDeputy).toHaveBeenCalledWith({
      principal_id: "p1", deputy_id: "s1", role: "commander",
      start_date: "2026-02-01", end_date: "2026-02-28",
    })
  );
});

test("start/end date fields are styled consistently with every other date input in the app", async () => {
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  await screen.findByText("יוסי כהן");

  const start = screen.getByLabelText("מתאריך");
  const end = screen.getByLabelText("עד תאריך");
  expect(start.className).toContain("border");
  expect(start.className).toContain("rounded");
  expect(start.className).toContain("dark:bg-gray-700");
  expect(end.className).toContain("border");
  expect(end.className).toContain("rounded");
  expect(end.className).toContain("dark:bg-gray-700");
});

test("revokes an existing grant", async () => {
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  mockRevokeDeputy.mockResolvedValue(undefined);
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  await screen.findByText("יוסי כהן");

  fireEvent.click(screen.getByText("הסר"));

  await waitFor(() => expect(mockRevokeDeputy).toHaveBeenCalledWith("g1"));
  confirmSpy.mockRestore();
});

test("role select is hidden and fixed to commander when principal only holds that role", async () => {
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  await screen.findByText("יוסי כהן");
  expect(screen.queryByLabelText("תפקיד")).not.toBeInTheDocument();
});

test("role select is shown when principal holds both roles", async () => {
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: true }} />);
  await screen.findByText("יוסי כהן");
  expect(screen.getByLabelText("תפקיד")).toBeInTheDocument();
});

test("shows the specific backend error reason instead of a generic message", async () => {
  mockCreateDeputy.mockRejectedValue({
    response: { data: { detail: "principal_lacks_role" } },
  });
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  await screen.findByText("יוסי כהן");

  fireEvent.change(screen.getByPlaceholderText("חיפוש חייל..."), { target: { value: "יוסי" } });
  fireEvent.click(await screen.findByText(/יוסי כהן/));
  fireEvent.click(screen.getByText("הוסף ממלא מקום"));

  await waitFor(() =>
    expect(screen.getByText("החייל שנבחר אינו מפקד/אחראי תורנויות כרגע")).toBeInTheDocument()
  );
  expect(screen.queryByText("שגיאה")).not.toBeInTheDocument();
});
