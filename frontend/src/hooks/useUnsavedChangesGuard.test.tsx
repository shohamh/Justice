import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { UnsavedChangesProvider } from "../contexts/UnsavedChangesContext";
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

describe("useUnsavedChangesGuard", () => {
  it("discards immediately when not dirty", () => {
    const onDiscard = vi.fn();
    render(
      <MemoryRouter>
        <UnsavedChangesProvider>
          <DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />
        </UnsavedChangesProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the confirmation dialog instead of discarding when dirty", () => {
    const onDiscard = vi.fn();
    render(
      <MemoryRouter>
        <UnsavedChangesProvider>
          <DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />
        </UnsavedChangesProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("make-dirty"));
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("discards immediately (no provider) when used outside a provider", () => {
    const onDiscard = vi.fn();
    render(<DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />);
    fireEvent.click(screen.getByTestId("make-dirty"));
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
  });
});
