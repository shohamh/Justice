import { chromium, expect, type FullConfig, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const roles = ["soldier", "commander", "dutyManager", "admin"] as const;

export type Role = (typeof roles)[number];

export const journeyActors = {
  assignedExemption: "1000009",
  assignedGimelim: "1000010",
  assignedAbsent: "1000011",
  assignedHakpaza: "1000012",
  firstReserve: "1000002",
  secondReserve: "1000003",
  // Swaps journey (frontend/tests/e2e/smoke/swaps.spec.ts). Team "רוקט"'s
  // four non-officer, non-leader members: 1000015-1000018. Verified against
  // the seeded DB directly (not just seed.py's team-size arithmetic) —
  // 1000014 is that team's leader (role="commander") and 1000019 is an
  // officer (is_officer=true, blocked from most duty types by rank rules),
  // neither a plain assignable soldier.
  swapRequesterA: "1000015",
  swapCoveringA: "1000016",
  swapRequesterB: "1000017",
  swapCoveringB: "1000018",
  // Hierarchy transfers journey (frontend/tests/e2e/smoke/hierarchy_transfers.spec.ts).
  // "צוות ריי" (team "Ray", under branch "פוקוס" -> mador "שבירה"), a plain
  // non-officer, non-leader member ("ריי 3") — verified against seed.py's
  // team-soldier numbering directly: `next_pn()` is first called in the
  // team-leader loop, so with all_teams ordered מארס/טוקסיק/רוקט/ורטיגו
  // (under מחקר) then פלאש/ריי/ספארק (under שבירה) then ארק/אקסודוס/נילוס
  // (under גוליבר), team "ריי" (6th team, index 5) gets leader pn 1000032
  // and members 1000033-1000037; this is member index 2 (0-based),
  // i.e. 1000035. Used as the *transferred soldier* to view their own
  // rejection notice on /my-requests — NOT as the actor who submits or
  // approves the transfer (those roles are covered by the existing
  // `commander`/`dutyManager` role fixtures, which are already scoped, via
  // seed.py's branch-wide commander/DutyManagerScope assignment, across the
  // entire "פוקוס" branch subtree — including both "ריי" and its sibling
  // team "ספארק" used as source/destination — so no separate actor is
  // needed for the create/approve/reject actions themselves).
  transferSoldier: "1000035",
} as const;

export type JourneyActor = keyof typeof journeyActors;

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

export function journeyActorStorageState(actor: JourneyActor): string {
  return resolve(authStateDirectory, `journey-${actor}.json`);
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
  const browser = await chromium.launch({ channel: "chrome" });

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
    for (const actor of Object.keys(journeyActors) as JourneyActor[]) {
      const context = await browser.newContext({ baseURL });
      try {
        const page = await context.newPage();
        await page.goto("/login");
        await page.getByTestId("personal-number-input").fill(journeyActors[actor]);
        await page.getByTestId("password-input").fill(SEED_PASSWORD);
        await page.getByTestId("login-submit").click();
        await expect(page).toHaveURL(/\/$/);
        await context.storageState({ path: journeyActorStorageState(actor) });
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
}
