import { useEffect, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { useModalBackClose } from "../hooks/useModalBackClose";

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const ZOOM_STEP_PER_PIXEL = 0.0015;

interface Props {
  fileUrl: string;
  fileName: string;
  contentType: string;
  onClose: () => void;
}

export default function DocumentPreviewModal({ fileUrl, fileName, contentType, onClose }: Props) {
  useModalBackClose(onClose);
  const [numPages, setNumPages] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const isPdf = contentType === "application/pdf";

  useEffect(() => {
    setZoom(1);
  }, [fileUrl]);

  function handleWheel(e: React.WheelEvent<HTMLImageElement>) {
    e.preventDefault();
    setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z - e.deltaY * ZOOM_STEP_PER_PIXEL)));
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[70] p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-full max-w-2xl max-h-[90dvh] overflow-y-auto"
        dir="rtl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold text-sm truncate">{fileName}</h3>
          <div className="flex items-center gap-3">
            <a
              href={fileUrl}
              download={fileName}
              className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              הורדה
            </a>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
          </div>
        </div>

        {isPdf ? (
          <Document
            file={fileUrl}
            onLoadSuccess={({ numPages: n }) => setNumPages(n)}
            loading={<p className="text-sm text-gray-500">טוען מסמך...</p>}
            error={<p className="text-sm text-red-500">שגיאה בטעינת המסמך</p>}
          >
            {Array.from({ length: numPages ?? 0 }, (_, i) => (
              <Page key={i} pageNumber={i + 1} width={600} />
            ))}
          </Document>
        ) : (
          <div className="overflow-auto max-h-[75dvh]">
            <img
              src={fileUrl}
              alt={fileName}
              onWheel={handleWheel}
              onDoubleClick={() => setZoom(1)}
              style={{ transform: `scale(${zoom})`, transformOrigin: "center top" }}
              className="max-w-full h-auto mx-auto cursor-zoom-in"
            />
          </div>
        )}
      </div>
    </div>
  );
}
