import { describe, it, expect } from "vitest";
import { validateFileSignature } from "./fileValidation";

function makeFile(bytes: number[], type: string, name = "f"): File {
  return new File([new Uint8Array(bytes)], name, { type });
}

const PDF_SIGNATURES = { "application/pdf": [new Uint8Array([0x25, 0x50, 0x44, 0x46])] }; // %PDF

describe("validateFileSignature", () => {
  it("accepts a file whose bytes match its declared type", async () => {
    const file = makeFile([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31], "application/pdf");
    await expect(validateFileSignature(file, PDF_SIGNATURES)).resolves.toBe(true);
  });

  it("rejects a file whose bytes don't match its declared (spoofed) type", async () => {
    const file = makeFile([0x3c, 0x73, 0x63, 0x72, 0x69, 0x70, 0x74], "application/pdf", "fake.pdf");
    await expect(validateFileSignature(file, PDF_SIGNATURES)).resolves.toBe(false);
  });

  it("rejects a type with no registered signature", async () => {
    const file = makeFile([0x25, 0x50, 0x44, 0x46], "application/octet-stream");
    await expect(validateFileSignature(file, PDF_SIGNATURES)).resolves.toBe(false);
  });
});
