import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ImportUploadPage from "./ImportUploadPage";
import * as importSessionsApi from "../api/importSessions";
import type { ParsedState } from "../api/importSessions";

vi.mock("../api/importSessions");

const mockNavigate = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const mockPreview: ParsedState = {
  soldiers: [],
  duty_shifts: [],
  shift_templates: [],
  parser_id: "default",
  parser_warnings: [],
};

function makeFile(): File {
  return new File(["dummy"], "import.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

describe("ImportUploadPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uploads the selected file and navigates to the session review page on success", async () => {
    vi.mocked(importSessionsApi.uploadSession).mockResolvedValue({
      session_id: "session-123",
      preview: mockPreview,
    });

    render(<ImportUploadPage />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile()] } });

    await waitFor(() => {
      expect(importSessionsApi.uploadSession).toHaveBeenCalledWith(
        expect.any(File),
      );
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/import/sessions/session-123");
    });
  });

  it("shows an error banner and resets the loading state when uploadSession rejects", async () => {
    vi.mocked(importSessionsApi.uploadSession).mockRejectedValue(
      new Error("boom"),
    );

    render(<ImportUploadPage />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile()] } });

    expect(
      await screen.findByText("שגיאה בפענוח הקובץ — ודא שהוא xlsx תקין"),
    ).toBeInTheDocument();

    expect(mockNavigate).not.toHaveBeenCalled();

    const button = screen.getByRole("button", { name: "בחר קובץ" });
    expect(button).not.toBeDisabled();
  });

  it("renders a template download link with the correct href", () => {
    render(<ImportUploadPage />);

    const link = screen.getByText("הורד תבנית לדוגמה ›");
    expect(link).toHaveAttribute("href", "/api/import/template");
  });
});
