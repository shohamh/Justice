import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ExemptionTypeViewModal from "./ExemptionTypeViewModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

const mockUpdateExemptionType = vi.fn(() =>
  Promise.resolve({ id: "e1", name: "פטור שמירות", description: null, is_global: false, is_medical: false, is_commander_exemption: false })
);
const mockSetExemptionDutyTypes = vi.fn(() => Promise.resolve(["d1", "d2"]));

vi.mock("../api/dutyConfig", () => ({
  updateExemptionType: (...args: unknown[]) => mockUpdateExemptionType(...args),
  setExemptionDutyTypes: (...args: unknown[]) => mockSetExemptionDutyTypes(...args),
}));

const exemptionType = {
  id: "e1", name: "פטור שמירות", description: null,
  is_global: false, is_medical: false, is_commander_exemption: false,
};
const dutyTypes = [
  { id: "d1", name: "שמירה", score_per_day: "1.0", description: null, active: true, contact_name: null, contact_phone: null, start_time: null, end_time: null, instructions: null, is_external: false, eligible_node_ids: null },
  { id: "d2", name: "מטבח", score_per_day: "1.0", description: null, active: true, contact_name: null, contact_phone: null, start_time: null, end_time: null, instructions: null, is_external: false, eligible_node_ids: null },
];

test("view mode shows the mapped duty type name and hides the pencil when canEdit is false", () => {
  render(
    <ExemptionTypeViewModal
      exemptionType={exemptionType}
      mappedDutyTypeIds={["d1"]}
      dutyTypes={dutyTypes}
      canEdit={false}
      onClose={() => {}}
      onSaved={() => {}}
    />
  );
  expect(screen.getByText("שמירה")).toBeInTheDocument();
  expect(screen.queryByTestId("exemption-edit-pencil")).not.toBeInTheDocument();
});

test("pencil is shown when canEdit is true, and clicking it reveals the edit form", () => {
  render(
    <ExemptionTypeViewModal
      exemptionType={exemptionType}
      mappedDutyTypeIds={["d1"]}
      dutyTypes={dutyTypes}
      canEdit={true}
      onClose={() => {}}
      onSaved={() => {}}
    />
  );
  fireEvent.click(screen.getByTestId("exemption-edit-pencil"));
  expect(screen.getByTestId("exemption-edit-global")).toBeInTheDocument();
});

test("saving edits calls updateExemptionType and setExemptionDutyTypes, then returns to view mode", async () => {
  const onSaved = vi.fn();
  render(
    <ExemptionTypeViewModal
      exemptionType={exemptionType}
      mappedDutyTypeIds={["d1"]}
      dutyTypes={dutyTypes}
      canEdit={true}
      onClose={() => {}}
      onSaved={onSaved}
    />
  );
  fireEvent.click(screen.getByTestId("exemption-edit-pencil"));
  fireEvent.click(screen.getByTestId("exemption-edit-dt-מטבח"));
  fireEvent.click(screen.getByTestId("exemption-edit-save"));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(mockUpdateExemptionType).toHaveBeenCalledWith("e1", {
    name: "פטור שמירות", is_global: false, is_medical: false, is_commander_exemption: false,
  });
  expect(mockSetExemptionDutyTypes).toHaveBeenCalledWith("e1", ["d1", "d2"]);
});

test("shows an error and stays in edit mode when updateExemptionType fails", async () => {
  mockUpdateExemptionType.mockRejectedValueOnce({ response: { data: { detail: "שגיאת שרת" } } });
  const onSaved = vi.fn();
  render(
    <ExemptionTypeViewModal
      exemptionType={exemptionType}
      mappedDutyTypeIds={["d1"]}
      dutyTypes={dutyTypes}
      canEdit={true}
      onClose={() => {}}
      onSaved={onSaved}
    />
  );
  fireEvent.click(screen.getByTestId("exemption-edit-pencil"));
  fireEvent.click(screen.getByTestId("exemption-edit-save"));
  await waitFor(() => expect(screen.getByText("שגיאת שרת")).toBeInTheDocument());
  expect(onSaved).not.toHaveBeenCalled();
  expect(screen.getByTestId("exemption-edit-save")).toBeInTheDocument();
});
