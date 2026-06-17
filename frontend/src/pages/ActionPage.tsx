import { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api as client } from "../api/client";

export default function ActionPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<"pending" | "success" | "error">("pending");

  useEffect(() => {
    const token = searchParams.get("token");
    if (!token) {
      setStatus("error");
      return;
    }
    client.post("/action", { token })
      .then((r) => {
        setStatus("success");
        const action: string = r.data?.action ?? "";
        // Navigate to the relevant section after a short delay
        const path =
          action.startsWith("constraint") ? "/constraints" :
          action.startsWith("exemption") ? "/exemption-requests" :
          action.startsWith("swap") ? "/swaps" : "/notifications";
        setTimeout(() => navigate(path), 1500);
      })
      .catch(() => {
        setStatus("error");
      });
  }, [navigate, searchParams]);

  return (
    <main className="min-h-screen flex items-center justify-center p-6 dark:bg-gray-900" dir="rtl">
      <div className="w-full max-w-sm bg-white dark:bg-gray-800 shadow rounded-lg p-8 text-center">
        {status === "pending" && <p className="text-gray-500">{t("action.processing")}</p>}
        {status === "success" && <p className="text-green-600 text-lg">✅ {t("action.success")}</p>}
        {status === "error" && (
          <p className="text-red-600 text-lg">❌ {t("action.error")}</p>
        )}
      </div>
    </main>
  );
}
