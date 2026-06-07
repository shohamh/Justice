import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { isAxiosError } from "axios";
import Fuse from "fuse.js";
import { validateInviteCode, fetchRegisterNodes, register, NodeOut } from "../api/auth";
import { useAuth } from "../auth/AuthContext";

const ALL_RANKS = [
  "טוראי","רבט","סמל","סמר","רסל","רסר","רסמ","רסב","רנג",
  "קמא","סגמ","סגן","קאב","סרן","רסן","סאל","אלמ","תאל","אלוף","רב אלוף",
];

interface ExemptionRow { exemption_type_id: string; start_date: string; end_date: string; reason: string; }
interface ConstraintRow { start_date: string; end_date: string; reason: string; }
interface FormData {
  invite_code: string; personal_number: string; full_name: string;
  password: string; confirm_password: string; phone: string; email: string;
  gender: string; is_officer: boolean; rank: string; bahad1_graduate: boolean;
  enlistment_date: string; mandatory_end_date: string; discharge_date: string;
  last_mitvahim_date: string; last_alal_date: string;
  requested_node_id: string;
  exemption_requests: ExemptionRow[];
  personal_constraints: ConstraintRow[];
}

const INITIAL: FormData = {
  invite_code: "", personal_number: "", full_name: "", password: "",
  confirm_password: "", phone: "", email: "", gender: "", is_officer: false, rank: "",
  bahad1_graduate: false, enlistment_date: "", mandatory_end_date: "",
  discharge_date: "", last_mitvahim_date: "", last_alal_date: "",
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
  const [codeValid, setCodeValid] = useState<boolean | null>(null);

  useEffect(() => { fetchRegisterNodes().then(setNodes).catch(() => {}); }, []);

  const fuse = new Fuse(nodes, { keys: ["name", "commander_name"], threshold: 0.4 });
  const searchResults = nodeSearch ? fuse.search(nodeSearch).map(r => r.item) : nodes.slice(0, 20);

  function set<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm(prev => ({ ...prev, [key]: value }));
  }

  async function checkCode() {
    const valid = await validateInviteCode(form.invite_code);
    setCodeValid(valid);
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
        requested_node_id: form.requested_node_id,
        exemption_requests: form.exemption_requests,
        personal_constraints: form.personal_constraints,
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
      };
      setError(detail ? (knownErrors[detail] ?? detail) : t("register.errors.network"));
    } finally {
      setSubmitting(false);
    }
  }

  const selectedNode = nodes.find(n => n.id === form.requested_node_id);

  return (
    <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
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
            {([["personal_number","מספר אישי","text"],["full_name","שם מלא","text"],["phone","טלפון","tel"],
               ["email","אימייל","email"],
               ["enlistment_date","תאריך גיוס","date"],["mandatory_end_date","סיום חובה","date"],
               ["discharge_date","שחרור","date"],["last_mitvahim_date","מטווח אחרון","date"],
               ["last_alal_date","אל\"ל אחרון","date"]] as [keyof FormData, string, string][]).map(([key, label, type]) => (
              <label key={key as string} className="block text-sm">{label}
                <input type={type} className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  value={form[key] as string}
                  onChange={e => set(key, e.target.value)} />
              </label>
            ))}
            <label className="block text-sm">מגדר
              <select className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.gender} onChange={e => set("gender", e.target.value)}>
                <option value="">בחר</option><option value="male">זכר</option><option value="female">נקבה</option>
              </select>
            </label>
            <label className="block text-sm">דרגה
              <select className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.rank} onChange={e => set("rank", e.target.value)}>
                <option value="">בחר</option>
                {ALL_RANKS.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.is_officer} onChange={e => set("is_officer", e.target.checked)} /> קצין
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.bahad1_graduate} onChange={e => set("bahad1_graduate", e.target.checked)} /> {"בוגר בה\"ד 1"}
            </label>
            <label className="block text-sm">סיסמה
              <input type="password" className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.password} onChange={e => set("password", e.target.value)} />
            </label>
            <label className="block text-sm">אימות סיסמה
              <input type="password" className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.confirm_password} onChange={e => set("confirm_password", e.target.value)} />
            </label>
            {form.confirm_password && form.password !== form.confirm_password && (
              <p className="text-red-600 text-sm">הסיסמאות אינן תואמות</p>
            )}
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(1)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={!form.personal_number || !form.full_name || form.password.length < 10 || form.password !== form.confirm_password}
                onClick={() => setStep(3)}>{t("register.next")}</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_exemptions")}</h2>
            {form.exemption_requests.map((er, i) => (
              <div key={i} className="border rounded p-2 space-y-1 text-sm">
                <input placeholder="מזהה סוג פטור (UUID)" className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={er.exemption_type_id}
                  onChange={e => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], exemption_type_id: e.target.value}; set("exemption_requests", rows); }} />
                <input type="date" className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={er.start_date}
                  onChange={e => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], start_date: e.target.value}; set("exemption_requests", rows); }} />
                <input type="date" className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={er.end_date}
                  onChange={e => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], end_date: e.target.value}; set("exemption_requests", rows); }} />
                <input placeholder={t("register.reason")} className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={er.reason}
                  onChange={e => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], reason: e.target.value}; set("exemption_requests", rows); }} />
                <button className="text-red-600 text-xs" onClick={() => set("exemption_requests", form.exemption_requests.filter((_,j) => j !== i))}>{t("register.remove")}</button>
              </div>
            ))}
            <button className="text-indigo-600 dark:text-indigo-400 text-sm"
              onClick={() => set("exemption_requests", [...form.exemption_requests, {exemption_type_id:"",start_date:"",end_date:"",reason:""}])}>
              + {t("register.add_exemption")}
            </button>
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(2)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded" onClick={() => setStep(4)}>{t("register.next")}</button>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_constraints")}</h2>
            {form.personal_constraints.map((pc, i) => (
              <div key={i} className="border rounded p-2 space-y-1 text-sm">
                <input type="date" className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={pc.start_date}
                  onChange={e => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], start_date: e.target.value}; set("personal_constraints", rows); }} />
                <input type="date" className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={pc.end_date}
                  onChange={e => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], end_date: e.target.value}; set("personal_constraints", rows); }} />
                <input placeholder={t("register.reason")} className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={pc.reason}
                  onChange={e => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], reason: e.target.value}; set("personal_constraints", rows); }} />
                <button className="text-red-600 text-xs" onClick={() => set("personal_constraints", form.personal_constraints.filter((_,j) => j !== i))}>{t("register.remove")}</button>
              </div>
            ))}
            <button className="text-indigo-600 dark:text-indigo-400 text-sm"
              onClick={() => set("personal_constraints", [...form.personal_constraints, {start_date:"",end_date:"",reason:""}])}>
              + {t("register.add_constraint")}
            </button>
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(3)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded" onClick={() => setStep(5)}>{t("register.next")}</button>
            </div>
          </div>
        )}

        {step === 5 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_commander")}</h2>
            <input className="block w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" placeholder={t("register.search_commander")}
              value={nodeSearch} onChange={e => setNodeSearch(e.target.value)} />
            <div className="max-h-52 overflow-y-auto border rounded divide-y text-sm">
              {searchResults.length === 0 && <p className="p-2 text-gray-400">{t("register.no_results")}</p>}
              {searchResults.map(n => (
                <button key={n.id}
                  className={`w-full text-right p-2 hover:bg-indigo-50 ${form.requested_node_id === n.id ? "bg-indigo-100 font-semibold" : ""}`}
                  onClick={() => set("requested_node_id", n.id)}>
                  <span>{n.name}</span>
                  {n.commander_name && <span className="text-gray-400 text-xs mr-2">({n.commander_name})</span>}
                  <span className="text-gray-300 text-xs mr-1">{n.level}</span>
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
