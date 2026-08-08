import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DismissalModal from "./DismissalModal";
import { CalendarShift, CalendarShiftAssignee } from "../api/calendar";

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

function renderModal() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <DismissalModal shift={shift} primary={primary} canGimelim={false} defaultRestDays={0} onClose={() => {}} onDone={() => {}} />
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
