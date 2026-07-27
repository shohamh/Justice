import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Layout from "../components/Layout";
import HierarchyNodePickerModal from "../components/HierarchyNodePickerModal";
import HierarchyCheckboxTree from "../components/HierarchyCheckboxTree";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";
import { translateApiError } from "../utils/translateApiError";
import {
  getAnnounceScope,
  postAnnouncement,
  listAnnouncements,
  getAnnouncementRecipients,
} from "../api/announcements";

export default function AnnouncementsPage() {
  const { user } = useAuth();
  const canAnnounce = user?.role === "admin" || user?.is_commander || user?.is_duty_manager;
  if (!canAnnounce) return <Navigate to="/" replace />;
  return <AnnouncementsContent />;
}

function AnnouncementsContent() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = user?.role === "admin";

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [narrowNodeIds, setNarrowNodeIds] = useState<string[]>([]);
  const [narrowNames, setNarrowNames] = useState<Record<string, string>>({});
  const [pickerOpen, setPickerOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const limit = 20;

  const scopeQuery = useQuery({
    queryKey: queryKeys.announceScope(),
    queryFn: getAnnounceScope,
    enabled: !isAdmin,
  });
  const scopeNodes = scopeQuery.data ?? [];

  const [selectedScopeIds, setSelectedScopeIds] = useState<Set<string> | null>(null);

  useEffect(() => {
    if (scopeQuery.data && selectedScopeIds === null) {
      const nodeIds = new Set(scopeQuery.data.map((n) => n.id));
      const rootIds = scopeQuery.data
        .filter((n) => n.parent_id === null || !nodeIds.has(n.parent_id))
        .map((n) => n.id);
      setSelectedScopeIds(new Set(rootIds));
    }
  }, [scopeQuery.data, selectedScopeIds]);

  const historyQuery = useQuery({
    queryKey: queryKeys.announcementsList(offset),
    queryFn: () => listAnnouncements({ offset, limit }),
  });
  const history = historyQuery.data?.items ?? [];
  const total = historyQuery.data?.total ?? 0;

  const recipientsQuery = useQuery({
    queryKey: queryKeys.announcementRecipients(expandedId ?? ""),
    queryFn: () => getAnnouncementRecipients(expandedId as string),
    enabled: expandedId !== null,
  });

  async function handleSubmit() {
    setSubmitting(true);
    setSuccessMsg(null);
    setErrorMsg(null);
    try {
      const hierarchy_node_ids = isAdmin
        ? (narrowNodeIds.length > 0 ? narrowNodeIds : undefined)
        : (selectedScopeIds && selectedScopeIds.size > 0 ? Array.from(selectedScopeIds) : undefined);
      await postAnnouncement({ title, body: body || undefined, hierarchy_node_ids });
      setSuccessMsg(t("announcements.sent_success"));
      setTitle("");
      setBody("");
      setNarrowNodeIds([]);
      setNarrowNames({});
      setOffset(0);
      await queryClient.invalidateQueries({ queryKey: ["notifications", "announcements"] });
    } catch (err) {
      setErrorMsg(translateApiError(err, t, t("announcements.send_error")));
    } finally {
      setSubmitting(false);
    }
  }

  function handleRemoveNarrow(id: string) {
    setNarrowNodeIds((prev) => prev.filter((n) => n !== id));
    setNarrowNames((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  function handlePicked(nodeId: string, nodeName: string) {
    setNarrowNodeIds((prev) => (prev.includes(nodeId) ? prev : [...prev, nodeId]));
    setNarrowNames((prev) => ({ ...prev, [nodeId]: nodeName }));
    setPickerOpen(false);
  }

  const pages = Math.ceil(total / limit);
  const typeIcon = (type: string) => (type === "system_announcement" ? "📣" : "📢");

  return (
    <Layout>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mb-6">
        <h2 className="text-xl font-semibold mb-4">{t("announcements.compose_title")}</h2>
        <div className="space-y-3">
          <div>
            <label htmlFor="announcement-title" className="block text-sm text-gray-600 dark:text-gray-300 mb-1">
              {t("announcements.field_title")}
            </label>
            <input
              id="announcement-title"
              aria-label={t("announcements.field_title")}
              className="border rounded p-2 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="announcement-body" className="block text-sm text-gray-600 dark:text-gray-300 mb-1">
              {t("announcements.field_body")}
            </label>
            <textarea
              id="announcement-body"
              aria-label={t("announcements.field_body")}
              className="border rounded p-2 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </div>

          <div>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-1">{t("announcements.target_label")}</p>
            {isAdmin ? (
              <div className="space-y-2">
                <p className="text-sm">
                  {narrowNodeIds.length === 0 ? t("announcements.target_everyone") : Object.values(narrowNames).join(", ")}
                </p>
                <button
                  type="button"
                  className="text-xs text-indigo-600 hover:underline"
                  onClick={() => setPickerOpen(true)}
                >
                  {t("announcements.target_narrow")}
                </button>
                {narrowNodeIds.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className="ms-2 text-xs text-red-500 hover:underline"
                    onClick={() => handleRemoveNarrow(id)}
                  >
                    {narrowNames[id]} ✕
                  </button>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-sm">{t("announcements.target_my_scope")}</p>
                {scopeNodes.length > 0 && (
                  <HierarchyCheckboxTree
                    nodes={scopeNodes}
                    selectedIds={selectedScopeIds ?? new Set()}
                    onChange={setSelectedScopeIds}
                  />
                )}
              </div>
            )}
          </div>

          {successMsg && <p className="text-sm text-green-600">{successMsg}</p>}
          {errorMsg && <p className="text-sm text-red-600">{errorMsg}</p>}

          <button
            type="button"
            disabled={submitting || !title.trim() || (!isAdmin && scopeQuery.isLoading)}
            onClick={handleSubmit}
            className="bg-indigo-600 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
          >
            {submitting ? t("announcements.submitting") : t("announcements.submit")}
          </button>
        </div>
      </div>

      {pickerOpen && (
        <HierarchyNodePickerModal
          onClose={() => setPickerOpen(false)}
          onPicked={handlePicked}
        />
      )}

      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold mb-4">{t("announcements.history_title")}</h2>
        {history.length === 0 ? (
          <p className="text-gray-500">{t("announcements.no_history")}</p>
        ) : (
          <div className="space-y-2">
            {history.map((a) => (
              <div key={a.id} className="border dark:border-gray-600 rounded p-3">
                <div className="flex items-start gap-2">
                  <span className="text-lg">{typeIcon(a.type)}</span>
                  <div className="flex-1">
                    <p className="font-medium">{a.title}</p>
                    {a.body && <p className="text-sm text-gray-500 dark:text-gray-400">{a.body}</p>}
                    <p className="text-xs text-gray-400 mt-1">
                      {t("announcements.read_count", { read: a.read_count, total: a.recipient_count })}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="text-xs text-indigo-600 hover:underline"
                    onClick={() => setExpandedId(expandedId === a.id ? null : a.id)}
                  >
                    {expandedId === a.id ? t("announcements.hide_recipients") : t("announcements.view_recipients")}
                  </button>
                </div>
                {expandedId === a.id && (
                  <div className="mt-2 ps-8 space-y-1">
                    {(recipientsQuery.data?.items ?? []).map((r) => (
                      <div key={r.soldier_id} className="text-sm flex justify-between">
                        <span>{r.full_name}</span>
                        <span className={r.is_read ? "text-green-600" : "text-gray-400"}>
                          {r.is_read ? t("announcements.recipient_read") : t("announcements.recipient_unread")}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {pages > 1 && (
          <div className="flex justify-center gap-2 mt-4">
            {Array.from({ length: pages }, (_, i) => (
              <button
                key={i}
                onClick={() => setOffset(i * limit)}
                className={`px-3 py-1 rounded text-sm ${offset === i * limit ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-700 dark:text-gray-300"}`}
              >
                {i + 1}
              </button>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
