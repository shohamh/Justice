import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AlgorithmInlinePanel from "./AlgorithmInlinePanel";
import * as algorithmApi from "../api/algorithm";

vi.mock("../api/algorithm", () => ({
  submitJob: vi.fn(),
  getAlgorithmDefaults: vi.fn().mockResolvedValue({ T: 8, Wt: 14, R: 15, Wr: 28 }),
}));

vi.mock("./SubHierarchySelector", () => ({
  default: () => <div data-testid="sub-hierarchy-selector" />,
}));

vi.mock("./AlgorithmModeHelpModal", () => ({
  default: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="mode-help-modal">
      <button onClick={onClose}>סגור</button>
    </div>
  ),
}));

const DUTY_TYPES = [{ id: "dt1", name: "שמירה", is_reserve_type: false }];

test("shows selected shift count badge", () => {
  render(
    <AlgorithmInlinePanel
      selectedShiftIds={["s1", "s2", "s3"]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={vi.fn()}
    />
  );
  expect(screen.getByText(/3 משמרות נבחרות/)).toBeInTheDocument();
});

test("run button disabled when 0 shifts selected", () => {
  render(
    <AlgorithmInlinePanel
      selectedShiftIds={[]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={vi.fn()}
    />
  );
  expect(screen.getByRole("button", { name: /הרץ שיבוץ/ })).toBeDisabled();
});

test("run button enabled when shifts selected", () => {
  render(
    <AlgorithmInlinePanel
      selectedShiftIds={["s1"]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={vi.fn()}
    />
  );
  expect(screen.getByRole("button", { name: /הרץ שיבוץ/ })).toBeEnabled();
});

test("calls submitJob and onJobSubmitted on run", async () => {
  const mockSubmit = vi.mocked(algorithmApi.submitJob).mockResolvedValue({
    id: "job-123",
  } as Awaited<ReturnType<typeof algorithmApi.submitJob>>);
  const onJobSubmitted = vi.fn();
  const onClose = vi.fn();

  render(
    <AlgorithmInlinePanel
      selectedShiftIds={["s1", "s2"]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={onJobSubmitted}
      onClose={onClose}
    />
  );

  fireEvent.click(screen.getByRole("button", { name: /הרץ שיבוץ/ }));

  await waitFor(() => {
    expect(mockSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ shift_ids: ["s1", "s2"], mode: "shadow" })
    );
    expect(onJobSubmitted).toHaveBeenCalledWith("job-123");
    expect(onClose).toHaveBeenCalled();
  });
});

test("shows error message on submit failure", async () => {
  vi.mocked(algorithmApi.submitJob).mockRejectedValue({
    response: { data: { detail: "server_error" } },
  });

  render(
    <AlgorithmInlinePanel
      selectedShiftIds={["s1"]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={vi.fn()}
    />
  );

  fireEvent.click(screen.getByRole("button", { name: /הרץ שיבוץ/ }));

  await waitFor(() => {
    expect(screen.getByText("server_error")).toBeInTheDocument();
  });
});

test("close button calls onClose", () => {
  const onClose = vi.fn();
  render(
    <AlgorithmInlinePanel
      selectedShiftIds={[]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={onClose}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "סגור" }));
  expect(onClose).toHaveBeenCalled();
});
