import { describe, expect, it } from "vitest";

import type { PermissionUser } from "./permissions";
import { isCommandScopeAvailable, isManagementUser } from "./dashboardRoles";

describe("dashboardRoles", () => {
  it.each([
    [{ role: "admin", is_commander: false, is_duty_manager: false }, true],
    [{ role: "commander", is_commander: true, is_duty_manager: false }, true],
    [{ role: "duty_manager", is_commander: false, is_duty_manager: true }, true],
    [{ role: "soldier", is_commander: false, is_duty_manager: false }, false],
  ])("classifies %s as a management dashboard user", (user, expected) => {
    expect(isManagementUser(user as PermissionUser)).toBe(expected);
  });

  it("does not expose command scope for an anonymous user", () => {
    expect(isCommandScopeAvailable(null)).toBe(false);
  });

  it("keeps command scope availability aligned with management access", () => {
    const user = { role: "duty_manager", is_commander: false, is_duty_manager: true } as PermissionUser;

    expect(isCommandScopeAvailable(user)).toBe(true);
    expect(isCommandScopeAvailable(user)).toBe(isManagementUser(user));
  });
});
