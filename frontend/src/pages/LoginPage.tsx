import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AxiosError } from "axios";

import { fetchOidcStatus, startSsoLogin } from "../api/auth";
import { useAuth } from "../auth/AuthContext";
import { safeInternalReturnPath } from "../auth/returnPath";
import { readAuthReturnPath, storeAuthReturnPath } from "../auth/returnPathStorage";
import JusticeLogo from "../components/JusticeLogo";
import PasswordInput from "../components/PasswordInput";

type ErrKey = "invalid_credentials" | "network" | "rate_limited" | null;

export default function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const routeState = location.state;
  const resetSuccess =
    routeState && typeof routeState === "object" && "resetSuccess" in routeState
      ? routeState.resetSuccess === true
      : false;
  const hasRouterReturnTo = Boolean(routeState && typeof routeState === "object" && "from" in routeState);
  const returnTo = hasRouterReturnTo
    ? safeInternalReturnPath((routeState as { from?: unknown }).from)
    : readAuthReturnPath();

  const [searchParams] = useSearchParams();
  // The callback only ever sends the bare flag; nothing else from the URL is read or shown.
  const ssoFailed = searchParams.get("sso_error") === "1";
  const [ssoEnabled, setSsoEnabled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchOidcStatus().then((enabled) => { if (!cancelled) setSsoEnabled(enabled === true); });
    return () => { cancelled = true; };
  }, []);

  const [personalNumber, setPersonalNumber] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [errorKey, setErrorKey] = useState<ErrKey>(null);
  const [retryAfterSeconds, setRetryAfterSeconds] = useState<string | null>(null);
  const [attempts, setAttempts] = useState<{ n: number; max: number } | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErrorKey(null);
    setAttempts(null);
    setSubmitting(true);
    try {
      await login(personalNumber, password, rememberMe);
      storeAuthReturnPath(returnTo);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof AxiosError) {
        if (err.response?.status === 401) {
          setErrorKey("invalid_credentials");
          const d = err.response.data?.detail;
          if (d && typeof d === "object" && "attempts" in d) {
            setAttempts({ n: d.attempts, max: d.max_attempts });
          }
        } else if (err.response?.status === 429) {
          setErrorKey("rate_limited");
          setRetryAfterSeconds(err.response.headers["retry-after"] ?? null);
        } else if (err.response && err.response.status >= 400 && err.response.status < 500) {
          setErrorKey("invalid_credentials");
        } else {
          setErrorKey("network");
        }
      } else {
        setErrorKey("network");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="h-[100dvh] overflow-y-auto flex flex-col items-center justify-center p-6 gap-8 dark:bg-gray-900">
      <JusticeLogo size="lg" />
      <form onSubmit={onSubmit} className="w-full max-w-sm bg-white shadow rounded-lg p-6 space-y-4 dark:bg-gray-800" data-testid="login-form">
        <h1 className="text-2xl font-bold text-center dark:text-gray-100">{t("login.title")}</h1>

        {resetSuccess && (
          <div className="text-green-700 text-sm bg-green-50 rounded p-2 text-center">
            {t("reset_password.success")}
          </div>
        )}

        <label className="block">
          <span className="text-sm font-medium dark:text-gray-100">{t("login.personal_number_label")}</span>
          <input
            type="text"
            inputMode="numeric"
            autoComplete="username"
            required
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200 p-2 border dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            value={personalNumber}
            onChange={(e) => setPersonalNumber(e.target.value)}
            data-testid="personal-number-input"
            placeholder={t("login.personal_number_placeholder")}
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium dark:text-gray-100">{t("login.password_label")}</span>
          <PasswordInput
            autoComplete="current-password"
            required
            dir="ltr"
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200 p-2 border dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="password-input"
          />
        </label>

        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none" dir="rtl">
          <input
            type="checkbox"
            checked={rememberMe}
            onChange={(e) => setRememberMe(e.target.checked)}
            className="rounded"
            data-testid="remember-me-checkbox"
          />
          {t("login.remember_me")}
        </label>

        {ssoFailed && (
          <div className="text-rejected text-sm" role="alert" data-testid="sso-error">
            {t("login.errors.sso_failed")}
          </div>
        )}

        {errorKey && (
          <div className="text-rejected text-sm" data-testid="login-error">
            {errorKey === "rate_limited" && retryAfterSeconds
              ? t("login.errors.rate_limited", { seconds: retryAfterSeconds })
              : t(`login.errors.${errorKey}`)}
            {errorKey === "invalid_credentials" && attempts && (
              <div>{t("login.errors.attempts_remaining", { n: attempts.n, max: attempts.max })}</div>
            )}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium py-2 rounded-md"
          data-testid="login-submit"
        >
          {submitting ? t("login.submitting") : t("login.submit")}
        </button>

        {ssoEnabled && (
          <button
            type="button"
            onClick={() => {
              storeAuthReturnPath(returnTo);
              startSsoLogin();
            }}
            className="w-full border border-indigo-600 text-indigo-600 dark:text-indigo-300 dark:border-indigo-300 hover:bg-indigo-50 dark:hover:bg-gray-700 font-medium py-2 rounded-md"
            data-testid="sso-login-button"
          >
            {t("login.sso_button")}
          </button>
        )}

        <p className="text-center text-sm text-gray-500 mt-2">
          <a href="/register" className="text-indigo-600 dark:text-indigo-300 hover:underline">
            {t("register.signup_button")}
          </a>
        </p>
        <p className="text-center text-sm text-gray-500">
          <a href="/forgot-password" className="text-indigo-600 dark:text-indigo-300 hover:underline">
            {t("forgot_password.link_label")}
          </a>
        </p>
      </form>
    </main>
  );
}
