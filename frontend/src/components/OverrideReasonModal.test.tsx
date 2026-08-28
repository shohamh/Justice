import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import OverrideReasonModal from "./OverrideReasonModal";

describe("OverrideReasonModal", () => {
  it("disables confirm until a reason is typed, then calls onConfirm with it", () => {
    const onConfirm = vi.fn();
    render(<OverrideReasonModal open count={2} onCancel={() => {}} onConfirm={onConfirm} />);

    const confirmButton = screen.getByRole("button", { name: /אישור/ });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "צורך מבצעי" } });
    expect(confirmButton).not.toBeDisabled();

    fireEvent.click(confirmButton);
    expect(onConfirm).toHaveBeenCalledWith("צורך מבצעי");
  });

  it("clears a previously-typed reason when closed and reopened, so a stale reason can't leak to a different action", () => {
    const onConfirm = vi.fn();
    const { rerender } = render(
      <OverrideReasonModal open count={1} onCancel={() => {}} onConfirm={onConfirm} />
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "נימוק ישן" } });
    expect(screen.getByRole("textbox")).toHaveValue("נימוק ישן");

    rerender(<OverrideReasonModal open={false} count={1} onCancel={() => {}} onConfirm={onConfirm} />);
    rerender(<OverrideReasonModal open count={1} onCancel={() => {}} onConfirm={onConfirm} />);

    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("button", { name: /אישור/ })).toBeDisabled();
  });
});
