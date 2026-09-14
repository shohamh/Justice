import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "../i18n";
import SoldierEditModal from "./SoldierEditModal";
import { UnsavedChangesProvider } from "../contexts/UnsavedChangesContext";
import * as hierarchyApi from "../api/hierarchy";

vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn().mockResolvedValue([]),
}));

const soldier = { id: "s1", full_name: "אורי כהן", phone: "0500000000", hierarchy_node_id: "n1" } as never;

function renderModal(onSave = vi.fn().mockResolvedValue(undefined), onClose = vi.fn()) {
  return {
    onSave, onClose,
    ...render(
      <MemoryRouter>
        <UnsavedChangesProvider>
          <SoldierEditModal soldier={soldier} onSave={onSave} onClose={onClose} />
        </UnsavedChangesProvider>
      </MemoryRouter>,
    ),
  };
}

describe("SoldierEditModal unsaved-changes guard", () => {
  it("closes immediately when nothing changed", async () => {
    const { onClose } = renderModal();
    await waitFor(() => expect(hierarchyApi.fetchTree).toHaveBeenCalled());
    fireEvent.click(screen.getByText("בטל", { selector: "button" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirms before discarding an edited name via cancel", async () => {
    const { onClose } = renderModal();
    await waitFor(() => expect(hierarchyApi.fetchTree).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("edit-soldier-name"), { target: { value: "אורי לוי" } });
    fireEvent.click(screen.getByText("בטל", { selector: "button" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("unsaved-discard"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("save and leave calls the parent onSave with the diff, then closes", async () => {
    const { onSave, onClose } = renderModal();
    await waitFor(() => expect(hierarchyApi.fetchTree).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("edit-soldier-name"), { target: { value: "אורי לוי" } });
    fireEvent.click(screen.getByText("בטל", { selector: "button" }));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith({ full_name: "אורי לוי" });
  });
});
