import { fireEvent, render, screen } from "@testing-library/react";
import ConfirmDialog from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders Hebrew fallback labels and confirms only when confirmed", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<ConfirmDialog open title="מחיקה" message="למחוק?" onConfirm={onConfirm} onClose={onClose} />);

    expect(screen.getByRole("button", { name: "ביטול" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "אישור" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "ביטול" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "אישור" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("applies danger styling to the confirm action", () => {
    render(<ConfirmDialog open title="מחיקה" message="למחוק?" danger onConfirm={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: "אישור" })).toHaveClass("bg-red-600");
  });
});
