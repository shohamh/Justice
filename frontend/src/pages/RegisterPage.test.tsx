import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider, QueryClient } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import RegisterPage from "./RegisterPage";
import * as authApi from "../api/auth";
import * as registrationSettingsApi from "../api/registrationSettings";
import * as publicSettingsApi from "../api/publicSettings";
import * as rankAdvancementApi from "../api/rankAdvancement";
import { useAuth } from "../auth/AuthContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../api/auth");
vi.mock("../api/registrationSettings");
vi.mock("../api/publicSettings");
vi.mock("../api/rankAdvancement");
vi.mock("../auth/AuthContext");

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useAuth).mockReturnValue({
    loginWithToken: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>);
  vi.mocked(registrationSettingsApi.getRegistrationPublicSettings).mockResolvedValue({ email_domain_hint: null });
  vi.mocked(publicSettingsApi.getPublicSettings).mockResolvedValue({});
  vi.mocked(authApi.validateInviteCode).mockResolvedValue(true);
  vi.mocked(authApi.fetchRegisterNodes).mockResolvedValue([]);
  vi.mocked(authApi.listPublicExemptionTypes).mockResolvedValue([
    { id: "et-medical", name: "פטור רפואי", description: null, is_medical: true },
    { id: "et-regular", name: "פטור רגיל", description: null, is_medical: false },
  ]);
  vi.mocked(rankAdvancementApi.getRankLadder).mockResolvedValue({
    enlisted: [
      { rank: "טוראי", months_to_next: 4 },
      { rank: "רבט", months_to_next: null },
      { rank: "סמל", months_to_next: null },
      { rank: "סמר", months_to_next: null },
      { rank: "רסל", months_to_next: null },
      { rank: "רסר", months_to_next: null },
      { rank: "רסמ", months_to_next: null },
      { rank: "רסב", months_to_next: null },
      { rank: "רנג", months_to_next: null },
    ],
    officer: [
      { rank: "קמא", months_to_next: null },
      { rank: "סגמ", months_to_next: null },
      { rank: "סגן", months_to_next: null },
      { rank: "קאב", months_to_next: null },
      { rank: "סרן", months_to_next: null },
      { rank: "קאם", months_to_next: null },
      { rank: "רסן", months_to_next: null },
      { rank: "סאל", months_to_next: null },
      { rank: "אלמ", months_to_next: null },
      { rank: "תאל", months_to_next: null },
      { rank: "אלוף", months_to_next: null },
      { rank: "רב אלוף", months_to_next: null },
    ],
  });
});

// getByRole("combobox") also matches native <select> elements, so pick the
// element that carries the Combobox component's own aria-haspopup marker.
function getComboboxInput(): HTMLElement {
  const candidates = screen.getAllByRole("combobox");
  const match = candidates.find(el => el.getAttribute("aria-haspopup") === "listbox");
  if (!match) throw new Error("No Combobox input found");
  return match;
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><RegisterPage /></MemoryRouter>
    </QueryClientProvider>
  );
}

async function goToExemptionsStep() {
  renderPage();
  fireEvent.change(screen.getByLabelText(/register.invite_code_label/), { target: { value: "CODE1" } });
  fireEvent.click(screen.getByText("register.next"));
  await waitFor(() => expect(authApi.validateInviteCode).toHaveBeenCalled());

  fireEvent.change(screen.getByLabelText(/מספר אישי/), { target: { value: "1234567" } });
  fireEvent.change(screen.getByLabelText(/שם מלא/), { target: { value: "ישראל ישראלי" } });
  fireEvent.change(screen.getByLabelText(/טלפון/), { target: { value: "0501234567" } });
  fireEvent.change(screen.getByLabelText(/אימייל/), { target: { value: "a@b.com" } });
  fireEvent.change(screen.getByLabelText(/מגדר/), { target: { value: "male" } });
  fireEvent.change(screen.getByLabelText(/תאריך גיוס/), { target: { value: "01012024" } });
  fireEvent.change(screen.getByLabelText(/סיום חובה/), { target: { value: "01012026" } });
  fireEvent.change(screen.getByLabelText(/מטווח אחרון/), { target: { value: "01012025" } });
  fireEvent.change(screen.getByLabelText(/שחרור/), { target: { value: "01012027" } });
  fireEvent.change(screen.getByLabelText(/^סיסמה/), { target: { value: "a-long-enough-pass1" } });
  fireEvent.change(screen.getByLabelText(/^אימות סיסמה/), { target: { value: "a-long-enough-pass1" } });

  // Rank via Combobox: proven pattern (see MyRequestsPage.test.tsx) is
  // fireEvent.focus on the combobox's own input (getByText on the wrapping
  // label doesn't reach the nested input) followed by pointerDown/pointerUp
  // on the visible option button — a plain click doesn't trigger selection.
  fireEvent.focus(getComboboxInput());
  const rankOption = await screen.findByRole("button", { name: "טוראי" });
  fireEvent.pointerDown(rankOption);
  fireEvent.pointerUp(rankOption);

  await waitFor(() => expect(screen.getByText("register.next")).not.toBeDisabled());
  fireEvent.click(screen.getByText("register.next"));
  await screen.findByText("register.step_exemptions");
}

describe("RegisterPage - exemption rows", () => {
  it("permanent checkbox on a row disables its date fields", async () => {
    await goToExemptionsStep();
    fireEvent.click(screen.getByText("+ register.add_exemption"));

    expect(screen.getByTestId("register-er-permanent-0")).not.toBeChecked();

    fireEvent.click(screen.getByTestId("register-er-permanent-0"));

    const inputs = screen.getAllByRole("textbox");
    const dateInputs = inputs.filter(el => el.hasAttribute("disabled"));
    expect(dateInputs.length).toBeGreaterThanOrEqual(2);
  });

  it("blocks proceeding past the exemptions step when a medical row has no file", async () => {
    await goToExemptionsStep();
    fireEvent.click(screen.getByText("+ register.add_exemption"));

    fireEvent.focus(getComboboxInput());
    const medicalOption = screen.getByRole("button", { name: "פטור רפואי 🏥" });
    fireEvent.pointerDown(medicalOption);
    fireEvent.pointerUp(medicalOption);

    expect(screen.getByText("register.next")).toBeDisabled();
  });

  // Regression tests: unlike MyRequestsPage, RegisterPage's per-row file
  // picker used to have no size cap, and files that failed the magic-byte
  // signature check were silently dropped from `valid` with zero feedback —
  // a soldier attaching a genuine oversized or funky-header PDF saw nothing
  // happen and "next" just stayed disabled with no explanation.
  it("shows the oversized file in a rejected-files list instead of silently dropping it", async () => {
    await goToExemptionsStep();
    fireEvent.click(screen.getByText("+ register.add_exemption"));

    const input = screen.getByTestId("register-er-files-0");
    const bigFile = new File([new Uint8Array(11 * 1024 * 1024)], "big.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [bigFile] } });

    await waitFor(() => expect(screen.getByText("exemption_requests.file_too_large")).toBeInTheDocument());
    expect(screen.getByText("big.pdf")).toBeInTheDocument();
  });

  it("shows a file with a bad magic-byte signature in the rejected-files list instead of dropping it silently", async () => {
    await goToExemptionsStep();
    fireEvent.click(screen.getByText("+ register.add_exemption"));

    const input = screen.getByTestId("register-er-files-0");
    const badFile = new File(["not actually a pdf"], "fake.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [badFile] } });

    await waitFor(() => expect(screen.getByText("exemption_requests.file_too_large")).toBeInTheDocument());
    expect(screen.getByText("fake.pdf")).toBeInTheDocument();
  });

  it("keeps each row's rejected-files list independent", async () => {
    await goToExemptionsStep();
    fireEvent.click(screen.getByText("+ register.add_exemption"));
    fireEvent.click(screen.getByText("+ register.add_exemption"));

    const badFile = new File(["nope"], "row0-bad.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByTestId("register-er-files-0"), { target: { files: [badFile] } });
    await waitFor(() => expect(screen.getByText("row0-bad.pdf")).toBeInTheDocument());

    // Row 1's dropzone shouldn't show row 0's rejected file.
    expect(screen.queryAllByText("row0-bad.pdf")).toHaveLength(1);
  });
});
