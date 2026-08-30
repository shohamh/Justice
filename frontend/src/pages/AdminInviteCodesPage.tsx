import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ClipboardCopy } from "lucide-react";
import Layout from "../components/Layout";
import { listInviteCodes, createInviteCode, revokeInviteCode } from "../api/inviteCodes";
import { queryKeys } from "../queryKeys";

export function AdminInviteCodesContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const codesQuery = useQuery({ queryKey: queryKeys.inviteCodes(), queryFn: listInviteCodes });
  const hasInvalidResponse = codesQuery.data !== undefined && !Array.isArray(codesQuery.data);
  const codes = hasInvalidResponse ? [] : (codesQuery.data ?? []);
  const [usesLeft, setUsesLeft] = useState(5);
  const [copyState, setCopyState] = useState<Record<string, "copied" | "error">>({});

  const createMutation = useMutation({
    mutationFn: createInviteCode,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.inviteCodes() }),
  });
  const revokeMutation = useMutation({
    mutationFn: revokeInviteCode,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.inviteCodes() }),
  });

  async function handleCopy(codeId: string, code: string) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(code);
      setCopyState(state => ({ ...state, [codeId]: "copied" }));
      window.setTimeout(() => {
        setCopyState(state => {
          if (state[codeId] !== "copied") return state;
          const next = { ...state };
          delete next[codeId];
          return next;
        });
      }, 2000);
    } catch {
      setCopyState(state => ({ ...state, [codeId]: "error" }));
    }
  }

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl">
      <h2 className="text-xl font-semibold dark:text-gray-100">{t("invite_codes.title")}</h2>
      <div className="flex gap-2 items-end">
        <label className="text-sm dark:text-gray-300">{t("invite_codes.uses_left_label")}
          <input type="number" min={1} className="mt-1 block w-24 border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={usesLeft} onChange={e => setUsesLeft(Number(e.target.value))} />
        </label>
        <button className="bg-indigo-600 text-white px-4 py-2 rounded disabled:opacity-50"
          onClick={() => createMutation.mutate(usesLeft)} disabled={createMutation.isPending}>
          {t("invite_codes.create")}
        </button>
      </div>
      {(codesQuery.isError || hasInvalidResponse) && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {t("invite_codes.load_error", "שגיאה בטעינת קודי ההזמנה")}
        </p>
      )}
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b dark:border-gray-700 text-gray-500 dark:text-gray-400 text-right">
            <th className="py-2">{t("invite_codes.code", "קוד")}</th>
            <th className="py-2">{t("invite_codes.uses_left")}</th>
            <th className="py-2"></th>
          </tr>
        </thead>
        <tbody>
          {codes.map(c => {
            const copied = copyState[c.id] === "copied";
            return (
              <tr key={c.id} className={`border-b dark:border-gray-700 ${c.uses_left === 0 ? "opacity-40" : ""}`}>
                <td className="py-2 font-mono">
                  <span className="inline-flex items-center gap-2">
                    <span>{c.code}</span>
                    <button
                      type="button"
                      className="p-1 rounded text-indigo-600 hover:bg-indigo-50 dark:hover:bg-gray-700"
                      aria-label={copied ? "הועתק" : "העתק"}
                      title={copied ? "הועתק" : "העתק"}
                      data-testid={`invite-code-copy-${c.id}`}
                      onClick={() => handleCopy(c.id, c.code)}
                    >
                      {copied ? (
                        <Check className="h-4 w-4 text-green-600" aria-hidden="true" data-testid={`invite-code-copy-success-${c.id}`} />
                      ) : (
                        <ClipboardCopy className="h-4 w-4" aria-hidden="true" />
                      )}
                    </button>
                    {copyState[c.id] === "error" && <span className="text-red-600 text-xs">לא ניתן להעתיק — נסה שוב</span>}
                  </span>
                </td>
                <td className="py-2">{c.uses_left}</td>
                <td className="py-2">
                  <button className="text-red-600 text-xs hover:underline"
                    onClick={() => revokeMutation.mutate(c.id)}>
                    {t("invite_codes.revoke")}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

export default function AdminInviteCodesPage() {
  return <Layout><AdminInviteCodesContent /></Layout>;
}
