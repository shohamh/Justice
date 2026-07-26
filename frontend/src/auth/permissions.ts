export interface PermissionUser {
  role: "soldier" | "commander" | "duty_manager" | "admin";
  is_commander: boolean;
  is_duty_manager: boolean;
}

export function isAdmin(user: PermissionUser | null): boolean {
  return user?.role === "admin";
}

export function canApprove(user: PermissionUser | null): boolean {
  return user?.role === "admin" || !!user?.is_commander || !!user?.is_duty_manager;
}

export function canPlan(user: PermissionUser | null): boolean {
  return user?.role === "admin" || !!user?.is_duty_manager;
}

export function authenticated(user: PermissionUser | null): boolean {
  return user !== null;
}
