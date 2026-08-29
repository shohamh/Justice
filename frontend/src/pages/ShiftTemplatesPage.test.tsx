import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ShiftTemplatesContent } from "./ShiftTemplatesPage";
import { deleteTemplate } from "../api/shiftTemplates";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: string | (Record<string, unknown> & { defaultValue?: string })) => {
      const fallback = typeof options === "string" ? options : options?.defaultValue;
      let template = fallback ?? key;
      if (options && typeof options === "object") {
        for (const [varName, value] of Object.entries(options)) {
          if (varName === "defaultValue") continue;
          template = template.replaceAll(`{{${varName}}}`, String(value));
        }
      }
      return template;
    },
  }),
}));
vi.mock("../api/shiftTemplates", () => ({
  listTemplates: vi.fn(() => Promise.resolve([{ id: "template-1", name: "לילה", duty_type_id: "type-1", recurrence_type: "daily", weekdays: [], duration_days: 1, required_count: 1, auto_roll: false }])),
  deleteTemplate: vi.fn(),
}));
vi.mock("../api/dutyConfig", () => ({ listDutyTypes: vi.fn(() => Promise.resolve([])), listLocations: vi.fn(() => Promise.resolve([])) }));
vi.mock("../components/DataTable", () => ({
  DataTable: ({ columns, data }: { columns: { id: string; cell: (row: unknown) => React.ReactNode }[]; data: unknown[] }) => <div>{data.flatMap((row, rowIndex) => columns.map(column => <div key={`${rowIndex}-${column.id}`}>{column.cell(row)}</div>))}</div>,
}));
vi.mock("../components/ShiftTemplateFormModal", () => ({ default: () => null }));
vi.mock("../components/GenerateShiftsModal", () => ({ default: () => null }));

describe("ShiftTemplatesContent", () => {
  it("does not delete a template until the styled confirmation is accepted", async () => {
    vi.mocked(deleteTemplate).mockResolvedValue(undefined);
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ShiftTemplatesContent /></QueryClientProvider>);

    fireEvent.click(await screen.findByText("shift_templates.delete"));
    expect(deleteTemplate).not.toHaveBeenCalled();
    expect(screen.getByText("מחיקת תבנית")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));

    await waitFor(() => expect(deleteTemplate).toHaveBeenCalledWith("template-1"));
  });
});
