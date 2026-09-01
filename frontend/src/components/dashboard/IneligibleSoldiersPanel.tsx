import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { getIneligibleSoldiers } from "../../api/ineligibleSoldiers";
import { queryKeys } from "../../queryKeys";
import { IneligibleSoldiersTable } from "../ranges/IneligibleSoldiersTable";

interface Props {
  scope?: "command";
}

export function IneligibleSoldiersPanel({ scope = "command" }: Props) {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: queryKeys.ineligibleSoldiers("commander"),
    queryFn: () => getIneligibleSoldiers("commander"),
    retry: false,
  });

  return (
    <section id="panel-ineligible-soldiers" dir="rtl">
      <p className="mb-2 text-xs font-medium text-gray-500 dark:text-gray-400">
        {t(scope === "command" ? "command_dashboard.ineligible_soldiers_scope_command" : "range_qualification.dashboard.title")}
      </p>
      <IneligibleSoldiersTable
        audience="commander"
        data={query.data}
        loading={query.isLoading}
        error={query.isError}
      />
    </section>
  );
}

export default IneligibleSoldiersPanel;
