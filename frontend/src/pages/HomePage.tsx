import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import AlertBanners from "../components/dashboard/AlertBanners";
import DutyCalendarWidget from "../components/dashboard/DutyCalendarWidget";
import DutyDetailModal from "../components/dashboard/DutyDetailModal";
import UpcomingDutiesWidget from "../components/dashboard/UpcomingDutiesWidget";
import SwapStatusWidget from "../components/dashboard/SwapStatusWidget";
import PendingApprovalsWidget from "../components/dashboard/PendingApprovalsWidget";
import DutyHistoryWidget from "../components/dashboard/DutyHistoryWidget";

import { useAuth } from "../auth/AuthContext";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { DutyType, DutyLocation, listDutyTypes, listLocations } from "../api/dutyConfig";
import { SwapRequest, listMySwaps, listPendingSwaps } from "../api/swaps";
import { EnrollmentRequestDTO, listPendingEnrollments } from "../api/enrollment";
import { SettingsMap, getSystemSettings } from "../api/systemSettings";
import { TransparencyRow, getTransparency } from "../api/scoring";

function offsetDate(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split("T")[0];
}

export default function HomePage() {
  const { t } = useTranslation();
  const { user } = useAuth();

  const [duties, setDuties] = useState<EffectiveDuty[]>([]);
  const [typeNames, setTypeNames] = useState<Record<string, string>>({});
  const [locationNames, setLocationNames] = useState<Record<string, string>>({});
  const [selectedDuty, setSelectedDuty] = useState<EffectiveDuty | null>(null);
  const [mySwaps, setMySwaps] = useState<SwapRequest[]>([]);
  const [pendingEnrollments, setPendingEnrollments] = useState<EnrollmentRequestDTO[]>([]);
  const [pendingSwaps, setPendingSwaps] = useState<SwapRequest[]>([]);
  const [settings, setSettings] = useState<SettingsMap>({});
  const [transparencyRows, setTransparencyRows] = useState<TransparencyRow[]>([]);

  const canApprove = user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin";

  function handleOpenDuty(duty: EffectiveDuty) {
    setSelectedDuty(duty);
  }

  function handleRequestSwap(duty: EffectiveDuty) {
    setSelectedDuty(null);
    // navigate to swap creation — link to swaps page with assignment id
    window.location.href = `/swaps?new=${duty.assignment_id}`;
  }
  const myRow = useMemo(() => transparencyRows.find((r) => r.soldier_id === user?.id) ?? null, [transparencyRows, user]);

  useEffect(() => {
    if (!user) return;

    const dutyFetch = listEffectiveDuties(user.id, {
      date_from: offsetDate(-365),
      date_to: offsetDate(60),
    }).catch(() => [] as EffectiveDuty[]);

    const typesFetch = listDutyTypes().catch(() => [] as DutyType[]);
    const locsFetch = listLocations().catch(() => [] as DutyLocation[]);
    const swapsFetch = listMySwaps().catch(() => [] as SwapRequest[]);
    const settingsFetch = getSystemSettings().catch(() => ({} as SettingsMap));
    const transparencyFetch = getTransparency().catch(() => [] as TransparencyRow[]);

    const enrollFetch = canApprove
      ? listPendingEnrollments().catch(() => [] as EnrollmentRequestDTO[])
      : Promise.resolve([] as EnrollmentRequestDTO[]);

    const pendingSwapsFetch = canApprove
      ? listPendingSwaps().catch(() => [] as SwapRequest[])
      : Promise.resolve([] as SwapRequest[]);

    void Promise.all([dutyFetch, typesFetch, locsFetch, swapsFetch, settingsFetch, enrollFetch, pendingSwapsFetch, transparencyFetch]).then(
      ([d, dts, locs, sw, sett, enr, psw, tr]) => {
        setDuties(d);
        setTypeNames(Object.fromEntries((dts as DutyType[]).map((t) => [t.id, t.name])));
        setLocationNames(Object.fromEntries((locs as DutyLocation[]).map((l) => [l.id, l.name])));
        setMySwaps(sw);
        setSettings(sett);
        setPendingEnrollments(enr as EnrollmentRequestDTO[]);
        setPendingSwaps(psw as SwapRequest[]);
        setTransparencyRows(tr as TransparencyRow[]);
      }
    );
  }, [user, canApprove]);

  return (
    <Layout>
      <div className="space-y-4 max-w-3xl mx-auto" dir="rtl">
        <h2 className="text-xl font-semibold">{t("home.welcome", { name: user?.full_name ?? "" })}</h2>

        <AlertBanners
          lastMitvahimDate={user?.last_mitvahim_date ?? null}
          lastAlalDate={user?.last_alal_date ?? null}
          settings={settings}
        />

        <DutyCalendarWidget duties={duties} typeNames={typeNames} onOpenDuty={handleOpenDuty} />

        <UpcomingDutiesWidget
          duties={duties}
          typeNames={typeNames}
          locationNames={locationNames}
          onOpenDuty={handleOpenDuty}
        />

        <SwapStatusWidget swaps={mySwaps} />

        {canApprove && (
          <PendingApprovalsWidget
            pendingEnrollments={pendingEnrollments}
            pendingSwaps={pendingSwaps}
          />
        )}

        <DutyHistoryWidget
          duties={duties}
          typeNames={typeNames}
          locationNames={locationNames}
          myRow={myRow}
          allRows={transparencyRows}
        />
      </div>

      <DutyDetailModal
        duty={selectedDuty}
        typeNames={typeNames}
        locationNames={locationNames}
        onClose={() => setSelectedDuty(null)}
        onRequestSwap={handleRequestSwap}
      />
    </Layout>
  );
}
