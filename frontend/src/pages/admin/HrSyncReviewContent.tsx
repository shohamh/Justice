import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  listHeldForReview, dismissHeldForReview,
  listDivergences, clearFieldOverride,
  listVanished, listRankConflicts, listSyncRuns, runSyncNow,
} from "../../api/hrReview";
import { DataTable, ColDef } from "../../components/DataTable";
import type {
  HeldForReviewItemDTO, DivergenceItemDTO, VanishedItemDTO,
  RankConflictItemDTO, PersonSyncRunDTO,
} from "../../api/hrReview";

export default function HrSyncReviewContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const heldQuery = useQuery({ queryKey: ["hr-sync-held"], queryFn: listHeldForReview });
  const divergencesQuery = useQuery({ queryKey: ["hr-sync-divergences"], queryFn: listDivergences });
  const vanishedQuery = useQuery({ queryKey: ["hr-sync-vanished"], queryFn: listVanished });
  const conflictsQuery = useQuery({ queryKey: ["hr-sync-conflicts"], queryFn: listRankConflicts });
  const runsQuery = useQuery({ queryKey: ["hr-sync-runs"], queryFn: listSyncRuns });

  const dismissMutation = useMutation({
    mutationFn: (profileId: string) => dismissHeldForReview(profileId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["hr-sync-held"] }),
  });
  const clearOverrideMutation = useMutation({
    mutationFn: ({ profileId, fieldName }: { profileId: string; fieldName: string }) =>
      clearFieldOverride(profileId, fieldName),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["hr-sync-divergences"] }),
  });
  const runNowMutation = useMutation({
    mutationFn: runSyncNow,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-held"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-divergences"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-vanished"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-conflicts"] });
    },
  });

  const heldColumns: ColDef<HeldForReviewItemDTO>[] = [
    { id: "personal_number", header: t("admin.hr_sync.personal_number"), cell: (r) => r.personal_number },
    { id: "review_reason", header: t("admin.hr_sync.reason"), cell: (r) => r.review_reason ?? "—" },
    {
      id: "actions", header: "", cell: (r) => (
        <button
          type="button"
          data-testid={`hr-sync-dismiss-${r.id}`}
          className="px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600"
          onClick={() => dismissMutation.mutate(r.id)}
        >
          {t("admin.hr_sync.dismiss")}
        </button>
      ),
    },
  ];

  const divergenceColumns: ColDef<DivergenceItemDTO>[] = [
    { id: "field_name", header: t("admin.hr_sync.field"), cell: (r) => r.field_name },
    { id: "hr_value", header: t("admin.hr_sync.hr_value"), cell: (r) => String(r.hr_value ?? "—") },
    { id: "local_value", header: t("admin.hr_sync.local_value"), cell: (r) => String(r.local_value ?? "—") },
    {
      id: "actions", header: "", cell: (r) => (
        <button
          type="button"
          data-testid={`hr-sync-clear-override-${r.id}`}
          className="px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600"
          onClick={() => clearOverrideMutation.mutate({ profileId: r.soldier_hr_profile_id, fieldName: r.field_name })}
        >
          {t("admin.hr_sync.clear_override")}
        </button>
      ),
    },
  ];

  const vanishedColumns: ColDef<VanishedItemDTO>[] = [
    { id: "personal_number", header: t("admin.hr_sync.personal_number"), cell: (r) => r.personal_number },
  ];

  const conflictColumns: ColDef<RankConflictItemDTO>[] = [
    { id: "old_rank", header: t("admin.hr_sync.old_rank"), cell: (r) => r.old_rank ?? "—" },
    { id: "new_rank", header: t("admin.hr_sync.new_rank"), cell: (r) => r.new_rank ?? "—" },
    {
      id: "why", header: t("admin.hr_sync.why"),
      cell: (r) => (r.triggered_by_worker_decision ? t("admin.hr_sync.why_worker") : t("admin.hr_sync.why_jump")),
    },
  ];

  const runColumns: ColDef<PersonSyncRunDTO>[] = [
    { id: "status", header: t("admin.hr_sync.status"), cell: (r) => r.status },
    { id: "total_fetched", header: t("admin.hr_sync.total_fetched"), cell: (r) => r.total_fetched },
    { id: "created_count", header: t("admin.hr_sync.created_count"), cell: (r) => r.created_count },
    { id: "updated_count", header: t("admin.hr_sync.updated_count"), cell: (r) => r.updated_count },
    { id: "held_count", header: t("admin.hr_sync.held_count"), cell: (r) => r.held_count },
  ];

  return (
    <div className="space-y-6" data-testid="hr-sync-review-content">
      <div className="flex justify-end">
        <button
          type="button"
          data-testid="hr-sync-run-now"
          className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white disabled:opacity-50"
          disabled={runNowMutation.isPending}
          onClick={() => runNowMutation.mutate()}
        >
          {t("admin.hr_sync.run_now")}
        </button>
      </div>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.held_for_review")}</h3>
        <DataTable
          columns={heldColumns}
          data={heldQuery.data?.items ?? []}
          testId="hr-sync-held-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.divergences")}</h3>
        <DataTable
          columns={divergenceColumns}
          data={divergencesQuery.data?.items ?? []}
          testId="hr-sync-divergences-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.vanished")}</h3>
        <DataTable
          columns={vanishedColumns}
          data={vanishedQuery.data?.items ?? []}
          testId="hr-sync-vanished-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.rank_conflicts")}</h3>
        <DataTable
          columns={conflictColumns}
          data={conflictsQuery.data?.items ?? []}
          testId="hr-sync-conflicts-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.run_history")}</h3>
        <DataTable
          columns={runColumns}
          data={runsQuery.data?.person_syncs ?? []}
          testId="hr-sync-runs-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>
    </div>
  );
}
