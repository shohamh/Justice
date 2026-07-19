import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Layout from "../components/Layout";
import ShiftTemplateFormModal from "../components/ShiftTemplateFormModal";
import GenerateShiftsModal from "../components/GenerateShiftsModal";
import { queryKeys } from "../queryKeys";
import { ShiftTemplate, deleteTemplate, listTemplates } from "../api/shiftTemplates";
import { listDutyTypes, listLocations } from "../api/dutyConfig";
import { DataTable, type ColDef } from "../components/DataTable";

export function ShiftTemplatesContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editTemplate, setEditTemplate] = useState<ShiftTemplate | null>(null);
  const [generateTemplateId, setGenerateTemplateId] = useState<string | null>(null);

  const templatesQuery = useQuery({ queryKey: queryKeys.shiftTemplates(), queryFn: () => listTemplates() });
  const templates = templatesQuery.data ?? [];

  const dutyTypesQuery = useQuery({ queryKey: queryKeys.dutyTypes(), queryFn: listDutyTypes });
  const dutyTypes = dutyTypesQuery.data ?? [];

  const locationsQuery = useQuery({ queryKey: queryKeys.dutyLocations(), queryFn: listLocations });
  const locations = locationsQuery.data ?? [];

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: queryKeys.shiftTemplates() });
  }

  async function handleDelete(tmpl: ShiftTemplate) {
    if (!window.confirm(t("shift_templates.confirm_delete"))) return;
    try {
      await deleteTemplate(tmpl.id);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(detail ?? "שגיאה");
    }
  }

  const dtName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);

  const cols: ColDef<ShiftTemplate>[] = [
    {
      id: "name",
      header: t("shift_templates.name"),
      cell: (tmpl) => tmpl.name,
      sortValue: (tmpl) => tmpl.name,
      filterValue: (tmpl) => tmpl.name,
    },
    {
      id: "duty_type",
      header: t("shift_templates.duty_type"),
      cell: (tmpl) => dtName(tmpl.duty_type_id),
      sortValue: (tmpl) => dtName(tmpl.duty_type_id),
      filterValue: (tmpl) => dtName(tmpl.duty_type_id),
    },
    {
      id: "recurrence_type",
      header: t("shift_templates.recurrence_type"),
      cell: (tmpl) => (
        <span className="flex flex-col gap-1">
          <span className="bg-violet-100 dark:bg-violet-900 text-violet-700 dark:text-violet-300 px-1.5 py-0.5 rounded text-xs w-fit">
            {t(`shift_templates.recurrence_${tmpl.recurrence_type}`)}
          </span>
          {tmpl.recurrence_type === "weekly" && tmpl.weekdays.length === 1 && (
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {t(`weekday_${tmpl.weekdays[0]}`)}
              {tmpl.duration_days > 1 && ` · ${tmpl.duration_days} ${t("shift_templates.days", "ימים")}`}
            </span>
          )}
        </span>
      ),
      filterValue: (tmpl) => t(`shift_templates.recurrence_${tmpl.recurrence_type}`),
    },
    {
      id: "required_count",
      header: t("shift_templates.required_count"),
      cell: (tmpl) => tmpl.required_count,
      sortValue: (tmpl) => tmpl.required_count,
    },
    {
      id: "auto_roll",
      header: t("shift_templates.auto_roll"),
      cell: (tmpl) => tmpl.auto_roll
        ? <span className="bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 px-2 py-0.5 rounded text-xs font-medium">{t("shift_templates.auto_badge")}</span>
        : null,
    },
    {
      id: "actions",
      header: t("shift_templates.actions"),
      cell: (tmpl) => (
        <span className="space-x-2 space-x-reverse">
          <button
            type="button"
            onClick={() => setGenerateTemplateId(tmpl.id)}
            className="text-green-600 text-xs hover:underline"
          >
            {t("shift_templates.generate")}
          </button>
          <button
            type="button"
            onClick={() => setEditTemplate(tmpl)}
            className="text-blue-600 dark:text-blue-400 text-xs hover:underline"
          >
            {t("shift_templates.edit")}
          </button>
          <button
            type="button"
            onClick={() => handleDelete(tmpl)}
            className="text-red-600 text-xs hover:underline"
          >
            {t("shift_templates.delete")}
          </button>
        </span>
      ),
    },
  ];

  return (
    <>
      <div data-testid="shift-templates-page" className="space-y-4">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-semibold">{t("shift_templates.title")}</h2>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
          >
            {t("shift_templates.create")}
          </button>
        </div>

        <DataTable
          columns={cols}
          data={templates}
          filterPlaceholder={t("table.filter_placeholder")}
          emptyMessage="אין תבניות"
        />
      </div>

      {showCreate && (
        <ShiftTemplateFormModal
          dutyTypes={dutyTypes}
          locations={locations}
          onSubmit={async () => { setShowCreate(false); await refresh(); }}
          onClose={() => setShowCreate(false)}
        />
      )}
      {editTemplate && (
        <ShiftTemplateFormModal
          dutyTypes={dutyTypes}
          locations={locations}
          initial={editTemplate}
          onSubmit={async () => { setEditTemplate(null); await refresh(); }}
          onClose={() => setEditTemplate(null)}
        />
      )}
      {generateTemplateId && (
        <GenerateShiftsModal
          open={true}
          templateId={generateTemplateId}
          onClose={() => setGenerateTemplateId(null)}
          onGenerated={() => setGenerateTemplateId(null)}
        />
      )}
    </>
  );
}

export default function ShiftTemplatesPage() {
  return <Layout><ShiftTemplatesContent /></Layout>;
}
