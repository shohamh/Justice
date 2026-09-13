import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useState } from "react";
import { UnsavedChangesProvider } from "./UnsavedChangesContext";
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard";

function DirtyForm({ onSave, onDiscard }: { onSave: () => Promise<boolean>; onDiscard: () => void }) {
  const [dirty, setDirty] = useState(true);
  const { requestClose } = useUnsavedChangesGuard({ kind: "modal", isDirty: dirty, onSave, onDiscard: () => { setDirty(false); onDiscard(); } });
  return <button onClick={requestClose} data-testid="close">close</button>;
}

describe("UnsavedChangesContext dialog", () => {
  it("shows nothing when no guard requested a close", () => {
    render(<UnsavedChangesProvider><div /></UnsavedChangesProvider>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("discard and leave calls onDiscard and closes the dialog", () => {
    const onDiscard = vi.fn();
    render(<UnsavedChangesProvider><DirtyForm onSave={vi.fn()} onDiscard={onDiscard} /></UnsavedChangesProvider>);
    fireEvent.click(screen.getByTestId("close"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("unsaved-discard"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancel closes the dialog without calling onDiscard or onSave", () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn();
    render(<UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-cancel"));
    expect(onDiscard).not.toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("save and leave calls onSave, then onDiscard once it resolves true", async () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn().mockResolvedValue(true);
    render(<UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(onDiscard).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("save and leave shows a retry error and stays open when onSave resolves false", async () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn().mockResolvedValue(false);
    render(<UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(screen.getByTestId("unsaved-error")).toBeInTheDocument());
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("save and leave shows a retry error and re-enables cancel when onSave rejects", async () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn().mockRejectedValue(new Error("network error"));
    render(<UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(screen.getByTestId("unsaved-error")).toBeInTheDocument());
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTestId("unsaved-cancel")).not.toBeDisabled();
  });
});
