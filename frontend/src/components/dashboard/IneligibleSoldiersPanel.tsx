import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { getIneligibleSoldiers } from "../../api/ineligibleSoldiers";
import { queryKeys } from "../../queryKeys";
import { IneligibleSoldiersTable } from "../ranges/IneligibleSoldiersTable";

interface Props {
  scope?: "command";
  isOpen: boolean;
  authorizationScope: string | null;
}

export function IneligibleSoldiersPanel({ scope = "command", isOpen, authorizationScope }: Props) {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: [...queryKeys.ineligibleSoldiers("commander"), authorizationScope],
    queryFn: () => getIneligibleSoldiers("commander"),
    enabled: isOpen && authorizationScope !== null,
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
      {query.isError && (
        <button type="button" className="mt-2 text-sm underline" onClick={() => void query.refetch()}>
          {t("common.retry", { defaultValue: "Try again" })}
        </button>
      )}
    </section>
  );
}

export default IneligibleSoldiersPanel;
