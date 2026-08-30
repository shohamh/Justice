# Vendored pdf.js worker

`pdf.worker.min.mjs` is copied verbatim from `node_modules/pdfjs-dist/build/pdf.worker.min.mjs`
(the version pinned transitively via `react-pdf` in `package-lock.json`). It's committed here
instead of imported from `node_modules` at build time so the app never fetches it from a CDN at
runtime and works fully offline.

pdf.js requires the worker version to match the main-thread `pdfjs-dist` version exactly, so
whenever `react-pdf` (or `pdfjs-dist`) is upgraded, refresh this file from the same repo:

```bash
cp node_modules/pdfjs-dist/build/pdf.worker.min.mjs public/pdfjs/pdf.worker.min.mjs
```
