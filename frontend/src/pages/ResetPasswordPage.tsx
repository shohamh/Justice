import { useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { isAxiosError } from "axios";
import { resetPassword } from "../api/auth";

export default function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mismatch = confirm.length > 0 && password !== confirm;

  async function handleSubmit() {
    if (password !== confirm) {
      setError(t("reset_password.errors.passwords_mismatch"));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await resetPassword(token, password);
      navigate("/login", { state: { resetSuccess: true }, replace: true });
    } catch (err) {
      const detail = isAxiosError(err) ? (err.response?.data?.detail as string | undefined) : undefined;
      const known: Record<string, string> = {
        token_invalid: t("reset_password.errors.token_invalid"),
        token_expired: t("reset_password.errors.token_expired"),
        password_too_short: t("reset_password.errors.password_too_short"),
      };
      setError(detail ? (known[detail] ?? detail) : t("login.errors.network"));
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
        <div className="text-center space-y-3">
          <p className="text-red-600">{t("reset_password.errors.token_invalid")}</p>
          <Link to="/forgot-password" className="text-indigo-600 dark:text-indigo-300 hover:underline text-sm">
            {t("forgot_password.title")}
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
      <div className="w-full max-w-sm bg-white dark:bg-gray-800 shadow rounded-lg p-6 space-y-4">
        <h1 className="text-2xl font-bold text-center">{t("reset_password.title")}</h1>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        <label className="block text-sm">
          {t("reset_password.new_password")}
          <input
            type="password"
            className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={password}
            onChange={e => setPassword(e.target.value)}
          />
        </label>

        <label className="block text-sm">
          {t("reset_password.confirm")}
          <input
            type="password"
            className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
          />
        </label>

        {mismatch && (
          <p className="text-red-500 text-xs">{t("reset_password.errors.passwords_mismatch")}</p>
        )}

        <button
          onClick={handleSubmit}
          disabled={submitting || !password || mismatch}
          className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
        >
          {submitting ? t("reset_password.submitting") : t("reset_password.submit")}
        </button>

        <p className="text-center text-sm text-gray-500">
          <Link to="/forgot-password" className="text-indigo-600 dark:text-indigo-300 hover:underline">
            {t("forgot_password.title")}
          </Link>
        </p>
      </div>
    </main>
  );
}
