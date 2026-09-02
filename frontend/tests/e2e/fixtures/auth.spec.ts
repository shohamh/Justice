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

  test.describe(`saved ${role} session`, () => {
    test.use({ storageState: roleStorageState(role) });

    test("roleStorageState restores authentication", async ({ page }) => {
      await expect(page).toHaveURL(/\/$/);
      await expect(page.getByTestId("login-form")).toHaveCount(0);

      const me = await page.request.get("/api/me");
      expect(me.ok()).toBe(true);
      expect(await me.json()).toEqual(expect.objectContaining({
        personal_number: {
          soldier: "1000003",
          commander: "2000001",
          dutyManager: "2500001",
          admin: "1000001",
        }[role],
        role: role === "dutyManager" ? "duty_manager" : role,
      }));
    });
  });
}

test.describe("scenario data", () => {
  test.use({ storageState: roleStorageState("admin") });

  test("creates uniquely named configuration prerequisites", async ({ page }) => {
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
  });
});
