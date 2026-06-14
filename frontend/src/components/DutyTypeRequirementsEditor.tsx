import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyType, updateDutyTypeRequirements } from "../api/dutyConfig";
import { getRanks } from "../api/soldiers";

interface Props {
  dutyType: DutyType;
  onSaved: () => void;
}

export default function DutyTypeRequirementsEditor({ dutyType, onSaved }: Props) {
  const { t } = useTranslation();
  const [reqs, setReqs] = useState<NonNullable<DutyType["requirements"]>>(dutyType.requirements ?? {});
  const [ranks, setRanks] = useState<{ enlisted: string[]; officers: string[] }>({ enlisted: [], officers: [] });

  useEffect(() => {
    void getRanks().then(setRanks);
  }, []);

  function toggleItem(key: keyof NonNullable<DutyType["requirements"]>, value: string) {
    const current: string[] = (reqs[key] as string[] | undefined) ?? [];
    const next = current.includes(value)
      ? current.filter((v: string) => v !== value)
      : [...current, value];
    setReqs(prev => ({ ...prev, [key]: next }));
  }

  async function save() {
    await updateDutyTypeRequirements(dutyType.id, reqs);
    onSaved();
  }

  return (
    <div className="space-y-3 text-sm" dir="rtl">
      {/* Gender */}
      <div>
        <p className="font-medium">{t("eligibility.allowed_genders")}</p>
        <div className="flex flex-wrap gap-3">
          {["male", "female"].map(g => (
            <label key={g} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={(reqs.allowed_genders ?? []).includes(g)}
                onChange={() => toggleItem("allowed_genders", g)}
              />
              {g === "male" ? t("soldier_profile.gender_male") : t("soldier_profile.gender_female")}
            </label>
          ))}
        </div>
      </div>

      {/* Ranks */}
      <div>
        <p className="font-medium">{t("eligibility.allowed_ranks")}</p>
        <div className="space-y-1">
          <p className="text-xs text-gray-500">{t("soldier_profile.enlisted")}</p>
          <div className="flex flex-wrap gap-2">
            {ranks.enlisted.map(r => (
              <label key={r} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={(reqs.allowed_ranks ?? []).includes(r)}
                  onChange={() => toggleItem("allowed_ranks", r)}
                />
                {r}
              </label>
            ))}
          </div>
          <p className="text-xs text-gray-500">{t("soldier_profile.officers")}</p>
          <div className="flex flex-wrap gap-2">
            {ranks.officers.map(r => (
              <label key={r} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={(reqs.allowed_ranks ?? []).includes(r)}
                  onChange={() => toggleItem("allowed_ranks", r)}
                />
                {r}
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Service type */}
      <div>
        <p className="font-medium">{t("eligibility.allowed_service_types")}</p>
        <div className="flex flex-wrap gap-3">
          {["חובה", "קבע"].map(s => (
            <label key={s} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={(reqs.allowed_service_types ?? []).includes(s)}
                onChange={() => toggleItem("allowed_service_types", s)}
              />
              {s}
            </label>
          ))}
        </div>
      </div>

      {/* Boolean flags */}
      {[
        { key: "requires_mitvahim", label: t("eligibility.requires_mitvahim") },
        { key: "requires_alal", label: t("eligibility.requires_alal") },
        { key: "requires_bahad1", label: t("eligibility.requires_bahad1") },
        { key: "officers_allowed", label: t("eligibility.officers_allowed"), defaultVal: true },
        { key: "enlisted_allowed", label: t("eligibility.enlisted_allowed"), defaultVal: true },
      ].map(({ key, label, defaultVal }) => (
        <label key={key} className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={(reqs[key as keyof NonNullable<DutyType["requirements"]>] as boolean | undefined) ?? (defaultVal ?? false)}
            onChange={e => setReqs(prev => ({ ...prev, [key]: e.target.checked }))}
          />
          {label}
        </label>
      ))}

      <button
        type="button"
        onClick={save}
        className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
      >
        {t("eligibility.save")}
      </button>
    </div>
  );
}
