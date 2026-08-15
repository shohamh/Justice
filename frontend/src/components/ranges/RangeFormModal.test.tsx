import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RangeFormModal from "./RangeFormModal";
const event = { id:"r1", hierarchy_node_id:"n1", range_type:"laser" as const, date:"2026-09-01", range_location_id:"loc1", location:"old", required_count:1, reserve_count:1, status:"planned" as const, assignments:[{id:"a1",soldier_id:"s1",is_reserve:false,is_draft:false,attendance_status:"pending" as const,note:null}] };
describe("RangeFormModal",()=>{
  it("uses the standard modal form structure with grouped sections and a footer", () => {
    render(<RangeFormModal open event={null} hierarchyNodeId="n1" locations={[]} onClose={vi.fn()} onSubmit={vi.fn()} />);

    expect(screen.getByTestId("range-form-header")).toBeInTheDocument();
    expect(screen.getByTestId("range-form-section-schedule")).toBeInTheDocument();
    expect(screen.getByTestId("range-form-section-contact")).toBeInTheDocument();
    expect(screen.getByTestId("range-form-section-notes")).toBeInTheDocument();
    expect(screen.getByTestId("range-form-footer")).toHaveClass("border-t", "pt-4");
    expect(screen.getByRole("button", { name: "ביטול" })).toHaveClass("border");
    expect(screen.getByRole("button", { name: "שמור" })).toHaveClass("bg-blue-600", "text-white");
  });

  it("requires explicit confirmation when changing date with assignments", async()=>{ const submit=vi.fn().mockResolvedValue(undefined); render(<RangeFormModal open event={event} hierarchyNodeId="n1" locations={[]} onClose={vi.fn()} onSubmit={submit}/>); fireEvent.change(screen.getByTestId("edit-date"),{target:{value:"2026-09-02"}}); fireEvent.click(screen.getByRole("button",{name:"שמור"})); expect(await screen.findByRole("alert")).toBeInTheDocument(); expect(submit).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByRole("button",{name:"שמור"})); await waitFor(()=>expect(submit).toHaveBeenCalledWith(expect.objectContaining({date:"2026-09-02",force_schedule_change:true}))); });
  it("resets the force confirmation when a different event is opened", async()=>{
    const secondEvent = { ...event, id: "r2", date: "2026-10-01" };
    const submit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    const { rerender } = render(<RangeFormModal open event={event} hierarchyNodeId="n1" locations={[]} onClose={onClose} onSubmit={submit}/>);

    fireEvent.change(screen.getByTestId("edit-date"), { target: { value: "2026-09-02" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "שמור" }));
    await waitFor(() => expect(submit).toHaveBeenCalledWith(expect.objectContaining({ force_schedule_change: true })));

    rerender(<RangeFormModal open event={secondEvent} hierarchyNodeId="n1" locations={[]} onClose={onClose} onSubmit={submit}/>);
    fireEvent.change(screen.getByTestId("edit-date"), { target: { value: "2026-10-02" } });
    fireEvent.click(screen.getByRole("button", { name: "שמור" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(submit).toHaveBeenCalledTimes(1);
  });
  it("rejects an end time before the start time",async()=>{ const submit=vi.fn(); render(<RangeFormModal open event={null} hierarchyNodeId="n1" locations={[{id:"loc1",name:"מטווח דרום",active:true}]} onClose={vi.fn()} onSubmit={submit}/>); fireEvent.focus(screen.getByTestId("new-range-location")); const locationOption = await screen.findByText("מטווח דרום"); fireEvent.pointerDown(locationOption); fireEvent.pointerUp(locationOption); fireEvent.change(screen.getByTestId("new-date"),{target:{value:"2026-09-02"}}); fireEvent.change(screen.getByTestId("new-start-time"),{target:{value:"12:00"}}); fireEvent.change(screen.getByTestId("new-end-time"),{target:{value:"11:00"}}); fireEvent.click(screen.getByRole("button",{name:"שמור"})); expect(screen.getByRole("alert")).toBeInTheDocument(); expect(submit).not.toHaveBeenCalled(); });
  it("shows a specific error when no location is selected",()=>{ const submit=vi.fn(); render(<RangeFormModal open event={null} hierarchyNodeId="n1" locations={[]} onClose={vi.fn()} onSubmit={submit}/>); fireEvent.change(screen.getByTestId("new-date"),{target:{value:"2026-09-02"}}); fireEvent.click(screen.getByRole("button",{name:"שמור"})); expect(screen.getByRole("alert")).toHaveTextContent("יש לבחור מיקום"); expect(submit).not.toHaveBeenCalled(); });
  it("does not expose inactive configured locations in the selector", () => {
    render(<RangeFormModal open event={null} hierarchyNodeId="n1" locations={[{ id: "loc-inactive", name: "מטווח סגור", active: false }]} onClose={vi.fn()} onSubmit={vi.fn()} />);

    fireEvent.focus(screen.getByTestId("new-range-location"));
    expect(screen.queryByText("מטווח סגור")).not.toBeInTheDocument();
  });
  it("does not offer inline range-location creation", () => {
    render(<RangeFormModal open event={null} hierarchyNodeId="n1" locations={[]} onClose={vi.fn()} onSubmit={vi.fn()} />);

    expect(screen.queryByText("+ הוסף מיקום")).not.toBeInTheDocument();
  });
  it("shows readable range type choices", () => {
    render(<RangeFormModal open event={null} hierarchyNodeId="n1" locations={[]} onClose={vi.fn()} onSubmit={vi.fn()} />);

    const rangeType = screen.getByTestId("new-range-type");
    expect(rangeType).toHaveValue("מטווח לייזר");
    fireEvent.focus(rangeType);

    const listbox = screen.getByRole("listbox");
    expect(listbox).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(screen.getByText("מטווח לייזר")).toBeInTheDocument();
    expect(screen.getByText("מטווח חי")).toBeInTheDocument();
    expect(screen.getByText("אל\"ל")).toBeInTheDocument();
  });
});
