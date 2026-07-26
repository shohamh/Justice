import { authenticated, canApprove, canPlan, isAdmin, PermissionUser } from "./auth/permissions";

export type SearchUser = PermissionUser;

export interface PageEntry {
  id: string;
  labelKey: string;
  keywords: string[];
  descriptionKey?: string;
  path: string;
  canAccess: (user: SearchUser | null) => boolean;
}

export interface QuickActionEntry {
  id: string;
  labelKey: string;
  keywords: string[];
  path: string;
  canAccess: (user: SearchUser | null) => boolean;
}

export interface HelpTopicEntry {
  id: string;
  labelKey: string;
  keywords: string[];
  canAccess: (user: SearchUser | null) => boolean;
}

export function getPageEntries(): PageEntry[] {
  return [
    { id: "page-home", labelKey: "search.pages.home", keywords: ["ראשי"], path: "/", canAccess: authenticated },
    { id: "page-team", labelKey: "search.pages.team", keywords: ["אנשי צוות והיררכיה"], path: "/team", canAccess: authenticated },
    { id: "page-transparency", labelKey: "search.pages.transparency", keywords: ["שקיפות"], path: "/transparency", canAccess: authenticated },
    { id: "page-my-duties", labelKey: "search.pages.my_duties", keywords: ["התורנויות שלי"], path: "/my-duties", canAccess: authenticated },
    { id: "page-my-requests", labelKey: "search.pages.my_requests", keywords: ["הבקשות שלי"], path: "/my-requests", canAccess: authenticated },
    { id: "page-approvals", labelKey: "search.pages.approvals", keywords: ["אישורים"], path: "/approvals", canAccess: canApprove },
    { id: "page-unit-calendar", labelKey: "search.pages.unit_calendar", keywords: ["לוח שנה יחידתי"], path: "/unit-calendar", canAccess: authenticated },
    { id: "page-swaps", labelKey: "search.pages.swaps", keywords: ["החלפות"], path: "/swaps", canAccess: authenticated },
    { id: "page-profile", labelKey: "search.pages.profile", keywords: ["פרופיל"], path: "/profile", canAccess: authenticated },
    { id: "page-command-dashboard", labelKey: "search.pages.command_dashboard", keywords: ["דשבורד מפקד"], path: "/command-dashboard", canAccess: canApprove },
    { id: "page-notifications", labelKey: "search.pages.notifications", keywords: ["התראות"], path: "/notifications", canAccess: authenticated },
    { id: "page-planning-shifts", labelKey: "search.pages.planning_shifts", keywords: ["ניהול משמרות"], path: "/planning/shifts", canAccess: canPlan },
    { id: "page-planning-config", labelKey: "search.pages.planning_config", keywords: ["הגדרות תכנון"], path: "/planning/config", canAccess: canPlan },
    { id: "page-planning-score-adjustments", labelKey: "search.pages.planning_score_adjustments", keywords: ["התאמות ניקוד"], path: "/planning/score-adjustments", canAccess: canPlan },
    { id: "page-planning-export", labelKey: "search.pages.planning_export", keywords: ["ייצוא"], path: "/planning/export", canAccess: canPlan },
    { id: "page-planning-potential", labelKey: "search.pages.planning_potential", keywords: ["פוטנציאל"], path: "/planning/potential", canAccess: canPlan },
    { id: "page-admin-settings", labelKey: "search.pages.admin_settings", keywords: ["הגדרות מערכת"], path: "/admin/settings", canAccess: isAdmin },
    { id: "page-import", labelKey: "search.pages.import", keywords: ["ייבוא"], path: "/import", canAccess: canPlan },
  ];
}

export function getQuickActionEntries(): QuickActionEntry[] {
  return [
    { id: "action-approvals", labelKey: "search.actions.approvals", keywords: ["עבור לאישורים"], path: "/approvals", canAccess: canApprove },
    { id: "action-new-shift", labelKey: "search.actions.new_shift", keywords: ["יצירת משמרת חדשה"], path: "/planning/shifts", canAccess: canPlan },
    { id: "action-import-upload", labelKey: "search.actions.import_upload", keywords: ["העלאת קובץ ייבוא"], path: "/import/upload", canAccess: canPlan },
  ];
}

export function getHelpTopicEntries(gimelimEnabled: boolean): HelpTopicEntry[] {
  const topics: HelpTopicEntry[] = [
    { id: "swaps", labelKey: "search.help.swaps", keywords: ["החלפות", "swap"], canAccess: authenticated },
    { id: "algorithm", labelKey: "search.help.algorithm", keywords: ["אלגוריתם", "algorithm"], canAccess: authenticated },
    { id: "fairness", labelKey: "search.help.fairness", keywords: ["הוגנות", "שקיפות", "fairness"], canAccess: authenticated },
    { id: "deep", labelKey: "search.help.deep", keywords: ["מאחורי הקלעים", "deep"], canAccess: authenticated },
    { id: "approvals", labelKey: "search.help.approvals", keywords: ["אישורים", "approvals"], canAccess: canApprove },
    { id: "hierarchy", labelKey: "search.help.hierarchy", keywords: ["היררכיה", "כשירות", "hierarchy"], canAccess: authenticated },
  ];
  if (gimelimEnabled) {
    topics.push({ id: "gimelim", labelKey: "search.help.gimelim", keywords: ["גימלים", "gimelim"], canAccess: authenticated });
  }
  return topics;
}

export interface TabEntry {
  id: string;
  pageLabelKey: string;
  labelKey: string;
  keywords: string[];
  path: string;
  tabParam: string;
  canAccess: (user: SearchUser | null) => boolean;
}

export function getTabEntries(): TabEntry[] {
  return [
    { id: "tab-admin-invite-codes", pageLabelKey: "search.pages.admin_settings", labelKey: "nav.admin_invite_codes", keywords: ["קודי הזמנה", "הזמנות", "הרשמה"], path: "/admin/settings", tabParam: "1", canAccess: isAdmin },
    { id: "tab-admin-changelog", pageLabelKey: "search.pages.admin_settings", labelKey: "nav.admin_changelog", keywords: ["יומן שינויים", "עדכונים", "גרסאות"], path: "/admin/settings", tabParam: "2", canAccess: isAdmin },
    { id: "tab-admin-bug-reports", pageLabelKey: "search.pages.admin_settings", labelKey: "nav.admin_bug_reports", keywords: ["דיווחי באגים", "באגים", "תקלות"], path: "/admin/settings", tabParam: "3", canAccess: isAdmin },
    { id: "tab-approvals-exemptions", pageLabelKey: "search.pages.approvals", labelKey: "approvals.tab_exemptions", keywords: ["בקשות פטור", "פטורים"], path: "/approvals", tabParam: "exemptions", canAccess: canApprove },
    { id: "tab-approvals-field-updates", pageLabelKey: "search.pages.approvals", labelKey: "soldier_profile.field_updates_tab", keywords: ["עדכוני פרופיל", "שינויי פרטים"], path: "/approvals", tabParam: "field_updates", canAccess: canApprove },
    { id: "tab-approvals-swaps", pageLabelKey: "search.pages.approvals", labelKey: "swaps.title", keywords: ["בקשות החלפה", "אישור החלפות"], path: "/approvals", tabParam: "swaps", canAccess: canApprove },
    { id: "tab-approvals-enrollment", pageLabelKey: "search.pages.approvals", labelKey: "enrollment.tab", keywords: ["הצטרפויות", "גיוס", "קליטה"], path: "/approvals", tabParam: "enrollment", canAccess: canApprove },
    { id: "tab-approvals-transfers", pageLabelKey: "search.pages.approvals", labelKey: "approvals.tab_transfers", keywords: ["העברות", "מעבר יחידה"], path: "/approvals", tabParam: "transfers", canAccess: canApprove },
    { id: "tab-swaps-board", pageLabelKey: "search.pages.swaps", labelKey: "swaps.tab_board", keywords: ["מרקטפלייס", "לוח החלפות"], path: "/swaps", tabParam: "board", canAccess: authenticated },
    { id: "tab-swaps-incoming", pageLabelKey: "search.pages.swaps", labelKey: "swaps.tab_incoming", keywords: ["בקשות אליי", "בקשות נכנסות"], path: "/swaps", tabParam: "incoming", canAccess: authenticated },
    { id: "tab-swaps-pending", pageLabelKey: "search.pages.swaps", labelKey: "swaps.tab_pending", keywords: ["ממתינים לאישור", "החלפות בהמתנה"], path: "/swaps", tabParam: "pending", canAccess: authenticated },
    { id: "tab-transparency-sub-units", pageLabelKey: "search.pages.transparency", labelKey: "search.tabs.transparency_sub_units", keywords: ["תתי יחידות", "יחידות משנה"], path: "/transparency", tabParam: "sub_units", canAccess: authenticated },
  ];
}
