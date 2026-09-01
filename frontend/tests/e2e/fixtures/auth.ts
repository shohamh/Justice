import { chromium, expect, type FullConfig, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const roles = ["soldier", "commander", "dutyManager", "admin"] as const;

export type Role = (typeof roles)[number];

const SEED_PASSWORD = "1234567890";
const authStateDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "../../../.playwright/auth");

const seededAccounts: Record<Role, { personalNumber: string }> = {
  soldier: { personalNumber: "1000003" },
  commander: { personalNumber: "2000001" },
  dutyManager: { personalNumber: "2500001" },
  admin: { personalNumber: "1000001" },
};

export function roleStorageState(role: Role): string {
  return resolve(authStateDirectory, `${role}.json`);
}

export async function loginAs(page: Page, role: Role): Promise<Page> {
  const account = seededAccounts[role];

  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill(account.personalNumber);
  await page.getByTestId("password-input").fill(SEED_PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(/\/$/);

  return page;
}

export default async function authenticateSeededRoles(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use.baseURL;
  if (typeof baseURL !== "string") {
    throw new Error("Playwright requires a string baseURL to create role storage states.");
  }

  await mkdir(dirname(roleStorageState("admin")), { recursive: true });
  const browser = await chromium.launch();

  try {
    for (const role of roles) {
      const context = await browser.newContext({ baseURL });
      try {
        const page = await context.newPage();
        await loginAs(page, role);
        await context.storageState({ path: roleStorageState(role) });
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
}
