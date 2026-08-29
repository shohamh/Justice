import { expect, it } from "vitest";
import { ADMIN_SETTINGS_TAB_ORDER } from "./AdminSettingsPage";

it("places the errors tab immediately before the audit log tab", () => {
  expect(ADMIN_SETTINGS_TAB_ORDER.indexOf("errors")).toBeLessThan(ADMIN_SETTINGS_TAB_ORDER.indexOf("audit-log"));
});
