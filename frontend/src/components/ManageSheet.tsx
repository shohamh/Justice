import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ManageSheet({ open, onClose }: Props) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const role = user?.role;
  const canManageTeam = role === "duty_manager" || role === "admin" || role === "commander";
  const canManageDuties = role === "duty_manager" || role === "admin";

  if (!open) return null;

  const linkClass = "block px-3 py-2 rounded hover:bg-gray-100 text-sm";
  const sectionHeadClass = "text-xs font-semibold text-gray-400 uppercase mb-1 px-3";

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        data-testid="manage-sheet-backdrop"
        role="presentation"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className="fixed bottom-0 right-0 left-0 md:bottom-0 md:right-24 md:left-auto md:top-0 bg-white z-50 rounded-t-2xl md:rounded-none shadow-xl overflow-y-auto max-h-[70vh] md:max-h-full md:w-64 py-4 space-y-3"
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
      >
        <div className="flex justify-end px-3">
          <button
            autoFocus
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            aria-label="סגור"
          >
            ✕
          </button>
        </div>

        <div>
          <h3 className={sectionHeadClass}>{t("nav.section_personal")}</h3>
          <Link to="/my-requests" onClick={onClose} className={linkClass}>{t("nav.my_requests")}</Link>
          <Link to="/swaps" onClick={onClose} className={linkClass}>{t("nav.swaps")}</Link>
          <Link to="/transparency" onClick={onClose} className={linkClass}>{t("nav.transparency")}</Link>
        </div>

        {canManageTeam && (
          <div>
            <h3 className={sectionHeadClass}>{t("nav.section_team")}</h3>
            <Link to="/team" onClick={onClose} className={linkClass}>{t("nav.team_hierarchy")}</Link>
            <Link to="/unit-calendar" onClick={onClose} className={linkClass}>{t("nav.unit_calendar")}</Link>
            <Link to="/command-dashboard" onClick={onClose} className={linkClass}>{t("nav.command_dashboard")}</Link>
          </div>
        )}

        {canManageDuties && (
          <div>
            <h3 className={sectionHeadClass}>{t("nav.section_planning")}</h3>
            <Link to="/duty-config" onClick={onClose} className={linkClass}>{t("nav.duty_config")}</Link>
            <Link to="/duty-management" onClick={onClose} className={linkClass}>{t("nav.duty_management")}</Link>
            <Link to="/shifts" onClick={onClose} className={linkClass}>{t("nav.shifts")}</Link>
            <Link to="/shift-templates" onClick={onClose} className={linkClass}>{t("nav.shift_templates")}</Link>
          </div>
        )}
      </div>
    </>
  );
}
