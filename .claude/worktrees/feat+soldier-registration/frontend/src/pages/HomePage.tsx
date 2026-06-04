import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";

export default function HomePage() {
  const { t } = useTranslation();
  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold">{t("home.welcome", { name: "" })}</h2>
        <p className="text-gray-600 mt-2">
          זהו עמוד הבית הראשוני. תכנים אמיתיים יתווספו ב-Slice 2 והלאה.
        </p>
      </section>
    </Layout>
  );
}
