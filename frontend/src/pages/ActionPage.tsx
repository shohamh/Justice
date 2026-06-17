import { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api as client } from "../api/client";
import Layout from "../components/Layout";

export default function ActionPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<"pending" | "success" | "error">("pending");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const token = searchParams.get("token");
    if (!token) {
      setStatus("error");
      setErrorMsg("missing token");
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
      .catch((err) => {
        setStatus("error");
        setErrorMsg(err?.response?.data?.detail ?? "error");
      });
  }, [navigate, searchParams]);

  return (
    <Layout>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-8 text-center">
        {status === "pending" && <p className="text-gray-500">{t("action.processing")}</p>}
        {status === "success" && <p className="text-green-600 text-lg">✅ {t("action.success")}</p>}
        {status === "error" && (
          <div>
            <p className="text-red-600 text-lg">❌ {t("action.error")}</p>
            {errorMsg && <p className="text-sm text-gray-500 mt-2">{errorMsg}</p>}
          </div>
        )}
      </div>
    </Layout>
  );
}
