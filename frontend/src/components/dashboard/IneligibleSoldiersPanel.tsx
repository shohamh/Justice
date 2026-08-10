import { useQuery } from "@tanstack/react-query";
import { getIneligibleSoldiers } from "../../api/ineligibleSoldiers";
import { queryKeys } from "../../queryKeys";
import { IneligibleSoldiersTable } from "../ranges/IneligibleSoldiersTable";

export function IneligibleSoldiersPanel() {
  const query = useQuery({
    queryKey: queryKeys.ineligibleSoldiers("commander"),
    queryFn: () => getIneligibleSoldiers("commander"),
    retry: false,
  });

  return (
    <section id="panel-ineligible-soldiers" dir="rtl">
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
