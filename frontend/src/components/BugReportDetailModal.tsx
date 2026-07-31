import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../queryKeys";
import {
  listComments,
  createComment,
  uploadCommentAttachment,
  bugReportCommentAttachmentDownloadUrl,
  BugReportComment,
} from "../api/bugReports";
import { translateApiError } from "../utils/translateApiError";

interface Props {
  reportId: string;
  onClose: () => void;
}

function AttachmentThumbnail({ reportId, commentId, attachmentId, fileName }: {
  reportId: string;
  commentId: string;
  attachmentId: string;
  fileName: string;
}) {
  const { t } = useTranslation();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setFailed(false);
    api
      .get(bugReportCommentAttachmentDownloadUrl(reportId, commentId, attachmentId), { responseType: "blob" })
      .then((res) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(res.data as Blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [reportId, commentId, attachmentId]);

  if (failed) {
    return (
      <div
        data-testid="attachment-thumbnail-fallback"
        className="w-16 h-16 flex items-center justify-center rounded border border-dashed border-gray-300 dark:border-gray-600 text-gray-400 text-xs"
        title={fileName}
      >
        ⚠
      </div>
    );
  }
  if (!url) return null;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer">
      <img
        src={url}
        alt={t("bug_reports.attachment_preview_alt")}
        title={fileName}
        className="max-w-[160px] max-h-[160px] rounded border dark:border-gray-600 mt-1"
      />
    </a>
  );
}

export default function BugReportDetailModal({ reportId, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const commentsQuery = useQuery({
    queryKey: queryKeys.bugReportComments(reportId),
    queryFn: () => listComments(reportId),
  });
  const comments = commentsQuery.data ?? [];

  async function handleSend() {
    if (!text.trim() || sending) return;
    setError(null);
    setAttachmentError(null);
    setSending(true);
    const pendingFile = file;
    try {
      const comment = await createComment(reportId, text.trim());
      // The comment is now saved server-side — reset the draft and refresh the
      // list immediately so the UI never implies the comment itself was lost,
      // even if the attachment upload below fails.
      setText("");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await qc.invalidateQueries({ queryKey: queryKeys.bugReportComments(reportId) });

      if (pendingFile) {
        try {
          await uploadCommentAttachment(reportId, comment.id, pendingFile);
          await qc.invalidateQueries({ queryKey: queryKeys.bugReportComments(reportId) });
        } catch {
          setAttachmentError(t("bug_reports.attachment_upload_failed"));
        }
      }
    } catch (err: unknown) {
      setError(translateApiError(err, t));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b dark:border-gray-600 flex justify-between items-center">
          <h3 className="font-semibold">{t("bug_reports.comments_title")}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label={t("bug_reports.close")}>
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {commentsQuery.isLoading && <p className="text-sm text-gray-500">{t("app.loading")}</p>}
          {commentsQuery.isError && (
            <p className="text-sm text-red-500">{translateApiError(commentsQuery.error, t)}</p>
          )}
          {!commentsQuery.isLoading && comments.length === 0 && (
            <p className="text-sm text-gray-500">{t("bug_reports.no_comments")}</p>
          )}
          {comments.map((c: BugReportComment) => (
            <div key={c.id} className="border rounded p-2 text-sm dark:border-gray-600">
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>{c.author_name}</span>
                <span dir="ltr">{new Date(c.created_at).toLocaleString("he-IL")}</span>
              </div>
              <p className="whitespace-pre-wrap">{c.body}</p>
              {c.attachments.map((a) => (
                <AttachmentThumbnail
                  key={a.id}
                  reportId={reportId}
                  commentId={c.id}
                  attachmentId={a.id}
                  fileName={a.file_name}
                />
              ))}
            </div>
          ))}
        </div>
        <div className="p-4 border-t dark:border-gray-600 space-y-2">
          <textarea
            className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
            rows={3}
            placeholder={t("bug_reports.comment_placeholder")}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 dark:text-gray-400">{t("bug_reports.attachment_label")}</label>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/gif"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-xs"
            />
          </div>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          {attachmentError && <p className="text-amber-600 text-xs">{attachmentError}</p>}
          <div className="flex justify-end">
            <button
              className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
              disabled={!text.trim() || sending}
              onClick={() => void handleSend()}
            >
              {sending ? t("bug_reports.sending") : t("bug_reports.send")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
