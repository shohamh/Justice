import { describe, expect, test } from "vitest";
import { getPageEntries, getQuickActionEntries, getHelpTopicEntries } from "./searchRegistry";
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
    expect(getHelpTopicEntries(true).some((e) => e.id === "gimelim")).toBe(true);
    expect(getHelpTopicEntries(false).some((e) => e.id === "gimelim")).toBe(false);
  });

  test("all non-gimelim topics are accessible to every authenticated user", () => {
    const entries = getHelpTopicEntries(true).filter((e) => e.id !== "gimelim");
    expect(entries.every((e) => e.canAccess(soldier))).toBe(true);
  });
});
