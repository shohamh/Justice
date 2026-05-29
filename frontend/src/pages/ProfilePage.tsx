import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import ExemptionsPanel from "../components/ExemptionsPanel";
import { useAuth } from "../auth/AuthContext";

export default function ProfilePage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-3">
        <h2 className="text-xl font-semibold">{t("profile.title")}</h2>
        <p>{t("team.full_name")}: {user?.full_name}</p>
        <p>{t("team.personal_number")}: {user?.personal_number}</p>
        <p>{t("team.role")}: {user?.role}</p>
        <Link to="/change-password" className="text-indigo-600 hover:text-indigo-800" data-testid="profile-change-password">
          {t("profile.change_password")}
        </Link>
        {user?.id && (
          <div className="pt-4 border-t">
            <ExemptionsPanel soldierId={user.id} canManage={false} />
          </div>
        )}
      </section>
    </Layout>
  );
}
