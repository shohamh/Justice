import { render, screen } from "@testing-library/react";
import { EventDetailModal } from "../components/planning/EventDetailModal";
import { ModalStackProvider } from "./ModalStackContext";

function StackFixture({ firstOpen, secondOpen }: { firstOpen: boolean; secondOpen: boolean }) {
  return (
    <ModalStackProvider>
      <EventDetailModal open={firstOpen} title="First modal" onClose={() => {}}>
        First content
      </EventDetailModal>
      <EventDetailModal open={secondOpen} title="Second modal" onClose={() => {}}>
        Second content
      </EventDetailModal>
    </ModalStackProvider>
  );
}

describe("modal opening order", () => {
  test("places a reopened modal above every modal opened before it", () => {
    const { rerender } = render(<StackFixture firstOpen secondOpen={false} />);
    const first = screen.getByRole("dialog", { name: "First modal" }).parentElement!;
    const firstLayer = Number(first.style.zIndex);

    rerender(<StackFixture firstOpen secondOpen />);
    const second = screen.getByRole("dialog", { name: "Second modal" }).parentElement!;
    const secondLayer = Number(second.style.zIndex);
    expect(Number(first.style.zIndex)).toBe(firstLayer);
    expect(firstLayer).toBeLessThan(secondLayer);

    rerender(<StackFixture firstOpen={false} secondOpen />);
    rerender(<StackFixture firstOpen secondOpen />);
    const reopenedFirst = screen.getByRole("dialog", { name: "First modal" }).parentElement!;
    expect(Number(reopenedFirst.style.zIndex)).toBeGreaterThan(secondLayer);
  });
});
