import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import DocumentPreviewModal from "./DocumentPreviewModal";

vi.mock("react-pdf", () => ({
  Document: ({ children }: { children: React.ReactNode }) => <div data-testid="pdf-document">{children}</div>,
  Page: () => <div data-testid="pdf-page" />,
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" }, version: "0.0.0" },
}));

describe("DocumentPreviewModal", () => {
  it("renders an image preview for image content types", () => {
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-image"
        fileName="note.png"
        contentType="image/png"
        onClose={() => {}}
      />
    );
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "blob:mock-image");
  });

  it("renders a PDF viewer for application/pdf content type", () => {
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-pdf"
        fileName="note.pdf"
        contentType="application/pdf"
        onClose={() => {}}
      />
    );
    expect(screen.getByTestId("pdf-document")).toBeInTheDocument();
  });

  it("has a working download link pointing at the file URL", () => {
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-pdf"
        fileName="note.pdf"
        contentType="application/pdf"
        onClose={() => {}}
      />
    );
    const link = screen.getByRole("link", { name: /הורדה/ });
    expect(link).toHaveAttribute("href", "blob:mock-pdf");
    expect(link).toHaveAttribute("download", "note.pdf");
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-pdf"
        fileName="note.pdf"
        contentType="application/pdf"
        onClose={onClose}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "✕" }));
    expect(onClose).toHaveBeenCalled();
  });
});
