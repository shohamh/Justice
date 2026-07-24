import "@testing-library/jest-dom";

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
