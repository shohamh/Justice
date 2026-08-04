import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RangeBulkCancelDialog from "./RangeBulkCancelDialog";

describe("RangeBulkCancelDialog", () => {
  it("requires a reason and reports the selected count before confirming", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(<RangeBulkCancelDialog open count={3} onClose={vi.fn()} onConfirm={onConfirm} />);

    expect(screen.getByText(/3/)).toBeInTheDocument();
    const confirmButton = screen.getByTestId("confirm-bulk-cancel-button");
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("סיבת הביטול"), { target: { value: "מזג אוויר" } });
    expect(confirmButton).not.toBeDisabled();
    fireEvent.click(confirmButton);
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("מזג אוויר"));
  });
});
