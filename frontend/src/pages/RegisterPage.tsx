import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import Fuse from "fuse.js";
import { validateInviteCode, fetchRegisterNodes, register, NodeOut, listPublicExemptionTypes, PublicExemptionType } from "../api/auth";
import { getRegistrationPublicSettings } from "../api/registrationSettings";
import { useAuth } from "../auth/AuthContext";
import Combobox from "../components/Combobox";
import DateInput from "../components/DateInput";
import PasswordStrengthHint, { passwordValid } from "../components/PasswordStrengthHint";
import { queryKeys } from "../queryKeys";
import { isDateRangeValid } from "../utils/formatDate";
import { isValidIsraeliPhone } from "../utils/phoneValidation";

const ENLISTED_RANKS = ["טוראי","רבט","סמל","סמר","רסל","רסר","רסמ","רסב","רנג","קמא","סגמ"];
const OFFICER_RANKS_LIST = ["סגן","קאב","סרן","רסן","סאל","אלמ","תאל","אלוף","רב אלוף"];
const OFFICER_RANKS = new Set(OFFICER_RANKS_LIST);

function buildTree(nodes: NodeOut[]): { node: NodeOut; depth: number }[] {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const childrenOf = new Map<string | null, NodeOut[]>();
  for (const n of nodes) {
    const p = n.parent_id ?? null;
    if (!childrenOf.has(p)) childrenOf.set(p, []);
    childrenOf.get(p)!.push(n);
  }
  const result: { node: NodeOut; depth: number }[] = [];
  function walk(parentId: string | null, depth: number) {
    for (const n of childrenOf.get(parentId) ?? []) {
      result.push({ node: n, depth });
      walk(n.id, depth + 1);
    }
  }
  // Find roots: nodes whose parent_id is null or not in the set
  const rootParentId = nodes.find(n => !byId.has(n.parent_id ?? ""))?.parent_id ?? null;
  walk(rootParentId, 0);
  // Fallback: if tree walk produced nothing, show flat
  if (result.length === 0) nodes.forEach(n => result.push({ node: n, depth: 0 }));
  return result;
}

interface ExemptionRow { exemption_type_id: string; start_date: string; end_date: string; reason: string; }
interface ConstraintRow { start_date: string; end_date: string; reason: string; }
interface FormData {
  invite_code: string; personal_number: string; full_name: string;
  password: string; confirm_password: string; phone: string; email: string;
  gender: string; is_officer: boolean; rank: string; bahad1_graduate: boolean;
  enlistment_date: string; mandatory_end_date: string; discharge_date: string;
  last_mitvahim_date: string; last_alal_date: string;
  has_military_driving_license: boolean; military_driving_license_expiry: string;
  requested_node_id: string;
  exemption_requests: ExemptionRow[];
  personal_constraints: ConstraintRow[];
}

const INITIAL: FormData = {
  invite_code: "", personal_number: "", full_name: "", password: "",
  confirm_password: "", phone: "", email: "", gender: "", is_officer: false, rank: "",
  bahad1_graduate: false, enlistment_date: "", mandatory_end_date: "",
  discharge_date: "", last_mitvahim_date: "", last_alal_date: "",
  has_military_driving_license: false, military_driving_license_expiry: "",
  requested_node_id: "", exemption_requests: [], personal_constraints: [],
};

export default function RegisterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { loginWithToken } = useAuth();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormData>(INITIAL);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [nodes, setNodes] = useState<NodeOut[]>([]);
  const [nodeSearch, setNodeSearch] = useState("");
  const [exemptionTypes, setExemptionTypes] = useState<PublicExemptionType[]>([]);
  const [codeValid, setCodeValid] = useState<boolean | null>(null);

  const registrationSettingsQuery = useQuery({
    queryKey: queryKeys.registrationPublicSettings(),
    queryFn: getRegistrationPublicSettings,
  });
  const emailDomainHint = registrationSettingsQuery.data?.email_domain_hint;
  const emailPlaceholder = emailDomainHint ? `שם@${emailDomainHint}` : undefined;

  useEffect(() => {
    listPublicExemptionTypes().then(setExemptionTypes).catch(() => {});
  }, []);

  // Nodes are fetched after invite code is validated (see checkCode)

  const fuse = new Fuse(nodes, { keys: ["name", "commander_name"], threshold: 0.4 });
  const searchResultIds = nodeSearch ? new Set(fuse.search(nodeSearch).map(r => r.item.id)) : null;
  const treeRows = buildTree(nodes);
  const filteredTree = searchResultIds ? treeRows.filter(r => searchResultIds.has(r.node.id)) : treeRows;

  function set<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm(prev => ({ ...prev, [key]: value }));
  }

  async function checkCode() {
    const valid = await validateInviteCode(form.invite_code);
    setCodeValid(valid);
    if (valid) {
      fetchRegisterNodes(form.invite_code).then(setNodes).catch(() => {});
    }
    return valid;
  }

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const resp = await register({
        invite_code: form.invite_code,
        personal_number: form.personal_number,
        full_name: form.full_name,
        password: form.password,
        phone: form.phone || null,
        email: form.email || null,
        gender: form.gender || null,
        is_officer: form.is_officer,
        rank: form.rank || null,
        bahad1_graduate: form.bahad1_graduate,
        enlistment_date: form.enlistment_date || null,
        mandatory_end_date: form.mandatory_end_date || null,
        discharge_date: form.discharge_date || null,
        last_mitvahim_date: form.last_mitvahim_date || null,
        last_alal_date: form.last_alal_date || null,
        has_military_driving_license: form.has_military_driving_license,
        military_driving_license_expiry: form.has_military_driving_license ? (form.military_driving_license_expiry || null) : null,
        requested_node_id: form.requested_node_id,
        exemption_requests: form.exemption_requests.filter(er => er.exemption_type_id && er.start_date),
        personal_constraints: form.personal_constraints.filter(pc => pc.start_date && pc.end_date),
      });
      await loginWithToken(resp.access_token);
      navigate("/setup/telegram", { replace: true });
    } catch (err) {
      const detail = isAxiosError(err) ? (err.response?.data?.detail as string | undefined) : undefined;
      const knownErrors: Record<string, string> = {
        "invalid invite code": t("register.errors.invite_code_invalid"),
        "invite code exhausted": t("register.errors.invite_code_exhausted"),
        "personal_number already exists": t("register.errors.personal_number_exists"),
        "holding node not bootstrapped": t("register.errors.node_not_bootstrapped"),
        "requested node not found": t("register.errors.node_not_found"),
        "exemption_missing_fields": t("register.errors.exemption_missing_fields"),
        "constraint_missing_fields": t("register.errors.constraint_missing_fields"),
      };
      setError(detail ? (knownErrors[detail] ?? detail) : t("register.errors.network"));
    } finally {
      setSubmitting(false);
    }
  }

  const selectedNode = nodes.find(n => n.id === form.requested_node_id);

  return (
    <main className="h-[100dvh] overflow-y-auto flex items-center justify-center p-6" dir="rtl">
      <div className="w-full max-w-lg bg-white dark:bg-gray-800 shadow rounded-lg p-6 space-y-4">
        <h1 className="text-2xl font-bold text-center">{t("register.title")}</h1>
        <div className="flex gap-1 justify-center">
          {[1,2,3,4,5,6].map(s => (
            <span key={s} className={`px-2 py-1 rounded text-xs ${step === s ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500"}`}>{s}</span>
          ))}
        </div>
        {error && <div className="text-red-600 text-sm">{error}</div>}

        {step === 1 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_invite")}</h2>
            <label className="block text-sm">{t("register.invite_code_label")}
              <input className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.invite_code}
                onChange={e => { set("invite_code", e.target.value); setCodeValid(null); }} />
            </label>
            {codeValid === false && <p className="text-red-600 text-sm">{t("register.invite_code_invalid")}</p>}
            <button className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
              onClick={async () => { if (await checkCode()) setStep(2); }} disabled={!form.invite_code}>
              {t("register.next")}
            </button>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-2">
            <h2 className="font-semibold">{t("register.step_personal")}</h2>
            <p className="text-xs text-gray-400">שדות עם <span className="text-red-500">*</span> הם חובה</p>
            <label className="block text-sm">מספר אישי <span className="text-red-500">*</span>
              <input type="text" className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={form.personal_number} onChange={e => set("personal_number", e.target.value)} />
            </label>
            <label className="block text-sm">שם מלא <span className="text-red-500">*</span>
              <input type="text" className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={form.full_name} onChange={e => set("full_name", e.target.value)} />
            </label>
            <label className="block text-sm">טלפון <span className="text-red-500">*</span>
              <input type="tel" dir="ltr" placeholder="05X-XXXXXXX" className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={form.phone} onChange={e => set("phone", e.target.value)} />
              {form.phone && !isValidIsraeliPhone(form.phone) && (
                <span className="text-red-600 text-xs">מספר טלפון לא תקין</span>
              )}
            </label>
            <label className="block text-sm">אימייל <span className="text-red-500">*</span>
              <input type="email" placeholder={emailPlaceholder} className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={form.email} onChange={e => set("email", e.target.value)} />
            </label>
            <label className="block text-sm">מגדר <span className="text-red-500">*</span>
              <select className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.gender} onChange={e => set("gender", e.target.value)}>
                <option value="">בחר</option><option value="male">זכר</option><option value="female">נקבה</option><option value="other">אחר</option>
              </select>
            </label>
            <label className="block text-sm">דרגה <span className="text-red-500">*</span>
              <Combobox
                items={[
                  ...ENLISTED_RANKS.map(r => ({ id: r, name: r, group: "חיילים" })),
                  ...OFFICER_RANKS_LIST.map(r => ({ id: r, name: r, group: "קצינים" })),
                ]}
                value={form.rank}
                onChange={v => {
                  const isOfficer = OFFICER_RANKS.has(v);
                  setForm(prev => ({ ...prev, rank: v, is_officer: isOfficer, bahad1_graduate: isOfficer, last_alal_date: isOfficer ? prev.last_alal_date : "" }));
                }}
                placeholder="בחר"
              />
            </label>
            {form.rank && (
              <div className="text-xs text-gray-500 space-x-3 flex gap-3">
                {form.is_officer && <span className="text-indigo-600 dark:text-indigo-300">✓ קצין</span>}
                {form.bahad1_graduate && <span className="text-indigo-600 dark:text-indigo-300">✓ בוגר בה&quot;ד 1</span>}
              </div>
            )}
            {([["enlistment_date","תאריך גיוס"],["mandatory_end_date","סיום חובה"],["discharge_date","שחרור"],["last_mitvahim_date","מטווח אחרון"]] as [keyof FormData, string][]).map(([key, label]) => (
              <label key={key as string} className="block text-sm">{label} <span className="text-red-500">*</span>
                <DateInput className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  value={form[key] as string} onChange={iso => set(key, iso)} />
              </label>
            ))}
            {form.is_officer && (
              <label className="block text-sm">אל&quot;ל אחרון
                <DateInput className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  value={form.last_alal_date} onChange={iso => set("last_alal_date", iso)} />
              </label>
            )}
            <div className="block text-sm">
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={form.has_military_driving_license}
                  onChange={e => set("has_military_driving_license", e.target.checked)} />
                רישיון נהיגה צבאי
              </label>
              {form.has_military_driving_license && (
                <label className="block text-sm mt-1">תוקף הרישיון
                  <DateInput className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    value={form.military_driving_license_expiry} onChange={iso => set("military_driving_license_expiry", iso)} />
                </label>
              )}
            </div>
            <label className="block text-sm">סיסמה <span className="text-red-500">*</span>
              <input type="password" dir="ltr" className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.password} onChange={e => set("password", e.target.value)} />
              <PasswordStrengthHint password={form.password} />
            </label>
            <label className="block text-sm">אימות סיסמה <span className="text-red-500">*</span>
              <input type="password" dir="ltr" className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.confirm_password} onChange={e => set("confirm_password", e.target.value)} />
            </label>
            {form.confirm_password && form.password !== form.confirm_password && (
              <p className="text-red-600 text-sm">הסיסמאות אינן תואמות</p>
            )}
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(1)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={
                  !form.personal_number || !form.full_name || !isValidIsraeliPhone(form.phone) || !form.email ||
                  !form.gender || !form.rank || !form.enlistment_date || !form.mandatory_end_date ||
                  !form.discharge_date || !form.last_mitvahim_date ||
                  !passwordValid(form.password) || form.password !== form.confirm_password
                }
                onClick={() => setStep(3)}>{t("register.next")}</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_exemptions")}</h2>
            {form.exemption_requests.map((er, i) => (
              <div key={i} className="border rounded p-2 space-y-1 text-sm">
                <Combobox
                  items={exemptionTypes.map(et => ({ id: et.id, name: et.name }))}
                  value={er.exemption_type_id}
                  onChange={v => {
                    const rows = [...form.exemption_requests];
                    rows[i] = { ...rows[i], exemption_type_id: v };
                    set("exemption_requests", rows);
                  }}
                  placeholder="סוג פטור"
                />
                <DateInput className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={er.start_date}
                  max={er.end_date || undefined}
                  onChange={iso => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], start_date: iso}; set("exemption_requests", rows); }} />
                <DateInput className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={er.end_date}
                  min={er.start_date || undefined}
                  onChange={iso => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], end_date: iso}; set("exemption_requests", rows); }} />
                <input placeholder={t("register.reason")} className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={er.reason}
                  onChange={e => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], reason: e.target.value}; set("exemption_requests", rows); }} />
                <button className="text-red-600 text-xs" onClick={() => set("exemption_requests", form.exemption_requests.filter((_,j) => j !== i))}>{t("register.remove")}</button>
              </div>
            ))}
            <button className="text-indigo-600 dark:text-indigo-300 text-sm"
              onClick={() => set("exemption_requests", [...form.exemption_requests, {exemption_type_id:"",start_date:"",end_date:"",reason:""}])}>
              + {t("register.add_exemption")}
            </button>
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(2)}>{t("register.back")}</button>
              <button
                className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={form.exemption_requests.some(er => !er.exemption_type_id || !er.start_date || !isDateRangeValid(er.start_date, er.end_date))}
                onClick={() => setStep(4)}
              >
                {t("register.next")}
              </button>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_constraints")}</h2>
            {form.personal_constraints.map((pc, i) => (
              <div key={i} className="border rounded p-2 space-y-1 text-sm">
                <DateInput className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={pc.start_date}
                  max={pc.end_date || undefined}
                  onChange={iso => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], start_date: iso}; set("personal_constraints", rows); }} />
                <DateInput className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={pc.end_date}
                  min={pc.start_date || undefined}
                  onChange={iso => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], end_date: iso}; set("personal_constraints", rows); }} />
                <input placeholder={t("register.reason")} className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={pc.reason}
                  onChange={e => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], reason: e.target.value}; set("personal_constraints", rows); }} />
                <button className="text-red-600 text-xs" onClick={() => set("personal_constraints", form.personal_constraints.filter((_,j) => j !== i))}>{t("register.remove")}</button>
              </div>
            ))}
            <button className="text-indigo-600 dark:text-indigo-300 text-sm"
              onClick={() => set("personal_constraints", [...form.personal_constraints, {start_date:"",end_date:"",reason:""}])}>
              + {t("register.add_constraint")}
            </button>
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(3)}>{t("register.back")}</button>
              <button
                className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={form.personal_constraints.some(pc => !pc.start_date || !pc.end_date || !isDateRangeValid(pc.start_date, pc.end_date))}
                onClick={() => setStep(5)}
              >
                {t("register.next")}
              </button>
            </div>
          </div>
        )}

        {step === 5 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_commander")} <span className="text-red-500">*</span></h2>
            <input className="block w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" placeholder={t("register.search_commander")}
              value={nodeSearch} onChange={e => setNodeSearch(e.target.value)} />
            <div className="max-h-60 overflow-y-auto border rounded text-sm">
              {filteredTree.length === 0 && <p className="p-2 text-gray-400">{t("register.no_results")}</p>}
              {filteredTree.map(({ node: n, depth }) => (
                <button key={n.id}
                  className={`w-full text-right flex items-center gap-1 py-1.5 px-2 hover:bg-indigo-50 dark:hover:bg-indigo-950 border-b dark:border-gray-700 last:border-b-0 ${form.requested_node_id === n.id ? "bg-indigo-100 dark:bg-indigo-900 font-semibold" : ""}`}
                  style={{ paddingRight: `${0.5 + depth * 1.25}rem` }}
                  onClick={() => set("requested_node_id", n.id)}>
                  {depth > 0 && <span className="text-gray-300 dark:text-gray-600 shrink-0">└</span>}
                  <span className="truncate">{n.name}</span>
                  {n.commander_name && <span className="text-gray-400 text-xs shrink-0 mr-1">({n.commander_name})</span>}
                </button>
              ))}
            </div>
            {selectedNode && (
              <p className="text-sm text-indigo-700 dark:text-indigo-300">
                {t("register.selected_node")}: <strong>{selectedNode.name}</strong>
                {selectedNode.commander_name && <> · {t("register.commander_label")}: {selectedNode.commander_name}</>}
              </p>
            )}
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(4)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={!form.requested_node_id} onClick={() => setStep(6)}>{t("register.next")}</button>
            </div>
          </div>
        )}

        {step === 6 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_review")}</h2>
            <dl className="divide-y text-sm">
              <div className="py-1 flex justify-between"><dt className="text-gray-500">מספר אישי</dt><dd>{form.personal_number}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">שם מלא</dt><dd>{form.full_name}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">דרגה</dt><dd>{form.rank}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">מסגרת מבוקשת</dt><dd>{selectedNode?.name ?? "—"}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">בקשות פטור</dt><dd>{form.exemption_requests.length}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">אילוצים</dt><dd>{form.personal_constraints.length}</dd></div>
            </dl>
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(5)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={submitting} onClick={handleSubmit}>
                {submitting ? t("register.submitting") : t("register.submit")}
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
