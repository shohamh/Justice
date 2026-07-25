import { describe, it, expect } from "vitest";
import { isAdmin, canApprove, canPlan, authenticated, SearchUser } from "./permissions";

describe("permissions", () => {
  describe("isAdmin", () => {
    it("returns true for admin user", () => {
      const user: SearchUser = {
        role: "admin",
        is_commander: false,
        is_duty_manager: false,
      };
      expect(isAdmin(user)).toBe(true);
    });

    it("returns false for non-admin user", () => {
      const user: SearchUser = {
        role: "soldier",
        is_commander: false,
        is_duty_manager: false,
      };
      expect(isAdmin(user)).toBe(false);
    });

    it("returns false for null user", () => {
      expect(isAdmin(null)).toBe(false);
    });

    it("returns false for commander", () => {
      const user: SearchUser = {
        role: "commander",
        is_commander: true,
        is_duty_manager: false,
      };
      expect(isAdmin(user)).toBe(false);
    });
  });

  describe("canApprove", () => {
    it("returns true for admin user", () => {
      const user: SearchUser = {
        role: "admin",
        is_commander: false,
        is_duty_manager: false,
      };
      expect(canApprove(user)).toBe(true);
    });

    it("returns true for commander", () => {
      const user: SearchUser = {
        role: "soldier",
        is_commander: true,
        is_duty_manager: false,
      };
      expect(canApprove(user)).toBe(true);
    });

    it("returns true for duty manager", () => {
      const user: SearchUser = {
        role: "soldier",
        is_commander: false,
        is_duty_manager: true,
      };
      expect(canApprove(user)).toBe(true);
    });

    it("returns false for regular soldier", () => {
      const user: SearchUser = {
        role: "soldier",
        is_commander: false,
        is_duty_manager: false,
      };
      expect(canApprove(user)).toBe(false);
    });

    it("returns false for null user", () => {
      expect(canApprove(null)).toBe(false);
    });
  });

  describe("canPlan", () => {
    it("returns true for admin user", () => {
      const user: SearchUser = {
        role: "admin",
        is_commander: false,
        is_duty_manager: false,
      };
      expect(canPlan(user)).toBe(true);
    });

    it("returns true for duty manager", () => {
      const user: SearchUser = {
        role: "soldier",
        is_commander: false,
        is_duty_manager: true,
      };
      expect(canPlan(user)).toBe(true);
    });

    it("returns false for commander without duty_manager role", () => {
      const user: SearchUser = {
        role: "soldier",
        is_commander: true,
        is_duty_manager: false,
      };
      expect(canPlan(user)).toBe(false);
    });

    it("returns false for regular soldier", () => {
      const user: SearchUser = {
        role: "soldier",
        is_commander: false,
        is_duty_manager: false,
      };
      expect(canPlan(user)).toBe(false);
    });

    it("returns false for null user", () => {
      expect(canPlan(null)).toBe(false);
    });
  });

  describe("authenticated", () => {
    it("returns true for any user", () => {
      const user: SearchUser = {
        role: "soldier",
        is_commander: false,
        is_duty_manager: false,
      };
      expect(authenticated(user)).toBe(true);
    });

    it("returns false for null user", () => {
      expect(authenticated(null)).toBe(false);
    });

    it("returns true for admin", () => {
      const user: SearchUser = {
        role: "admin",
        is_commander: false,
        is_duty_manager: false,
      };
      expect(authenticated(user)).toBe(true);
    });
  });
});
