import { useTranslation } from "react-i18next";
import BugReportCommentsPanel from "./BugReportCommentsPanel";

interface Props {
  reportId: string;
  onClose: () => void;
}

export default function BugReportDetailModal({ reportId, onClose }: Props) {
  const { t } = useTranslation();

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b dark:border-gray-600 flex justify-between items-center">
          <h3 className="font-semibold">{t("bug_reports.comments_title")}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label={t("bug_reports.close")}>
            ✕
          </button>
        </div>
        <BugReportCommentsPanel reportId={reportId} />
      </div>
    </div>
  );
}
