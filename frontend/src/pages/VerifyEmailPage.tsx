import { useEffect, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { isAxiosError } from "axios";
import { verifyEmail } from "../api/auth";

export default function VerifyEmailPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [errorKey, setErrorKey] = useState<string>("");

  useEffect(() => {
    if (!token) { setStatus("error"); setErrorKey("token_invalid"); return; }
    verifyEmail(token)
      .then(() => setStatus("ok"))
      .catch((err: unknown) => {
        const detail = isAxiosError(err) ? (err.response?.data?.detail as string | undefined) : undefined;
        setErrorKey(detail ?? "token_invalid");
        setStatus("error");
      });
  }, [token]);

  return (
    <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
      <div className="w-full max-w-sm bg-white shadow rounded-lg p-6 space-y-4 text-center">
        <h1 className="text-2xl font-bold">{t("verify_email.title")}</h1>
        {status === "loading" && <p className="text-gray-500">{t("app.loading")}</p>}
        {status === "ok" && (
          <>
            <p className="text-green-700">{t("verify_email.success")}</p>
            <Link to="/" className="text-indigo-600 hover:underline text-sm">{t("verify_email.go_home")}</Link>
          </>
        )}
        {status === "error" && (
          <>
            <p className="text-red-600">
              {t(`verify_email.errors.${errorKey}`, { defaultValue: t("verify_email.errors.token_invalid") })}
            </p>
            <Link to="/profile" className="text-indigo-600 hover:underline text-sm">{t("verify_email.go_profile")}</Link>
          </>
        )}
      </div>
    </main>
  );
}
