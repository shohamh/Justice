import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AxiosError } from "axios";

import { useAuth } from "../auth/AuthContext";
import PasswordStrengthHint, { passwordValid } from "../components/PasswordStrengthHint";
import PasswordInput from "../components/PasswordInput";

export default function ChangePasswordPage() {
  const { t } = useTranslation();
  const { changePassword, mustChangePassword } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await changePassword(current, next);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof AxiosError && err.response?.status === 400) {
        const detail = (err.response.data as { detail?: string })?.detail;
        setError(detail === "password_too_short" ? t("change_password.min_length") : t("change_password.wrong_current"));
      } else {
        setError(t("change_password.wrong_current"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="h-[100dvh] overflow-y-auto flex items-center justify-center p-6">
      <form onSubmit={onSubmit} className="w-full max-w-sm bg-white dark:bg-gray-800 shadow rounded-lg p-6 space-y-4" data-testid="change-password-form">
        <h1 className="text-2xl font-bold text-center">{t("change_password.title")}</h1>
        {mustChangePassword && (
          <div className="bg-pending/10 border border-pending/30 text-pending px-3 py-2 text-sm rounded" data-testid="forced-notice">
            {t("change_password.forced_notice")}
          </div>
        )}
        <label className="block">
          <span className="text-sm font-medium">{t("change_password.current")}</span>
          <PasswordInput required dir="ltr" className="mt-1 block w-full rounded-md border p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={current}
                 onChange={(e) => setCurrent(e.target.value)} data-testid="current-password" />
        </label>
        <label className="block">
          <span className="text-sm font-medium">{t("change_password.new")}</span>
          <PasswordInput required dir="ltr" className="mt-1 block w-full rounded-md border p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={next}
                 onChange={(e) => setNext(e.target.value)} data-testid="new-password" />
          <PasswordStrengthHint password={next} />
        </label>
        {error && <div className="text-rejected text-sm" data-testid="change-password-error">{error}</div>}
        <button type="submit" disabled={submitting || !passwordValid(next)}
                className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium py-2 rounded-md"
                data-testid="change-password-submit">
          {t("change_password.submit")}
        </button>
      </form>
    </main>
  );
}
