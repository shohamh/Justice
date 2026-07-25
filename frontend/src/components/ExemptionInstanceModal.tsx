import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ExemptionDetail, getExemptionDetail } from "../api/exemptions";
import { formatDdMmYyyy } from "../utils/formatDate";
import { DaysBadge } from "./DaysBadge";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  soldierId: string;
  exemptionId: string;
  onClose: () => void;
}

export default function ExemptionInstanceModal({ soldierId, exemptionId, onClose }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const [detail, setDetail] = useState<ExemptionDetail | null>(null);
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getExemptionDetail(soldierId, exemptionId)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 403) setForbidden(true);
      });
    return () => { cancelled = true; };
  }, [soldierId, exemptionId]);

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4"
      onClick={onClose}
      data-testid="exemption-instance-modal"
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-base">{t("exemptions.title")}</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        {forbidden && (
          <p className="text-sm text-red-500">{t("exemptions.no_permission_details")}</p>
        )}

        {!forbidden && detail && (
          <div className="space-y-2 text-sm">
            <p className="font-medium">{detail.exemption_type_name}</p>
            <span className="inline-block text-xs bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-0.5 rounded">
              {detail.is_global ? t("exemptions.category_global") : t("exemptions.category_partial")}
            </span>
            <p className="text-gray-700 dark:text-gray-300 flex items-center gap-2">
              <span>{formatDdMmYyyy(detail.start_date)}</span>
              {" → "}
              <span>{detail.end_date ? formatDdMmYyyy(detail.end_date) : t("exemptions.forever")}</span>
              <DaysBadge start={detail.start_date} end={detail.end_date} />
            </p>
            {detail.reason && (
              <p>
                <span className="font-medium">{t("exemptions.reason")}:</span> {detail.reason}
              </p>
            )}
            {detail.granted_by_name && (
              <p>
                <span className="font-medium">{t("exemptions.granted_by")}:</span> {detail.granted_by_name}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
