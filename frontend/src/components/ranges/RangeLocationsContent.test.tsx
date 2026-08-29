import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RangeLocationsContent from "./RangeLocationsContent";

describe("RangeLocationsContent", () => {
  it("lists existing locations and creates a new location for managers", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(
      <RangeLocationsContent
        locations={[{ id: "loc-1", name: "מטווח דרום", active: true }]}
        loading={false}
        error={false}
        canManage
        onCreate={onCreate}
        onUpdate={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByText("מטווח דרום")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("שם המיקום"), { target: { value: "מטווח מזרח" } });
    fireEvent.click(screen.getByRole("button", { name: "הוסף מיקום" }));

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith("מטווח מזרח"));
  });

  it("disables delete for used locations and explains why", () => {
    render(
      <RangeLocationsContent
        locations={[{ id: "loc-used", name: "מטווח בשימוש", active: true, can_delete: false, usage_count: 2 }]}
        loading={false}
        error={false}
        canManage
        onCreate={vi.fn().mockResolvedValue(undefined)}
        onUpdate={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const deleteButton = screen.getByRole("button", { name: "מחק מיקום" });
    expect(deleteButton).toBeDisabled();
    expect(deleteButton.parentElement).toHaveAttribute("title", "לא ניתן למחוק — המיקום כבר בשימוש במטווחים");
  });
});
