import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { generateTelegramCode, getTelegramStatus } from "../api/telegram";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";

export default function TelegramSetupPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refreshMe, telegramRequired } = useAuth();

  const codeQuery = useQuery({ queryKey: queryKeys.telegramLinkCode(), queryFn: generateTelegramCode });
  const codeInfo = codeQuery.data ?? null;

  // Status is only fetched on demand (the "check" button below), not polled —
  // this mirrors the page's original manual-check UX exactly.
  const statusQuery = useQuery({
    queryKey: queryKeys.telegramStatus(),
    queryFn: getTelegramStatus,
    enabled: false,
  });
  const verified = statusQuery.data?.is_verified ?? false;
  const checking = statusQuery.isFetching;

  useEffect(() => {
    if (verified) {
      void refreshMe();
      const timer = setTimeout(() => navigate("/", { replace: true }), 1200);
      return () => clearTimeout(timer);
    }
  }, [verified, navigate, refreshMe]);

  async function checkVerification() {
    await statusQuery.refetch();
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
      <div className="w-full max-w-sm bg-white dark:bg-gray-800 shadow rounded-lg p-6 space-y-4 text-center">
        <h1 className="text-2xl font-bold">{t("telegram_setup.title")}</h1>
        {verified ? (
          <p className="text-green-600 font-semibold">{t("telegram_setup.verified")}</p>
        ) : (
          <>
            <p className="text-sm text-gray-600 dark:text-gray-300">{t("telegram_setup.instructions")}</p>
            {codeInfo && (
              <>
                <div className="bg-gray-100 dark:bg-gray-700 rounded p-3 font-mono text-xl tracking-widest select-all dark:text-gray-100">
                  {codeInfo.code}
                </div>
                {codeInfo.bot_username && (
                  <a href={`https://t.me/${codeInfo.bot_username}`} target="_blank" rel="noreferrer"
                    className="text-indigo-600 dark:text-indigo-300 text-sm underline block">
                    {t("telegram_setup.bot_link")}
                  </a>
                )}
              </>
            )}
            <button className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
              onClick={checkVerification} disabled={checking}>
              {checking ? t("telegram_setup.checking") : t("telegram_setup.check_button")}
            </button>
            {!telegramRequired && (
              <button className="w-full text-gray-400 text-sm py-1"
                onClick={() => navigate("/", { replace: true })}>
                {t("telegram_setup.skip_for_now")}
              </button>
            )}
          </>
        )}
      </div>
    </main>
  );
}
