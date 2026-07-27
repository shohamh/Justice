import { describe, expect, test } from "vitest";
import { getPageEntries, getQuickActionEntries, getHelpTopicEntries, getTabEntries } from "./searchRegistry";
import type { SearchUser } from "./searchRegistry";

const soldier: SearchUser = { role: "soldier", is_commander: false, is_duty_manager: false };
const commander: SearchUser = { role: "soldier", is_commander: true, is_duty_manager: false };
const dutyManager: SearchUser = { role: "duty_manager", is_commander: false, is_duty_manager: true };
const admin: SearchUser = { role: "admin", is_commander: false, is_duty_manager: false };

describe("searchRegistry pages", () => {
  test("plain soldier cannot access planning pages", () => {
    const entries = getPageEntries();
    const planning = entries.find((e) => e.id === "page-planning-shifts")!;
    expect(planning.canAccess(soldier)).toBe(false);
    expect(planning.canAccess(dutyManager)).toBe(true);
    expect(planning.canAccess(admin)).toBe(true);
  });

  test("duty manager with role soldier can access planning pages", () => {
    const dutyManagerWithSoldierRole: SearchUser = { role: "soldier", is_commander: false, is_duty_manager: true };
    const entries = getPageEntries();
    const planning = entries.find((e) => e.id === "page-planning-shifts")!;
    expect(planning.canAccess(dutyManagerWithSoldierRole)).toBe(true);
  });

  test("plain soldier can access home and my-duties", () => {
    const entries = getPageEntries();
    expect(entries.find((e) => e.id === "page-home")!.canAccess(soldier)).toBe(true);
    expect(entries.find((e) => e.id === "page-my-duties")!.canAccess(soldier)).toBe(true);
  });

  test("admin settings page requires admin role", () => {
    const entries = getPageEntries();
    const settings = entries.find((e) => e.id === "page-admin-settings")!;
    expect(settings.canAccess(soldier)).toBe(false);
    expect(settings.canAccess(admin)).toBe(true);
  });

  test("no entry is accessible with a null user", () => {
    const entries = getPageEntries();
    expect(entries.every((e) => e.canAccess(null) === false)).toBe(true);
  });
});

describe("searchRegistry quick actions", () => {
  test("commander-gated quick action excludes plain soldiers", () => {
    const entries = getQuickActionEntries();
    const approve = entries.find((e) => e.id === "action-approvals")!;
    expect(approve.canAccess(soldier)).toBe(false);
    expect(approve.canAccess(commander)).toBe(true);
  });
});

describe("searchRegistry help topics", () => {
  test("gimelim topic only present when gimelimEnabled is true", () => {
    expect(getHelpTopicEntries(true, true).some((e) => e.id === "gimelim")).toBe(true);
    expect(getHelpTopicEntries(false, true).some((e) => e.id === "gimelim")).toBe(false);
  });

  test("hakpaza topic only present when hakpazaEnabled is true", () => {
    expect(getHelpTopicEntries(true, true).some((e) => e.id === "hakpaza")).toBe(true);
    expect(getHelpTopicEntries(true, false).some((e) => e.id === "hakpaza")).toBe(false);
  });

  test("all non-gimelim, non-approvals, non-hakpaza, non-import topics are accessible to every authenticated user", () => {
    const entries = getHelpTopicEntries(true, true).filter((e) => e.id !== "gimelim" && e.id !== "approvals" && e.id !== "hakpaza" && e.id !== "import");
    expect(entries.every((e) => e.canAccess(soldier))).toBe(true);
  });
});

describe("searchRegistry tabs", () => {
  test("returns exactly 12 tab entries", () => {
    expect(getTabEntries().length).toBe(12);
  });

  test("admin settings tabs require admin role", () => {
    const entries = getTabEntries();
    const inviteCodes = entries.find((e) => e.id === "tab-admin-invite-codes")!;
    expect(inviteCodes.canAccess(soldier)).toBe(false);
    expect(inviteCodes.canAccess(admin)).toBe(true);
  });

  test("approvals tabs require approval capability", () => {
    const entries = getTabEntries();
    const exemptions = entries.find((e) => e.id === "tab-approvals-exemptions")!;
    expect(exemptions.canAccess(soldier)).toBe(false);
    expect(exemptions.canAccess(commander)).toBe(true);
    expect(exemptions.canAccess(dutyManager)).toBe(true);
  });

  test("swaps and transparency tabs are accessible to any authenticated user", () => {
    const entries = getTabEntries();
    expect(entries.find((e) => e.id === "tab-swaps-board")!.canAccess(soldier)).toBe(true);
    expect(entries.find((e) => e.id === "tab-transparency-sub-units")!.canAccess(soldier)).toBe(true);
  });

  test("no tab entry is accessible with a null user", () => {
    expect(getTabEntries().every((e) => e.canAccess(null) === false)).toBe(true);
  });

  test("each tab entry within the same page has a distinct tabParam", () => {
    const entries = getTabEntries();
    const approvalsTabs = entries.filter((e) => e.path === "/approvals");
    const params = approvalsTabs.map((e) => e.tabParam);
    expect(new Set(params).size).toBe(params.length);
  });
});
