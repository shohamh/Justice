if (typeof document !== "undefined") {
  await import("@testing-library/jest-dom");
}

// jsdom's Blob/File implementation doesn't implement the async arrayBuffer()
// method (unlike real browsers), which fileValidation.ts relies on to read
// magic bytes. Polyfill it via FileReader so tests exercise the same code
// path production runs in a real browser.
if (typeof Blob !== "undefined" && !Blob.prototype.arrayBuffer) {
  Blob.prototype.arrayBuffer = function arrayBuffer(): Promise<ArrayBuffer> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(this);
    });
  };
}

// react-pdf pulls in pdfjs-dist, which touches browser canvas/DOMMatrix APIs
// at import time that jsdom doesn't implement. Any test that transitively
// imports a module using react-pdf (e.g. ApprovalsPage -> DocumentPreviewModal)
// would otherwise crash with "DOMMatrix is not defined". Tests that actually
// exercise DocumentPreviewModal's rendering provide their own more detailed
// mock (see DocumentPreviewModal.test.tsx), which takes precedence.
vi.mock("react-pdf", () => ({
  Document: () => null,
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" }, version: "0.0.0" },
}));
