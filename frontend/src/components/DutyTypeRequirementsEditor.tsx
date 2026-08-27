import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyType, updateDutyTypeRequirements } from "../api/dutyConfig";
import { getRanks } from "../api/soldiers";
import { isRankTrackFlexible } from "../constants/ranks";

type Reqs = NonNullable<DutyType["requirements"]>;

interface UncontrolledProps {
  dutyType: DutyType;
  onSaved: () => void;
  value?: undefined;
  onChange?: undefined;
}

interface ControlledProps {
  dutyType?: undefined;
  onSaved?: undefined;
  value: Reqs;
  onChange: (next: Reqs) => void;
}

type Props = UncontrolledProps | ControlledProps;

export default function DutyTypeRequirementsEditor(props: Props) {
  const { t } = useTranslation();
  const isControlled = props.value !== undefined;
  const [localReqs, setLocalReqs] = useState<Reqs>(
    isControlled ? props.value : (props.dutyType!.requirements ?? {})
  );
  const reqs = isControlled ? props.value : localReqs;
  const [ranks, setRanks] = useState<{ enlisted: string[]; officers: string[]; officer_academic: string[] }>({ enlisted: [], officers: [], officer_academic: [] });

  useEffect(() => {
    void getRanks().then(setRanks);
  }, []);

  function setReqs(updater: (prev: Reqs) => Reqs) {
    if (isControlled) {
      props.onChange(updater(reqs));
    } else {
      setLocalReqs(updater);
    }
  }

  function toggleItem(key: keyof Reqs, value: string) {
    const current: string[] = (reqs[key] as string[] | undefined) ?? [];
    const next = current.includes(value)
      ? current.filter((v: string) => v !== value)
      : [...current, value];
    setReqs(prev => ({ ...prev, [key]: next }));
  }

  function rankServiceTypeOverride(rank: string): "" | "חובה" | "קבע" {
    const list = reqs.rank_service_types?.[rank];
    if (list) return list.length === 1 ? (list[0] as "חובה" | "קבע") : "";
    // No explicit per-rank override: preselect the global service type when
    // exactly one is chosen, since that's the value this rank actually
    // inherits — an empty "ללא הגבלה" selection would misrepresent it.
    const global = reqs.allowed_service_types ?? [];
    return global.length === 1 ? (global[0] as "חובה" | "קבע") : "";
  }

  function setRankServiceTypeOverride(rank: string, value: "" | "חובה" | "קבע") {
    setReqs(prev => {
      const next = { ...(prev.rank_service_types ?? {}) };
      // An explicit "" must mean "unrestricted for this rank" even when a
      // global allowed_service_types filter would otherwise apply — so it
      // needs to be stored as an explicit empty override, not just removed
      // (removing it would fall back to inheriting the global filter again).
      next[rank] = value === "" ? [] : [value];
      return { ...prev, rank_service_types: next };
    });
  }

  async function save() {
    if (isControlled) return;
    await updateDutyTypeRequirements(props.dutyType!.id, reqs);
    props.onSaved!();
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
          {ranks.officer_academic.filter(r => !ranks.officers.includes(r)).length > 0 && (
            <>
              <p className="text-xs text-gray-500">קצינים אקדמאים</p>
              <div className="flex flex-wrap gap-2">
                {ranks.officer_academic.filter(r => !ranks.officers.includes(r)).map(r => (
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
            </>
          )}
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

      {/* Per-rank service-type override, for ranks that span both tracks (e.g. סמ"ר, סגן) */}
      {(reqs.allowed_ranks ?? []).filter(isRankTrackFlexible).length > 0 && (
        <div>
          <p className="font-medium">{t("eligibility.rank_service_type_override")}</p>
          <div className="space-y-1">
            {(reqs.allowed_ranks ?? []).filter(isRankTrackFlexible).map(rank => (
              <div key={rank} className="flex items-center gap-2 text-xs">
                <span className="w-10">{rank}</span>
                <select
                  className="border rounded px-1 py-0.5 dark:bg-gray-700 dark:border-gray-600"
                  value={rankServiceTypeOverride(rank)}
                  onChange={e => setRankServiceTypeOverride(rank, e.target.value as "" | "חובה" | "קבע")}
                  data-testid={`rank-service-type-${rank}`}
                >
                  <option value="">{t("eligibility.rank_service_type_none")}</option>
                  <option value="חובה">חובה</option>
                  <option value="קבע">קבע</option>
                </select>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Boolean flags */}
      {[
        { key: "requires_mitvahim", label: t("eligibility.requires_mitvahim") },
        { key: "requires_alal", label: t("eligibility.requires_alal") },
        { key: "requires_bahad1", label: t("eligibility.requires_bahad1") },
        { key: "requires_military_driving_license", label: t("eligibility.requires_military_driving_license") },
        { key: "officers_allowed", label: t("eligibility.officers_allowed"), defaultVal: true },
        { key: "enlisted_allowed", label: t("eligibility.enlisted_allowed"), defaultVal: true },
      ].map(({ key, label, defaultVal }) => (
        <label key={key} className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={(reqs[key as keyof Reqs] as boolean | undefined) ?? (defaultVal ?? false)}
            onChange={e => setReqs(prev => ({ ...prev, [key]: e.target.checked }))}
          />
          {label}
        </label>
      ))}

      {!isControlled && (
        <button
          type="button"
          onClick={save}
          className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
        >
          {t("eligibility.save")}
        </button>
      )}
    </div>
  );
}
