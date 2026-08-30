import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { checkForgotPasswordChannels, sendForgotPassword } from "../api/auth";

type Step = "input" | "choose" | "sent";

export default function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>("input");
  const [personalNumber, setPersonalNumber] = useState("");
  const [channels, setChannels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCheck() {
    setLoading(true);
    setError(null);
    try {
      const ch = await checkForgotPasswordChannels(personalNumber);
      // checkForgotPasswordChannels can only reject the request outright (see
      // catch below); it does not itself guarantee an array shape for a
      // malformed-but-200 response, so guard defensively before setState —
      // channels.map() below would otherwise crash on a non-array value.
      setChannels(Array.isArray(ch) ? ch : []);
      setStep("choose");
    } catch {
      setError(t("login.errors.network"));
    } finally {
      setLoading(false);
    }
  }

  async function handleSend(channel: string) {
    setLoading(true);
    setError(null);
    try {
      await sendForgotPassword(personalNumber, channel);
      setStep("sent");
    } catch {
      setError(t("login.errors.network"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="h-[100dvh] overflow-y-auto flex items-center justify-center p-6 dark:bg-gray-900" dir="rtl">
      <div className="w-full max-w-sm bg-white dark:bg-gray-800 shadow rounded-lg p-6 space-y-4">
        <h1 className="text-2xl font-bold text-center">{t("forgot_password.title")}</h1>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        {step === "input" && (
          <div className="space-y-3">
            <label className="block text-sm">
              {t("forgot_password.personal_number_label")}
              <input
                type="text"
                inputMode="numeric"
                className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={personalNumber}
                onChange={e => setPersonalNumber(e.target.value)}
              />
            </label>
            <button
              onClick={handleCheck}
              disabled={loading || !personalNumber}
              className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
            >
              {loading ? "..." : t("forgot_password.continue")}
            </button>
          </div>
        )}

        {step === "choose" && (
          <div className="space-y-3">
            {channels.length === 0 ? (
              <p className="text-sm text-gray-600">{t("forgot_password.no_channels")}</p>
            ) : (
              channels.map(ch => (
                <button
                  key={ch}
                  onClick={() => handleSend(ch)}
                  disabled={loading}
                  className="w-full border border-indigo-600 text-indigo-600 py-2 rounded hover:bg-indigo-50 disabled:opacity-50"
                >
                  {ch === "telegram" ? t("forgot_password.send_telegram") : t("forgot_password.send_email")}
                </button>
              ))
            )}
          </div>
        )}

        {step === "sent" && (
          <p className="text-green-700 text-sm text-center">{t("forgot_password.sent")}</p>
        )}

        <p className="text-center text-sm text-gray-500">
          <Link to="/login" className="text-indigo-600 dark:text-indigo-300 hover:underline">
            {t("forgot_password.back_to_login")}
          </Link>
        </p>
      </div>
    </main>
  );
}
