import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import ShiftTemplateFormModal from "../components/ShiftTemplateFormModal";
import GenerateShiftsModal from "../components/GenerateShiftsModal";
import { ShiftTemplate, deleteTemplate, listTemplates } from "../api/shiftTemplates";
import { DutyType, DutyLocation, listDutyTypes, listLocations } from "../api/dutyConfig";
import { DataTable, type ColDef } from "../components/DataTable";

export function ShiftTemplatesContent() {
  const { t } = useTranslation();
  const [templates, setTemplates] = useState<ShiftTemplate[]>([]);
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editTemplate, setEditTemplate] = useState<ShiftTemplate | null>(null);
  const [generateTemplateId, setGenerateTemplateId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [tmps, dts, locs] = await Promise.all([
      listTemplates(),
      listDutyTypes(),
      listLocations(),
    ]);
    setTemplates(tmps);
    setDutyTypes(dts);
    setLocations(locs);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

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
      id: "weekdays",
      header: t("shift_templates.weekdays"),
      cell: (tmpl) => (
        <span className="flex gap-1 flex-wrap">
          {tmpl.weekdays.map(d => (
            <span key={d} className="bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 px-1.5 py-0.5 rounded text-xs">
              {t(`weekday_${d}`)}
            </span>
          ))}
        </span>
      ),
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
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl" data-testid="shift-templates-page">
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
      </section>

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
