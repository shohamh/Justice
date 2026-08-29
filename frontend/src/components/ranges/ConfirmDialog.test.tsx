import { fireEvent, render, screen } from "@testing-library/react";
import ConfirmDialog from "./ConfirmDialog";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => key === "common.confirm" ? "אישור" : key === "common.cancel" ? "ביטול" : options?.defaultValue ?? key,
  }),
}));

describe("ranges ConfirmDialog compatibility wrapper", () => {
  it("uses translated defaults for the preserved reason field", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDialog open title="ניקוי" message="לנקות?" reasonLabel="סיבה" onConfirm={onConfirm} onClose={vi.fn()} />);

    expect(screen.getByRole("button", { name: "אישור" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ביטול" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "סיבה" }), { target: { value: "  סיבה  " } });
    fireEvent.click(screen.getByRole("button", { name: "אישור" }));
    expect(onConfirm).toHaveBeenCalledWith("סיבה");
  });
});
