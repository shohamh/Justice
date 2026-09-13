import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter, Routes, Route, Link } from "react-router-dom";
import { UnsavedChangesProvider } from "./UnsavedChangesContext";
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard";

function DirtyForm({ onSave, onDiscard }: { onSave: () => Promise<boolean>; onDiscard: () => void }) {
  const [dirty, setDirty] = useState(true);
  const { requestClose } = useUnsavedChangesGuard({ kind: "modal", isDirty: dirty, onSave, onDiscard: () => { setDirty(false); onDiscard(); } });
  return <button onClick={requestClose} data-testid="close">close</button>;
}

describe("UnsavedChangesContext dialog", () => {
  it("shows nothing when no guard requested a close", () => {
    render(<MemoryRouter><UnsavedChangesProvider><div /></UnsavedChangesProvider></MemoryRouter>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("discard and leave calls onDiscard and closes the dialog", () => {
    const onDiscard = vi.fn();
    render(<MemoryRouter><UnsavedChangesProvider><DirtyForm onSave={vi.fn()} onDiscard={onDiscard} /></UnsavedChangesProvider></MemoryRouter>);
    fireEvent.click(screen.getByTestId("close"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("unsaved-discard"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancel closes the dialog without calling onDiscard or onSave", () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn();
    render(<MemoryRouter><UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider></MemoryRouter>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-cancel"));
    expect(onDiscard).not.toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("save and leave calls onSave, then onDiscard once it resolves true", async () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn().mockResolvedValue(true);
    render(<MemoryRouter><UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider></MemoryRouter>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(onDiscard).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("save and leave shows a retry error and stays open when onSave resolves false", async () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn().mockResolvedValue(false);
    render(<MemoryRouter><UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider></MemoryRouter>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(screen.getByTestId("unsaved-error")).toBeInTheDocument());
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("save and leave shows a retry error and re-enables cancel when onSave rejects", async () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn().mockRejectedValue(new Error("network error"));
    render(<MemoryRouter><UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider></MemoryRouter>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(screen.getByTestId("unsaved-error")).toBeInTheDocument());
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTestId("unsaved-cancel")).not.toBeDisabled();
  });
});

function PageWithLink({ isDirty }: { isDirty: boolean }) {
  useUnsavedChangesGuard({ kind: "page", isDirty, onSave: vi.fn().mockResolvedValue(true), onDiscard: vi.fn() });
  return <Link to="/other">go</Link>;
}

describe("UnsavedChangesContext in-app link interception", () => {
  it("lets navigation proceed immediately when nothing is dirty", () => {
    render(
      <MemoryRouter initialEntries={["/here"]}>
        <UnsavedChangesProvider>
          <Routes>
            <Route path="/here" element={<PageWithLink isDirty={false} />} />
            <Route path="/other" element={<div data-testid="other-page">other</div>} />
          </Routes>
        </UnsavedChangesProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("go"));
    expect(screen.getByTestId("other-page")).toBeInTheDocument();
  });

  it("intercepts the click and shows the dialog when dirty, navigating only after confirming discard", () => {
    render(
      <MemoryRouter initialEntries={["/here"]}>
        <UnsavedChangesProvider>
          <Routes>
            <Route path="/here" element={<PageWithLink isDirty={true} />} />
            <Route path="/other" element={<div data-testid="other-page">other</div>} />
          </Routes>
        </UnsavedChangesProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("go"));
    expect(screen.queryByTestId("other-page")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("unsaved-discard"));
    expect(screen.getByTestId("other-page")).toBeInTheDocument();
  });
});

describe("UnsavedChangesContext beforeunload", () => {
  it("prevents unload while a guard is dirty", () => {
    render(<MemoryRouter><UnsavedChangesProvider><DirtyForm onSave={vi.fn()} onDiscard={vi.fn()} /></UnsavedChangesProvider></MemoryRouter>);
    const event = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    const preventDefault = vi.spyOn(event, "preventDefault");
    window.dispatchEvent(event);
    expect(preventDefault).toHaveBeenCalled();
  });

  it("does not prevent unload once nothing is dirty", () => {
    function CleanForm() {
      useUnsavedChangesGuard({ kind: "modal", isDirty: false, onSave: vi.fn(), onDiscard: vi.fn() });
      return null;
    }
    render(<MemoryRouter><UnsavedChangesProvider><CleanForm /></UnsavedChangesProvider></MemoryRouter>);
    const event = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    const preventDefault = vi.spyOn(event, "preventDefault");
    window.dispatchEvent(event);
    expect(preventDefault).not.toHaveBeenCalled();
  });
});

describe("UnsavedChangesContext back/forward interception", () => {
  it("cancels a real back-press while a page guard is dirty and shows the dialog", async () => {
    function DirtyPage() {
      useUnsavedChangesGuard({ kind: "page", isDirty: true, onSave: vi.fn(), onDiscard: vi.fn() });
      return <div data-testid="dirty-page">here</div>;
    }
    render(
      <MemoryRouter initialEntries={["/start", "/here"]} initialIndex={1}>
        <UnsavedChangesProvider>
          <DirtyPage />
        </UnsavedChangesProvider>
      </MemoryRouter>,
    );
    // Let the "push a sentinel while dirty" effect run.
    await waitFor(() => expect(window.history.length).toBeGreaterThan(0));
    act(() => { window.history.back(); });
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(screen.getByTestId("dirty-page")).toBeInTheDocument();
  });

  it("a modal-kind guard does not trigger the page back interception", () => {
    function DirtyModalGuard() {
      useUnsavedChangesGuard({ kind: "modal", isDirty: true, onSave: vi.fn(), onDiscard: vi.fn() });
      return null;
    }
    render(
      <MemoryRouter initialEntries={["/start", "/here"]} initialIndex={1}>
        <UnsavedChangesProvider><DirtyModalGuard /></UnsavedChangesProvider>
      </MemoryRouter>,
    );
    act(() => { window.history.back(); });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not reopen the dialog when a popstate lands back on our own sentinel (e.g. a modal closed by non-back means)", async () => {
    function DirtyPage() {
      useUnsavedChangesGuard({ kind: "page", isDirty: true, onSave: vi.fn(), onDiscard: vi.fn() });
      return <div data-testid="dirty-page">here</div>;
    }
    render(
      <MemoryRouter initialEntries={["/start", "/here"]} initialIndex={1}>
        <UnsavedChangesProvider>
          <DirtyPage />
        </UnsavedChangesProvider>
      </MemoryRouter>,
    );
    // Let the sentinel-push effect run, same as the genuine-back-press test.
    await waitFor(() => expect(window.history.length).toBeGreaterThan(0));
    // Simulate a modal built on useModalBackClose: it pushes its own entry on
    // top of our sentinel while open...
    act(() => { window.history.pushState({ __modal: true }, ""); });
    // ...then closes by a non-back means (X button, backdrop, Escape, submit),
    // whose cleanup consumes its own entry via a plain history.back() -- this
    // fires a real popstate that lands back on OUR sentinel, not past it.
    act(() => { window.history.back(); });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
