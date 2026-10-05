import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api as client } from "../api/client";

export default function ActionPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const [token] = useState(() => new URLSearchParams(location.search).get("token") ?? "");
  const submitted = useRef(false);
  const [status, setStatus] = useState<"pending" | "success" | "error">("pending");

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (!params.has("token") && !location.hash) return;
    params.delete("token");
    const search = params.toString();
    navigate({ pathname: location.pathname, search: search ? `?${search}` : "", hash: "" }, { replace: true, state: location.state });
  }, [location.pathname, location.search, location.hash, location.state, navigate]);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      return;
    }
    if (submitted.current) return;
    submitted.current = true;
    client.post("/action", { token })
      .then((r) => {
        setStatus("success");
        const action: string = r.data?.action ?? "";
        // Navigate to the relevant section after a short delay
        const path =
          action.startsWith("constraint") ? "/approvals?tab=constraints" :
          action.startsWith("exemption") ? "/approvals?tab=exemptions" :
          action.startsWith("swap") ? "/swaps" : "/notifications";
        setTimeout(() => navigate(path), 1500);
      })
      .catch(() => {
        setStatus("error");
      });
  }, [navigate, token]);

  return (
    <main className="h-[100dvh] overflow-y-auto flex items-center justify-center p-6 dark:bg-gray-900" dir="rtl">
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
