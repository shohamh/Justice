export interface SearchUser {
  role: "soldier" | "commander" | "duty_manager" | "admin";
  is_commander: boolean;
  is_duty_manager: boolean;
}

function isAdmin(user: SearchUser | null): boolean {
  return user?.role === "admin";
}

function canApprove(user: SearchUser | null): boolean {
  return user?.role === "admin" || !!user?.is_commander || !!user?.is_duty_manager;
}

function canPlan(user: SearchUser | null): boolean {
  return user?.role === "admin" || !!user?.is_duty_manager;
}

export interface PageEntry {
  id: string;
  labelKey: string;
  descriptionKey?: string;
  path: string;
  canAccess: (user: SearchUser | null) => boolean;
}

export interface QuickActionEntry {
  id: string;
  labelKey: string;
  path: string;
  canAccess: (user: SearchUser | null) => boolean;
}

export interface HelpTopicEntry {
  id: string;
  labelKey: string;
  keywords: string[];
  canAccess: (user: SearchUser | null) => boolean;
}

const authenticated = (user: SearchUser | null): boolean => user !== null;

export function getPageEntries(): PageEntry[] {
  return [
    { id: "page-home", labelKey: "search.pages.home", path: "/", canAccess: authenticated },
    { id: "page-team", labelKey: "search.pages.team", path: "/team", canAccess: authenticated },
    { id: "page-transparency", labelKey: "search.pages.transparency", path: "/transparency", canAccess: authenticated },
    { id: "page-my-duties", labelKey: "search.pages.my_duties", path: "/my-duties", canAccess: authenticated },
    { id: "page-my-requests", labelKey: "search.pages.my_requests", path: "/my-requests", canAccess: authenticated },
    { id: "page-approvals", labelKey: "search.pages.approvals", path: "/approvals", canAccess: canApprove },
    { id: "page-unit-calendar", labelKey: "search.pages.unit_calendar", path: "/unit-calendar", canAccess: authenticated },
    { id: "page-swaps", labelKey: "search.pages.swaps", path: "/swaps", canAccess: authenticated },
    { id: "page-profile", labelKey: "search.pages.profile", path: "/profile", canAccess: authenticated },
    { id: "page-command-dashboard", labelKey: "search.pages.command_dashboard", path: "/command-dashboard", canAccess: canApprove },
    { id: "page-notifications", labelKey: "search.pages.notifications", path: "/notifications", canAccess: authenticated },
    { id: "page-planning-shifts", labelKey: "search.pages.planning_shifts", path: "/planning/shifts", canAccess: canPlan },
    { id: "page-planning-config", labelKey: "search.pages.planning_config", path: "/planning/config", canAccess: canPlan },
    { id: "page-planning-score-adjustments", labelKey: "search.pages.planning_score_adjustments", path: "/planning/score-adjustments", canAccess: canPlan },
    { id: "page-planning-export", labelKey: "search.pages.planning_export", path: "/planning/export", canAccess: canPlan },
    { id: "page-planning-potential", labelKey: "search.pages.planning_potential", path: "/planning/potential", canAccess: canPlan },
    { id: "page-admin-settings", labelKey: "search.pages.admin_settings", path: "/admin/settings", canAccess: isAdmin },
    { id: "page-import", labelKey: "search.pages.import", path: "/import", canAccess: canPlan },
  ];
}

export function getQuickActionEntries(): QuickActionEntry[] {
  return [
    { id: "action-approvals", labelKey: "search.actions.approvals", path: "/approvals", canAccess: canApprove },
    { id: "action-new-shift", labelKey: "search.actions.new_shift", path: "/planning/shifts", canAccess: canPlan },
    { id: "action-import-upload", labelKey: "search.actions.import_upload", path: "/import/upload", canAccess: canPlan },
  ];
}

export function getHelpTopicEntries(gimelimEnabled: boolean): HelpTopicEntry[] {
  const topics: HelpTopicEntry[] = [
    { id: "swaps", labelKey: "search.help.swaps", keywords: ["החלפות", "swap"], canAccess: authenticated },
    { id: "algorithm", labelKey: "search.help.algorithm", keywords: ["אלגוריתם", "algorithm"], canAccess: authenticated },
    { id: "fairness", labelKey: "search.help.fairness", keywords: ["הוגנות", "שקיפות", "fairness"], canAccess: authenticated },
    { id: "deep", labelKey: "search.help.deep", keywords: ["מאחורי הקלעים", "deep"], canAccess: authenticated },
  ];
  if (gimelimEnabled) {
    topics.push({ id: "gimelim", labelKey: "search.help.gimelim", keywords: ["גימלים", "gimelim"], canAccess: authenticated });
  }
  return topics;
}
