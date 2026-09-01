import { expect, test } from "./test";

import { roleStorageState, roles } from "./auth";
import { createScenarioData, createUniqueName } from "./data";

for (const role of roles) {
  test(`loginAs authenticates the seeded ${role} account`, async ({ loginAsRole, page }) => {
    await loginAsRole(role);

    await expect(page).toHaveURL(/\/$/);

    const commanderNavigation = page.getByTestId("nav-commander");
    const planningNavigation = page.getByTestId("nav-planning");

    if (role === "soldier") {
      await expect(commanderNavigation).toHaveCount(0);
      await expect(planningNavigation).toHaveCount(0);
    } else if (role === "commander") {
      await expect(commanderNavigation).toBeVisible();
      await expect(planningNavigation).toHaveCount(0);
    } else {
      await expect(commanderNavigation).toBeVisible();
      await expect(planningNavigation).toBeVisible();
    }
  });

  test(`roleStorageState restores the seeded ${role} session`, async ({ browser }) => {
    const context = await browser.newContext({ storageState: roleStorageState(role) });
    const page = await context.newPage();

    await page.goto("/");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId("login-form")).toHaveCount(0);

    await context.close();
  });
}

test.describe("authenticated page fixture", () => {
  test.use({ storageState: roleStorageState("admin") });

  test("opens the saved admin session on the home page", async ({ page }) => {
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId("login-form")).toHaveCount(0);
  });
});

test("scenario data creates uniquely named configuration prerequisites", async ({ browser }) => {
  const context = await browser.newContext({ storageState: roleStorageState("admin") });
  const page = await context.newPage();

  try {
    const first = await createScenarioData(page.request);
    const second = await createScenarioData(page.request);

    expect(first.dutyType.name).toContain(first.runId);
    expect(first.location.name).toContain(first.runId);
    expect(first.exemptionType.name).toContain(first.runId);
    expect(first.dutyType.id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(first.location.id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(first.exemptionType.id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(createUniqueName("duty")).not.toBe(createUniqueName("duty"));
    expect(first.runId).not.toBe(second.runId);

    const refresh = await page.request.post("/api/auth/refresh");
    expect(refresh.ok()).toBe(true);
    const { access_token } = await refresh.json() as { access_token: string };
    const headers = { Authorization: `Bearer ${access_token}` };
    const [dutyTypes, locations, exemptionTypes] = await Promise.all([
      page.request.get("/api/duty-config/duty-types", { headers }),
      page.request.get("/api/duty-config/locations", { headers }),
      page.request.get("/api/duty-config/exemption-types", { headers }),
    ]);

    expect(dutyTypes.ok()).toBe(true);
    expect(locations.ok()).toBe(true);
    expect(exemptionTypes.ok()).toBe(true);
    const [dutyTypeRows, locationRows, exemptionTypeRows] = await Promise.all([
      dutyTypes.json() as Promise<{ id: string; name: string }[]>,
      locations.json() as Promise<{ id: string; name: string }[]>,
      exemptionTypes.json() as Promise<{ id: string; name: string }[]>,
    ]);
    expect(dutyTypeRows).toContainEqual(expect.objectContaining(first.dutyType));
    expect(locationRows).toContainEqual(expect.objectContaining(first.location));
    expect(exemptionTypeRows).toContainEqual(expect.objectContaining(first.exemptionType));
  } finally {
    await context.close();
  }
});
