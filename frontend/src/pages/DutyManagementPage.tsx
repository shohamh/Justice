import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { Assignment, cancelAssignment, createAssignment, listAssignments, setOverride } from "../api/assignments";
import { createAdjustment } from "../api/scoreAdjustments";
import { DutyLocation, DutyType, listDutyTypes, listLocations } from "../api/dutyConfig";
import { SoldierDTO, listSoldiers } from "../api/soldiers";

export function DutyManagementContent() {
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [types, setTypes] = useState<DutyType[]>([]);
  const [locs, setLocs] = useState<DutyLocation[]>([]);
  const [soldierId, setSoldierId] = useState("");
  const [typeId, setTypeId] = useState("");
  const [locId, setLocId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [rows, setRows] = useState<Assignment[]>([]);
  const [error, setError] = useState("");
  const [adjDelta, setAdjDelta] = useState("");
  const [adjReason, setAdjReason] = useState("");

  useEffect(() => {
    void (async () => {
      const [ss, dts, ls] = await Promise.all([listSoldiers(), listDutyTypes(), listLocations()]);
      setSoldiers(ss); setTypes(dts); setLocs(ls);
      if (ss[0]) setSoldierId(ss[0].id);
      if (dts[0]) setTypeId(dts[0].id);
      if (ls[0]) setLocId(ls[0].id);
    })();
  }, []);

  const refresh = useCallback(async (sid: string) => {
    if (sid) setRows(await listAssignments(sid));
  }, []);

  useEffect(() => { void refresh(soldierId); }, [soldierId, refresh]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await createAssignment({ soldier_id: soldierId, duty_type_id: typeId, duty_location_id: locId, start_date: start, end_date: end });
      setStart(""); setEnd("");
      await refresh(soldierId);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setError(detail ? (t(`errors.${detail}` as any) || detail) : t("errors.generic"));
    }
  }

  async function doCancel(id: string) {
    const reason = window.prompt(t("duty_management.cancel_reason"));
    if (!reason) return;
    await cancelAssignment(id, reason);
    await refresh(soldierId);
  }

  async function doOverride(id: string) {
    const day = window.prompt(t("duty_management.override_day"));
    if (!day) return;
    const repl = window.prompt(t("duty_management.replacement"));
    await setOverride(id, day, { effective_soldier_id: repl || null, reason: repl ? "replacement" : "cancelled" });
    await refresh(soldierId);
  }

  async function submitAdj(e: FormEvent) {
    e.preventDefault();
    await createAdjustment({ soldier_id: soldierId, delta: adjDelta, reason: adjReason });
    setAdjDelta(""); setAdjReason("");
  }

  return (
    <section className="bg-white rounded-lg shadow p-6 space-y-6" data-testid="duty-management-page">
      <h2 className="text-xl font-semibold">{t("duty_management.title")}</h2>

      <label className="block text-sm">{t("duty_management.soldier")}
        <select className="block border rounded p-1" value={soldierId} onChange={(e) => setSoldierId(e.target.value)} data-testid="dm-soldier">
          {soldiers.map((s) => <option key={s.id} value={s.id}>{s.full_name}</option>)}
        </select>
      </label>

      <form onSubmit={submit} className="flex flex-wrap items-end gap-2" data-testid="assignment-form">
        <select className="border rounded p-1" value={typeId} onChange={(e) => setTypeId(e.target.value)} data-testid="dm-type">
          {types.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select className="border rounded p-1" value={locId} onChange={(e) => setLocId(e.target.value)} data-testid="dm-loc">
          {locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        <input type="date" className="border rounded p-1" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="dm-start" />
        <input type="date" className="border rounded p-1" value={end} onChange={(e) => setEnd(e.target.value)} required data-testid="dm-end" />
        <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="dm-create">{t("duty_management.create")}</button>
      </form>
      {error && <p className="text-red-600 text-sm" data-testid="dm-error">{error}</p>}

      <ul className="text-sm space-y-1" data-testid="assignment-list">
        {rows.length === 0 && <li data-testid="dm-empty">{t("duty_management.none")}</li>}
        {rows.map((a) => (
          <li key={a.id} data-testid={`assignment-row-${a.id}`} className="flex items-center gap-2">
            <span dir="ltr">{a.start_date} → {a.end_date}</span>
            <button className="text-xs text-indigo-600" onClick={() => doOverride(a.id)} data-testid={`override-${a.id}`}>{t("duty_management.override")}</button>
            <button className="text-xs text-red-600" onClick={() => doCancel(a.id)} data-testid={`cancel-${a.id}`}>{t("duty_management.cancel")}</button>
          </li>
        ))}
      </ul>

      <form onSubmit={submitAdj} className="flex items-end gap-2 border-t pt-4" data-testid="adjustment-form">
        <h3 className="font-medium">{t("duty_management.score_adjustment")}</h3>
        <input className="border rounded p-1 w-24" value={adjDelta} onChange={(e) => setAdjDelta(e.target.value)} placeholder={t("duty_management.delta")} required data-testid="adj-delta" />
        <input className="border rounded p-1" value={adjReason} onChange={(e) => setAdjReason(e.target.value)} placeholder={t("duty_management.reason")} required data-testid="adj-reason" />
        <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="adj-submit">{t("duty_management.apply")}</button>
      </form>
    </section>
  );
}

export default function DutyManagementPage() {
  return <Layout><DutyManagementContent /></Layout>;
}
