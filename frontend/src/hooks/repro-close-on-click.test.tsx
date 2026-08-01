import { StrictMode, useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach } from "vitest";
import { useModalBackClose } from "./useModalBackClose";

function Modal({ onClose }: { onClose: () => void }) {
  useModalBackClose(onClose);
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        data-testid="modal-panel"
      >
        <p>content</p>
        <div style={{ height: 2000 }} />
      </div>
    </div>
  );
}

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>open</button>
      {open && <Modal onClose={() => setOpen(false)} />}
    </>
  );
}

describe("repro: modal closing on click/scroll", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/approvals");
  });

  test("clicking inside the panel must NOT close it", () => {
    const onClose = vi.fn();
    render(
      <StrictMode>
        <Modal onClose={onClose} />
      </StrictMode>,
    );
    const panel = screen.getByTestId("modal-panel");
    fireEvent.click(panel);
    fireEvent.click(screen.getByText("content"));
    expect(onClose).not.toHaveBeenCalled();
  });

  test("scrolling the panel must NOT close it", () => {
    const onClose = vi.fn();
    render(
      <StrictMode>
        <Modal onClose={onClose} />
      </StrictMode>,
    );
    const panel = screen.getByTestId("modal-panel");
    fireEvent.wheel(panel, { deltaY: 100 });
    fireEvent.scroll(panel);
    expect(onClose).not.toHaveBeenCalled();
  });

  test("open -> click inside -> still open", () => {
    render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );
    fireEvent.click(screen.getByText("open"));
    expect(screen.getByTestId("modal-panel")).toBeInTheDocument();
    fireEvent.click(screen.getByText("content"));
    expect(screen.getByTestId("modal-panel")).toBeInTheDocument();
  });
});
