import { expect, it } from "vitest";
import { ADMIN_SETTINGS_TAB_ORDER } from "./AdminSettingsPage";

it("places the errors tab immediately before the audit log tab", () => {
  expect(ADMIN_SETTINGS_TAB_ORDER.indexOf("errors")).toBeLessThan(ADMIN_SETTINGS_TAB_ORDER.indexOf("audit-log"));
});

it("places the audit log tab immediately before the hr-sync tab", () => {
  expect(ADMIN_SETTINGS_TAB_ORDER.indexOf("audit-log")).toBeLessThan(ADMIN_SETTINGS_TAB_ORDER.indexOf("hr-sync"));
});

it("places the identity-conflicts tab after hr-sync, matching the tab index the page renders", () => {
  expect(ADMIN_SETTINGS_TAB_ORDER.indexOf("identity-conflicts")).toBe(ADMIN_SETTINGS_TAB_ORDER.indexOf("hr-sync") + 1);
  expect(ADMIN_SETTINGS_TAB_ORDER.indexOf("identity-conflicts")).toBe(7);
});
