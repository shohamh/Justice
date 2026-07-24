export async function readMagicBytes(file: File, length: number): Promise<Uint8Array> {
  const slice = file.slice(0, length);
  const buf = await slice.arrayBuffer();
  return new Uint8Array(buf);
}

export async function validateFileSignature(
  file: File,
  allowedSignatures: Record<string, Uint8Array[]>,
): Promise<boolean> {
  const signatures = allowedSignatures[file.type];
  if (!signatures || signatures.length === 0) return false;
  const maxLen = Math.max(...signatures.map(s => s.length));
  const head = await readMagicBytes(file, maxLen);
  return signatures.some(sig => sig.every((byte, i) => head[i] === byte));
}

export const PDF_IMAGE_SIGNATURES: Record<string, Uint8Array[]> = {
  "application/pdf": [new Uint8Array([0x25, 0x50, 0x44, 0x46])], // %PDF
  "image/jpeg": [new Uint8Array([0xff, 0xd8, 0xff])],
  "image/png": [new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])],
  "image/gif": [
    new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x37, 0x61]), // GIF87a
    new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61]), // GIF89a
  ],
  "image/webp": [new Uint8Array([0x52, 0x49, 0x46, 0x46])], // RIFF
};

export const XLSX_SIGNATURES: Record<string, Uint8Array[]> = {
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [
    new Uint8Array([0x50, 0x4b, 0x03, 0x04]), // PK\x03\x04 (ZIP)
  ],
};
