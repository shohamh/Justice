import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { UnsavedChangesProvider, useUnsavedChangesInternalsForTests } from "../contexts/UnsavedChangesContext";
import { useUnsavedChangesGuard } from "./useUnsavedChangesGuard";

function DirtyPage({ onSave, onDiscard }: { onSave: () => Promise<boolean>; onDiscard: () => void }) {
  const [dirty, setDirty] = useState(false);
  const { requestClose } = useUnsavedChangesGuard({ kind: "page", isDirty: dirty, onSave, onDiscard });
  return (
    <div>
      <button onClick={() => setDirty(true)} data-testid="make-dirty">dirty</button>
      <button onClick={requestClose} data-testid="request-close">close</button>
    </div>
  );
}

function PendingProbe() {
  const { pendingDialogGuardId } = useUnsavedChangesInternalsForTests();
  return <div data-testid="pending">{pendingDialogGuardId ?? "none"}</div>;
}

describe("useUnsavedChangesGuard", () => {
  it("discards immediately when not dirty", () => {
    const onDiscard = vi.fn();
    render(
      <UnsavedChangesProvider>
        <DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />
        <PendingProbe />
      </UnsavedChangesProvider>,
    );
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("pending")).toHaveTextContent("none");
  });

  it("opens the pending dialog state instead of discarding when dirty", () => {
    const onDiscard = vi.fn();
    render(
      <UnsavedChangesProvider>
        <DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />
        <PendingProbe />
      </UnsavedChangesProvider>,
    );
    fireEvent.click(screen.getByTestId("make-dirty"));
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByTestId("pending")).not.toHaveTextContent("none");
  });

  it("discards immediately (with a warning) when used outside a provider", () => {
    const onDiscard = vi.fn();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />);
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    errorSpy.mockRestore();
  });
});
