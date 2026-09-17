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
    // Compare against the SECOND modal's current (live) z-index rather than the
    // value captured earlier: z-index is now rank-based among currently active
    // modals (bounded), so second's own z-index shifts down once first closes
    // and back up as other modals close around it. The invariant that must
    // hold is relative order at this point in time -- the reopened modal
    // (opened most recently) must render above the still-open second modal.
    const secondNow = screen.getByRole("dialog", { name: "Second modal" }).parentElement!;
    expect(Number(reopenedFirst.style.zIndex)).toBeGreaterThan(Number(secondNow.style.zIndex));
  });

  test("keeps the maximum z-index bounded by concurrently open modals, not lifetime history", () => {
    // Open and close 15 modals in sequence (far more than would ever be open
    // at once) via a single modal slot, then open two more together -- the
    // max z-index among currently-open modals must stay low (below the first
    // real fixed z-index tier, 60), even though many more than that many
    // modals were opened over the session's lifetime.
    function ChurnFixture({ openIndex, alsoOpen }: { openIndex: number; alsoOpen: boolean }) {
      return (
        <ModalStackProvider>
          <EventDetailModal open={openIndex >= 0} title="Churned modal" onClose={() => {}}>
            Churned content
          </EventDetailModal>
          <EventDetailModal open={alsoOpen} title="Companion modal" onClose={() => {}}>
            Companion content
          </EventDetailModal>
        </ModalStackProvider>
      );
    }

    const { rerender } = render(<ChurnFixture openIndex={-1} alsoOpen={false} />);
    for (let i = 0; i < 15; i++) {
      rerender(<ChurnFixture openIndex={i} alsoOpen={false} />);
      rerender(<ChurnFixture openIndex={-1} alsoOpen={false} />);
    }
    rerender(<ChurnFixture openIndex={15} alsoOpen />);

    const churned = screen.getByRole("dialog", { name: "Churned modal" }).parentElement!;
    const companion = screen.getByRole("dialog", { name: "Companion modal" }).parentElement!;
    expect(Number(churned.style.zIndex)).toBeLessThan(60);
    expect(Number(companion.style.zIndex)).toBeLessThan(60);
  });
});
