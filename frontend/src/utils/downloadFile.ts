export function sanitizeFilename(filename: string, fallback = "download"): string {
  const candidate = filename
    .replace(/\\/g, "/")
    .split("/")
    .pop()
    // eslint-disable-next-line no-control-regex
    ?.replace(/[<>:"/|?*\u0000-\u001f\u007f]/g, "_")
    .replace(/[. ]+$/g, "")
    .trim();

  const safe = candidate && candidate !== "." && candidate !== ".." ? candidate : fallback;
  return /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$/i.test(safe)
    ? `_${safe}`
    : safe;
}

export interface TemporaryBlobUrl {
  url: string;
  dispose: () => void;
}

export function createTemporaryBlobUrl(blob: Blob): TemporaryBlobUrl {
  const url = URL.createObjectURL(blob);
  let disposed = false;

  return {
    url,
    dispose() {
      if (disposed) return;
      disposed = true;
      URL.revokeObjectURL(url);
    },
  };
}

export function revokeBlobUrl(url: string): void {
  URL.revokeObjectURL(url);
}

export function downloadBlob(blob: Blob, filename: string): void {
  const temporaryUrl = createTemporaryBlobUrl(blob);
  const link = document.createElement("a");
  link.href = temporaryUrl.url;
  link.download = sanitizeFilename(filename);
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(temporaryUrl.dispose, 0);
}
