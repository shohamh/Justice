import { useTranslation } from "react-i18next";
import { ActiveDeputyGrantDTO } from "../api/auth";

interface Props {
  grants: ActiveDeputyGrantDTO[];
}

export default function ActiveDeputyBanner({ grants }: Props) {
  const { t } = useTranslation();
  if (grants.length === 0) return null;

  return (
    <div className="bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg p-3 text-sm text-indigo-800 dark:text-indigo-200 space-y-1" dir="rtl">
      {grants.map((g) => (
        <p key={g.principal_id}>
          {t("deputies.acting_as_banner", {
            principal: g.principal_name,
            role: g.role === "commander" ? t("deputies.role_commander", "מפקד") : t("deputies.role_duty_manager", "אחראי תורנויות"),
            endDate: g.end_date,
          })}
        </p>
      ))}
    </div>
  );
}
