export interface SearchUser {
  role: "soldier" | "commander" | "duty_manager" | "admin";
  is_commander: boolean;
  is_duty_manager: boolean;
}

export function isAdmin(user: SearchUser | null): boolean {
  return user?.role === "admin";
}

export function canApprove(user: SearchUser | null): boolean {
  return user?.role === "admin" || !!user?.is_commander || !!user?.is_duty_manager;
}

export function canPlan(user: SearchUser | null): boolean {
  return user?.role === "admin" || !!user?.is_duty_manager;
}

export const authenticated = (user: SearchUser | null): boolean => user !== null;
