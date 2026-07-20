import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Layout from "../components/Layout";
import { listInviteCodes, createInviteCode, revokeInviteCode } from "../api/inviteCodes";
import { queryKeys } from "../queryKeys";

export function AdminInviteCodesContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const codesQuery = useQuery({ queryKey: queryKeys.inviteCodes(), queryFn: listInviteCodes });
  const codes = codesQuery.data ?? [];
  const [usesLeft, setUsesLeft] = useState(5);

  const createMutation = useMutation({
    mutationFn: createInviteCode,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.inviteCodes() }),
  });
  const revokeMutation = useMutation({
    mutationFn: revokeInviteCode,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.inviteCodes() }),
  });

  const creating = createMutation.isPending;

  function handleCreate() {
    createMutation.mutate(usesLeft);
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
          onClick={handleCreate} disabled={creating}>
          {t("invite_codes.create")}
        </button>
      </div>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b dark:border-gray-700 text-gray-500 dark:text-gray-400 text-right">
            <th className="py-2">קוד</th>
            <th className="py-2">{t("invite_codes.uses_left")}</th>
            <th className="py-2"></th>
          </tr>
        </thead>
        <tbody>
          {codes.map(c => (
            <tr key={c.id} className={`border-b dark:border-gray-700 ${c.uses_left === 0 ? "opacity-40" : ""}`}>
              <td className="py-2 font-mono">{c.code}</td>
              <td className="py-2">{c.uses_left}</td>
              <td className="py-2">
                <button className="text-red-600 text-xs hover:underline"
                  onClick={() => revokeMutation.mutate(c.id)}>
                  {t("invite_codes.revoke")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function AdminInviteCodesPage() {
  return <Layout><AdminInviteCodesContent /></Layout>;
}
