import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import LocationFormModal from "./LocationFormModal";
import { UnsavedChangesProvider } from "../contexts/UnsavedChangesContext";

vi.mock("../api/dutyConfig", () => ({
  createLocation: vi.fn(),
}));

function renderModal(onCreated = vi.fn(), onClose = vi.fn()) {
  return {
    onCreated, onClose,
    ...render(
      <MemoryRouter>
        <UnsavedChangesProvider>
          <LocationFormModal onCreated={onCreated} onClose={onClose} />
        </UnsavedChangesProvider>
      </MemoryRouter>,
    ),
  };
}

describe("LocationFormModal unsaved-changes guard", () => {
  it("closes immediately when the name field is untouched", () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByText("✕"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirms before discarding a typed name via the backdrop", () => {
    const { onClose } = renderModal();
    fireEvent.change(screen.getByTestId("location-create-name"), { target: { value: "מטווח חדש" } });
    fireEvent.click(screen.getByText("✕"));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("unsaved-discard"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("save and leave creates the location then closes", async () => {
    const dutyConfig = await import("../api/dutyConfig");
    const created = { id: "loc1", name: "מטווח חדש" };
    vi.mocked(dutyConfig.createLocation).mockResolvedValue(created);
    const { onCreated, onClose } = renderModal();
    fireEvent.change(screen.getByTestId("location-create-name"), { target: { value: "מטווח חדש" } });
    fireEvent.click(screen.getByText("✕"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onCreated).toHaveBeenCalledWith(created);
  });
});
