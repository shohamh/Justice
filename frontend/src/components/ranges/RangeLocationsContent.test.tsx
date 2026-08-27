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
      />,
    );

    expect(screen.getByText("מטווח דרום")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("שם המיקום"), { target: { value: "מטווח מזרח" } });
    fireEvent.click(screen.getByRole("button", { name: "הוסף מיקום" }));

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith("מטווח מזרח"));
  });
});
