import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider, QueryClient } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import RegisterPage from "./RegisterPage";
import * as authApi from "../api/auth";
import * as registrationSettingsApi from "../api/registrationSettings";
import * as publicSettingsApi from "../api/publicSettings";
import { useAuth } from "../auth/AuthContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../api/auth");
vi.mock("../api/registrationSettings");
vi.mock("../api/publicSettings");
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
  const rankOption = screen.getByRole("button", { name: "טוראי" });
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
});
