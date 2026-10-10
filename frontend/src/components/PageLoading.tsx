import { useTranslation } from "react-i18next";

export default function PageLoading() {
  const { t } = useTranslation();
  return (
    <div
      data-testid="page-loading"
      role="status"
      aria-live="polite"
      style={{ padding: "2rem", textAlign: "center" }}
    >
      {t("app.loading")}
    </div>
  );
}

