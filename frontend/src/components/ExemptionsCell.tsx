import { useState } from "react";
import { ExemptionSummaryItem } from "../api/exemptions";
import { formatDdMmYyyy } from "../utils/formatDate";
import ExemptionInstanceModal from "./ExemptionInstanceModal";

interface Props {
  exemptions: ExemptionSummaryItem[];
  visible: boolean;
  placeholder: string;
  soldierId: string;
}

function chipLabel(item: ExemptionSummaryItem): string {
  return item.end_date
    ? `${item.exemption_type_name} (עד ${formatDdMmYyyy(item.end_date)})`
    : item.exemption_type_name;
}

export default function ExemptionsCell({ exemptions, visible, placeholder, soldierId }: Props) {
  const [openExemptionId, setOpenExemptionId] = useState<string | null>(null);

  if (!visible) return <>{placeholder}</>;
  if (exemptions.length === 0) return <>—</>;

  return (
    <>
      <span className="flex flex-wrap gap-1">
        {exemptions.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setOpenExemptionId(item.id)}
            className="text-xs text-blue-600 dark:text-blue-400 underline"
          >
            {chipLabel(item)}
          </button>
        ))}
      </span>
      {openExemptionId && (
        <ExemptionInstanceModal
          soldierId={soldierId}
          exemptionId={openExemptionId}
          onClose={() => setOpenExemptionId(null)}
        />
      )}
    </>
  );
}
