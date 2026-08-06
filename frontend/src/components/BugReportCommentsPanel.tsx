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
import DocumentPreviewModal from "./DocumentPreviewModal";

export interface BugReportCommentsPanelProps {
  reportId: string;
}

function AttachmentThumbnail({ reportId, commentId, attachmentId, fileName, contentType, onOpen }: {
  reportId: string;
  commentId: string;
  attachmentId: string;
  fileName: string;
  contentType: string;
  onOpen: (url: string, name: string) => void;
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
  const isImage = contentType.startsWith("image/");
  const img = (
    <img
      src={url}
      alt={t("bug_reports.attachment_preview_alt")}
      title={fileName}
      className={`max-w-[160px] max-h-[160px] rounded border dark:border-gray-600 mt-1 ${isImage ? "cursor-zoom-in" : ""}`}
      onClick={isImage ? () => onOpen(url, fileName) : undefined}
    />
  );
  if (isImage) return img;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer">
      {img}
    </a>
  );
}

export default function BugReportCommentsPanel({ reportId }: BugReportCommentsPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [failedUpload, setFailedUpload] = useState<{ commentId: string; file: File } | null>(null);
  const [sending, setSending] = useState(false);
  const [previewImage, setPreviewImage] = useState<{ url: string; name: string; contentType: string } | null>(null);
  const [retryingCommentId, setRetryingCommentId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Mirrors `failedUpload` synchronously so an in-flight retry can tell, after
  // its await resolves, whether it still targets the current failure or has
  // been superseded by a newer one (state read via closure would be stale).
  const failedUploadRef = useRef<{ commentId: string; file: File } | null>(null);
  function updateFailedUpload(value: { commentId: string; file: File } | null) {
    failedUploadRef.current = value;
    setFailedUpload(value);
  }
  // Mirrors `retryingCommentId` synchronously for the same reason as
  // `failedUploadRef` above: lets an in-flight retry's `finally` block tell,
  // after its await resolves, whether it's still the current in-flight
  // retry or has been superseded by a retry for a different comment.
  const retryingCommentIdRef = useRef<string | null>(null);
  function updateRetryingCommentId(value: string | null) {
    retryingCommentIdRef.current = value;
    setRetryingCommentId(value);
  }

  const commentsQuery = useQuery({
    queryKey: queryKeys.bugReportComments(reportId),
    queryFn: () => listComments(reportId),
  });
  const comments = commentsQuery.data ?? [];

  async function handleSend() {
    if (!text.trim() || sending) return;
    setError(null);
    setAttachmentError(null);
    updateFailedUpload(null);
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
      void qc.invalidateQueries({ queryKey: queryKeys.myBugReports() });
      void qc.invalidateQueries({ queryKey: queryKeys.myBugReportsUnseenCount() });

      if (pendingFile) {
        try {
          await uploadCommentAttachment(reportId, comment.id, pendingFile);
          await qc.invalidateQueries({ queryKey: queryKeys.bugReportComments(reportId) });
        } catch {
          setAttachmentError(t("bug_reports.attachment_upload_failed"));
          updateFailedUpload({ commentId: comment.id, file: pendingFile });
        }
      }
    } catch (err: unknown) {
      setError(translateApiError(err, t));
    } finally {
      setSending(false);
    }
  }

  async function handleRetryAttachment() {
    if (!failedUpload || retryingCommentId === failedUpload.commentId) return;
    // Capture the target this retry is for. If a newer failure supersedes it
    // (e.g. a subsequent comment's attachment also fails) while this upload
    // is still in flight, the stale result below must not clobber the newer
    // state.
    const target = failedUpload;
    updateRetryingCommentId(target.commentId);
    try {
      await uploadCommentAttachment(reportId, target.commentId, target.file);
      await qc.invalidateQueries({ queryKey: queryKeys.bugReportComments(reportId) });
      if (failedUploadRef.current?.commentId === target.commentId) {
        setAttachmentError(null);
        updateFailedUpload(null);
      }
    } catch {
      if (failedUploadRef.current?.commentId === target.commentId) {
        setAttachmentError(t("bug_reports.attachment_upload_failed"));
      }
    } finally {
      if (retryingCommentIdRef.current === target.commentId) {
        updateRetryingCommentId(null);
      }
    }
  }

  return (
    <>
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
                contentType={a.content_type}
                onOpen={(url, name) => setPreviewImage({ url, name, contentType: a.content_type })}
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
        {attachmentError && (
          <p className="text-amber-600 text-xs mt-1 flex items-center gap-2">
            {attachmentError}
            {failedUpload && (
              <button
                type="button"
                onClick={() => void handleRetryAttachment()}
                disabled={retryingCommentId === failedUpload.commentId}
                className="underline disabled:opacity-50"
              >
                נסה שוב
              </button>
            )}
          </p>
        )}
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

      {previewImage && (
        <DocumentPreviewModal
          fileUrl={previewImage.url}
          fileName={previewImage.name}
          contentType={previewImage.contentType}
          onClose={() => setPreviewImage(null)}
        />
      )}
    </>
  );
}
