import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DismissalModal from "./DismissalModal";
import { CalendarShift, CalendarShiftAssignee } from "../api/calendar";
import { GimelimPreview, commitGimelim, previewGimelim } from "../api/gimelim";
import { dismissAndReallocate } from "../api/reserves";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}));

vi.mock("../api/reserves", () => ({
  dismissAndReallocate: vi.fn(() => Promise.resolve({})),
}));

vi.mock("../api/gimelim", () => ({
  previewGimelim: vi.fn(() => Promise.resolve({})),
  commitGimelim: vi.fn(() => Promise.resolve({})),
  uploadGimelimAttachment: vi.fn(() => Promise.resolve({})),
}));

const shift: CalendarShift = {
  id: "s1",
  duty_type_id: "d1",
  duty_type_name: "duty",
  duty_type_color: "#fff",
  duty_location_name: "loc",
  start_date: "2026-08-01",
  end_date: "2026-08-05",
  start_time: "08:00",
  end_time: "08:00",
  start_at: "2026-08-01T08:00:00Z",
  end_at: "2026-08-05T08:00:00Z",
  required_count: 1,
  assigned_count: 1,
  fill_status: "full",
  reserve_count: 0,
  assignees: [],
};

const primary: CalendarShiftAssignee = {
  assignment_id: "a1",
  soldier_id: "sol1",
  soldier_name: "Soldier One",
  hierarchy_label: null,
  is_reserve: false,
  profile_picture_url: null,
  dismissals: [],
  reserve_assignment_id: null,
  reserve_hierarchy_distance: null,
  called_up_from: null,
  called_up_to: null,
  primary_assignment_ids: [],
  hierarchy_path_ids: [],
  weapon_ineligible: false,
  weapon_ineligible_reason: null,
};

function renderModal(
  canGimelim = false,
  options: { modalShift?: CalendarShift; modalPrimary?: CalendarShiftAssignee; onDone?: () => void } = {},
) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <SoldierModalProvider>
        <DismissalModal
          shift={options.modalShift ?? shift}
          primary={options.modalPrimary ?? primary}
          canGimelim={canGimelim}
          defaultRestDays={0}
          onClose={() => {}}
          onDone={options.onDone ?? (() => {})}
        />
      </SoldierModalProvider>
    </QueryClientProvider>
  );
}

test("prompts for the start date before the end date when the modal opens", () => {
  renderModal();
  expect(screen.getByText("בחר תאריך התחלה")).toBeInTheDocument();
  expect(screen.queryByText("בחר תאריך סיום")).not.toBeInTheDocument();
});

test("prompts for the end date after the start day is picked", () => {
  const { container } = renderModal();
  const dayButtons = Array.from(container.querySelectorAll("button")).filter(
    (b) => b.children.length === 2
  );
  expect(dayButtons.length).toBeGreaterThan(0);
  fireEvent.click(dayButtons[0]);
  expect(screen.getByText("בחר תאריך סיום")).toBeInTheDocument();
});

test("shows the current shift's last inclusive duty day, not its raw exclusive end_date, in the gimelim preview", async () => {
  const preview: GimelimPreview = {
    preview_token: "tok1",
    preview_token_expires_at: "2026-08-10T00:00:00Z",
    current_shift: {
      shift_id: "s1",
      duty_type_name: "duty",
      duty_location_name: "loc",
      start_date: "2026-08-01",
      end_date: "2026-08-05",
    },
    soldier_a: { id: "sol1", name: "Soldier One", rank: null },
    primary_assignment_id: "a1",
    reserve_assignment_id: "ra1",
    reserve_soldier: { id: "sol2", name: "Soldier Two", rank: null },
    future_assignment: null,
    warnings: [],
  };
  vi.mocked(previewGimelim).mockResolvedValueOnce(preview);

  renderModal(true);
  fireEvent.click(screen.getByText("dismiss_modal.mode_gimelim"));
  fireEvent.change(screen.getByPlaceholderText("פרטים רפואיים (לא מועברים לחיילים אחרים)"), {
    target: { value: "reason" },
  });
  fireEvent.click(screen.getByText("חשב הצעה ⟶"));

  await waitFor(() => {
    expect(screen.getByText(/2026-08-01/)).toBeInTheDocument();
  });
  expect(screen.getByText(/2026-08-04/)).toBeInTheDocument();
  expect(screen.queryByText(/2026-08-05/)).not.toBeInTheDocument();
});

test("exposes the gimelim preview and commit boundaries", async () => {
  const preview: GimelimPreview = {
    preview_token: "tok-commit",
    preview_token_expires_at: "2026-08-10T00:00:00Z",
    current_shift: {
      shift_id: "s1",
      duty_type_name: "duty",
      duty_location_name: "loc",
      start_date: "2026-08-01",
      end_date: "2026-08-05",
    },
    soldier_a: { id: "sol1", name: "Soldier One", rank: null },
    primary_assignment_id: "a1",
    reserve_assignment_id: "reserve-1",
    reserve_soldier: { id: "sol2", name: "Reserve One", rank: null },
    future_assignment: null,
    warnings: [],
  };
  const onDone = vi.fn();
  vi.mocked(previewGimelim).mockResolvedValueOnce(preview);
  vi.mocked(commitGimelim).mockResolvedValueOnce({
    dismissal_id: "dismissal-1",
    call_up_assignment_id: "reserve-1",
    future_primary_assignment_id: null,
    future_demoted_assignment_id: null,
    notifications_queued: 0,
  });

  renderModal(true, { onDone });
  fireEvent.click(screen.getByTestId("dismissal-mode-gimelim"));
  fireEvent.change(screen.getByPlaceholderText("פרטים רפואיים (לא מועברים לחיילים אחרים)"), {
    target: { value: "illness" },
  });
  fireEvent.click(screen.getByTestId("gimelim-preview-action"));

  await screen.findByTestId("gimelim-preview");
  expect(screen.getByTestId("gimelim-preview")).toHaveTextContent("Reserve One");
  fireEvent.click(screen.getByTestId("gimelim-commit-action"));

  await waitFor(() => expect(commitGimelim).toHaveBeenCalledWith("s1", "tok-commit"));
  expect(onDone).toHaveBeenCalledTimes(1);
});

test("selects a covering reserve and saves the existing dismissal reallocation", async () => {
  const reserveOne: CalendarShiftAssignee = {
    ...primary,
    assignment_id: "reserve-1",
    soldier_id: "reserve-soldier-1",
    soldier_name: "Reserve One",
    is_reserve: true,
  };
  const reserveTwo: CalendarShiftAssignee = {
    ...reserveOne,
    assignment_id: "reserve-2",
    soldier_id: "reserve-soldier-2",
    soldier_name: "Reserve Two",
  };
  const onDone = vi.fn();
  vi.mocked(dismissAndReallocate).mockResolvedValueOnce({
    dismissal_id: "dismissal-1",
    covering_reserve: { assignment_id: "reserve-2", called_up_from: "2026-08-01", called_up_to: "2026-08-04" },
    reallocations: [],
  });

  renderModal(false, {
    modalShift: { ...shift, assignees: [primary, reserveOne, reserveTwo] },
    modalPrimary: { ...primary, reserve_assignment_id: "reserve-1" },
    onDone,
  });
  fireEvent.focus(screen.getByTestId("dismissal-covering-reserve"));
  const reserveTwoOption = await screen.findByRole("button", { name: "Reserve Two" });
  fireEvent.pointerDown(reserveTwoOption);
  fireEvent.pointerUp(reserveTwoOption);
  fireEvent.change(screen.getByPlaceholderText("dismiss_modal.reason_placeholder"), {
    target: { value: "unavailable" },
  });
  fireEvent.click(screen.getByTestId("dismissal-save-replacement"));

  await waitFor(() => expect(dismissAndReallocate).toHaveBeenCalledWith("s1", {
    primary_assignment_id: "a1",
    covering_reserve_assignment_id: "reserve-2",
    from_date: "2026-08-01",
    to_date: "2026-08-04",
    reason: "unavailable",
  }));
  expect(onDone).toHaveBeenCalledTimes(1);
});
