import { canApprove, PermissionUser } from "./permissions";

export function isManagementUser(user: PermissionUser | null): boolean {
  return canApprove(user);
}

export function isCommandScopeAvailable(user: PermissionUser | null): boolean {
  return isManagementUser(user);
}
