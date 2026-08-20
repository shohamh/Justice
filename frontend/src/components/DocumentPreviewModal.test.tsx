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

  it("zooms an image in on scroll-up and back out on scroll-down", () => {
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-image"
        fileName="note.png"
        contentType="image/png"
        onClose={() => {}}
      />
    );
    const img = screen.getByRole("img");
    expect(img).toHaveStyle({ transform: "scale(1)" });

    fireEvent.wheel(img, { deltaY: -200 });
    expect(img.style.transform).not.toBe("scale(1)");
    const zoomedIn = img.style.transform;

    fireEvent.wheel(img, { deltaY: 200 });
    expect(img.style.transform).not.toBe(zoomedIn);
  });

  it("resets zoom to 1 on double-click", () => {
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-image"
        fileName="note.png"
        contentType="image/png"
        onClose={() => {}}
      />
    );
    const img = screen.getByRole("img");
    fireEvent.wheel(img, { deltaY: -500 });
    expect(img.style.transform).not.toBe("scale(1)");

    fireEvent.doubleClick(img);
    expect(img).toHaveStyle({ transform: "scale(1)" });
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
