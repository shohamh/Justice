import { test, expect, request as pwRequest, type APIRequestContext, type Page } from "@playwright/test";

/**
 * SSO browser journeys against a REAL OpenID Connect provider (Keycloak, imported
 * from justice-test-realm.json). Run with tests/e2e/oidc/run.ps1, which starts the
 * disposable stack (seeded DB, backend :8410 with OIDC_* -> Keycloak, Vite :5183).
 *
 * The provider is at http://127.0.0.1:8411 and the app at http://localhost:5183:
 * different sites, so the callback's cross-site redirect and Strict cookie handling
 * are real. Synthetic example.test identities only.
 */
const APP = process.env.E2E_BASE_URL ?? "http://localhost:5183";
const KC_PASSWORD = "Test-Passw0rd!";
const SEED_PASSWORD = "1234567890";
const MADOR_COMMANDER = "3000001"; // commander of mador "מחקר" (parent of team "צוות רוקט")
const TEAM_COMMANDER = "1000014"; // leader of team "צוות רוקט"
const ADMIN = "1000001";
const TEAM_NAME = "צוות רוקט";
const REGISTERED_PASSWORD = "Reg-Passw0rd!x";

/** Endpoints a plain soldier must never reach (admin / commander only). */
const PRIVILEGED_CALLS: { method: "get" | "post"; path: string; data?: object }[] = [
  { method: "get", path: "/api/admin/identity-conflicts" },
  { method: "get", path: "/api/admin/invite-codes" },
  { method: "post", path: "/api/admin/invite-codes", data: { uses_left: 1 } },
];

async function privilegedStatuses(personalNumber: string, password: string): Promise<number[]> {
  const { api, headers } = await apiAs(personalNumber, password);
  const statuses: number[] = [];
  for (const call of PRIVILEGED_CALLS) {
    const res = await api.fetch(call.path, { method: call.method, headers, data: call.data });
    statuses.push(res.status());
  }
  await api.dispose();
  return statuses;
}

async function keycloakSignIn(page: Page, username: string) {
  await expect(page).toHaveURL(/127\.0\.0\.1:8411\/realms\/justice-test\//);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(KC_PASSWORD);
  await page.locator("#kc-login").click();
}

async function startSso(page: Page, username: string) {
  await page.goto("/login");
  await page.getByTestId("sso-login-button").click();
  await keycloakSignIn(page, username);
}

async function expectNoSensitiveValues(page: Page, forbidden: string[] = []) {
  const url = page.url();
  expect(url).not.toMatch(/[?&](code|state|session_state|iss|id_token|access_token|token|email|nonce)=/);
  for (const value of forbidden) expect(url).not.toContain(value);
  const storage = await page.evaluate(() =>
    JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
  );
  expect(storage).not.toMatch(/id_token|access_token|code_verifier|nonce|session_state/i);
  for (const value of forbidden) expect(storage).not.toContain(value);
}

/** POST /api/auth/refresh with the page's cookies; retries a request that stalls on a starved machine. */
async function refreshOk(page: Page): Promise<boolean> {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      return (await page.request.post("/api/auth/refresh", { timeout: 15_000 })).ok();
    } catch {
      /* stalled request: retry */
    }
  }
  throw new Error("refresh request kept timing out");
}

async function apiAs(personalNumber: string, password = SEED_PASSWORD) {
  const api: APIRequestContext = await pwRequest.newContext({ baseURL: APP });
  const res = await api.post("/api/auth/login", {
    data: { personal_number: personalNumber, password },
  });
  expect(res.ok(), `login ${personalNumber}: ${res.status()} ${(await res.text()).slice(0, 200)}`).toBeTruthy();
  const token = ((await res.json()) as { access_token: string }).access_token;
  return { api, headers: { Authorization: `Bearer ${token}` } };
}

/** Fills the (multi-step) registration form from the personal-details step on. */
async function fillRegistration(page: Page, personalNumber: string, name: string) {
  const field = (label: string) => page.locator("label", { hasText: label }).first().locator("input").first();
  await field("מספר אישי").fill(personalNumber);
  await field("שם מלא").fill(name);
  await field("טלפון").fill("0501234567");
  await page.locator("label", { hasText: "מגדר" }).locator("select").selectOption("male");
  for (const [label, digits] of [
    ["תאריך גיוס", "01012025"],
    ["תאריך כניסה ליחידה", "01012025"],
    ["סיום חובה", "01012028"],
    ["תאריך שחרור", "01012029"],
    ["מטווח אחרון", "01062026"],
  ] as const) {
    const input = field(label);
    if (await input.count()) await input.pressSequentially(digits);
  }
  const rank = page.locator("label", { hasText: "דרגה" }).first().getByRole("combobox");
  await rank.scrollIntoViewIfNeeded();
  // The rank ladder loads asynchronously and the dropdown is fixed-position: centre the field
  // so the list is on screen, then pick the option and require that the "required" hint went away
  // (the typed text alone is not a selection).
  await rank.evaluate((el) => el.scrollIntoView({ block: "center" }));
  await expect(async () => {
    await rank.fill("");
    await rank.click();
    await page.getByRole("listbox").getByRole("button", { name: "סמל", exact: true }).first().click({ timeout: 3000 });
    await expect(rank).toHaveValue("סמל", { timeout: 1000 });
    await expect(page.locator("label", { hasText: "דרגה" }).first().getByText("שדה חובה")).toHaveCount(0, { timeout: 1000 });
  }).toPass({ timeout: 60_000 });
  const password = page.locator("label", { hasText: "סיסמה" }).first().locator("input").first();
  await password.fill(REGISTERED_PASSWORD);
  await expect(password).toHaveValue(REGISTERED_PASSWORD);
  await page.locator("label", { hasText: "אימות סיסמה" }).locator("input").first().fill(REGISTERED_PASSWORD);
  const next = () => page.getByRole("button", { name: "הבא" });
  await next().click(); // -> exemptions
  await next().click(); // -> constraints
  await next().click(); // -> commander/node
  await page.getByRole("button", { name: new RegExp(TEAM_NAME) }).first().click();
  await next().click(); // -> review
  await page.getByRole("button", { name: "הרשם", exact: true }).last().click();
}

test.describe.configure({ mode: "serial" });

test.describe("login UI", () => {
  test("SSO button is shown next to password login when configured", async ({ page }) => {
    test.skip(process.env.E2E_OIDC_DISABLED === "1", "backend without OIDC settings");
    await page.goto("/login");
    await expect(page.getByTestId("sso-login-button")).toBeVisible();
    await expect(page.getByTestId("personal-number-input")).toBeVisible();
    await expect(page.getByTestId("login-submit")).toBeVisible();
  });

  test("backend with no OIDC settings: no SSO button, start endpoint is 404, password login stays usable", async ({ page }) => {
    test.skip(process.env.E2E_OIDC_DISABLED !== "1", "needs a backend started without OIDC_* (run.ps1 -NoOidc)");
    await page.goto("/login");
    await expect(page.getByTestId("login-form")).toBeVisible();
    await expect(page.getByTestId("personal-number-input")).toBeVisible();
    await expect(page.getByTestId("sso-login-button")).toHaveCount(0);
    expect((await page.request.get("/api/auth/oidc/status")).status()).toBe(200);
    expect(await (await page.request.get("/api/auth/oidc/status")).json()).toEqual({ enabled: false });
    expect((await page.request.get("/api/auth/oidc/start", { maxRedirects: 0 })).status()).toBe(404);
  });
});

test.describe("existing soldier", () => {
  test("matching email + AD username signs in via Keycloak, and a second login uses the stored link", async ({ page, context }) => {
    await startSso(page, "sso.existing");
    await expect(page).toHaveURL(`${APP}/`);
    await expect(page.getByTestId("login-form")).toHaveCount(0);
    expect(await refreshOk(page)).toBeTruthy();
    await expectNoSensitiveValues(page, ["sso.existing", "example.test"]);

    // Second login (new browser session): resolved from the stored issuer/subject link.
    await context.clearCookies();
    await startSso(page, "sso.existing");
    await expect(page).toHaveURL(`${APP}/`);
    expect(await refreshOk(page)).toBeTruthy();
  });
});

test.describe("failures stay generic", () => {
  test("unverified provider email: generic error, no session, no registration context", async ({ page, context }) => {
    await startSso(page, "sso.unverified");
    await expect(page).toHaveURL(`${APP}/login?sso_error=1`);
    await expect(page.getByTestId("sso-error")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("sso.unverified");
    await expectNoSensitiveValues(page, ["sso.unverified", "example.test"]);
    expect(await refreshOk(page)).toBeFalsy();
    expect((await page.request.get("/api/auth/oidc/registration-context")).status()).toBe(404);
    const cookieNames = (await context.cookies()).map((c) => c.name);
    expect(cookieNames).not.toContain("refresh_token");
    expect(cookieNames).not.toContain("oidc_reg");
  });

  test("ambiguous identity: generic error, conflict visible to the admin", async ({ page, browser }) => {
    await startSso(page, "sso.ambig");
    await expect(page).toHaveURL(`${APP}/login?sso_error=1`);
    await expect(page.getByTestId("sso-error")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("sso.ambig");
    expect(await refreshOk(page)).toBeFalsy();
    await expectNoSensitiveValues(page, ["sso.ambig", "example.test"]);

    // The admin signs in through the API and the page starts from that session (as the other e2e
    // suites do): signing in through the UI and navigating away at once aborted the home page's
    // ~45 in-flight calls, which kept the small test backend busy and starved the next page load.
    const adminApi = await apiAs(ADMIN);
    const admin = await browser.newContext({ baseURL: APP, storageState: await adminApi.api.storageState() });
    const adminPage = await admin.newPage();
    await adminPage.goto("/admin/settings?tab=7");
    await expect(adminPage.getByTestId("identity-conflicts-content")).toBeVisible();
    await expect(adminPage.locator('[data-testid^="identity-conflict-"]').first()).toBeVisible();
    await expect(adminPage.getByTestId("identity-conflicts-empty")).toHaveCount(0);
    await adminApi.api.dispose();
    await admin.close();
  });
});

test.describe("unmatched identity registers and needs mador approval", () => {
  const personalNumber = String(8000000 + (Date.now() % 900000));
  let requestId = "";

  test("registration is prefilled read-only without an invite code and ends pending", async ({ page }) => {
    await startSso(page, "sso.new1");
    await expect(page).toHaveURL(`${APP}/register?sso=1`);
    await expect(page.getByLabel("קוד הזמנה")).toHaveCount(0);
    const email = page.locator('input[type="email"]');
    await expect(email).toHaveValue("sso.new1@example.test");
    await expect(email).toHaveAttribute("readonly", "");
    await expect(page.getByTestId("sso-ad-username")).toHaveValue("sso.new1");
    await expect(page.getByTestId("sso-ad-username")).toHaveAttribute("readonly", "");
    await expectNoSensitiveValues(page, ["sso.new1", "example.test"]);

    await fillRegistration(page, personalNumber, "בדיקה אס אס או");
    await expect(page).not.toHaveURL(/register/);
    await expectNoSensitiveValues(page, ["sso.new1", "example.test"]);

    // Pending in the holding node: the admin sees an open enrollment request.
    const { api, headers } = await apiAs(ADMIN);
    const pending = await api.get("/api/enrollment-requests/pending", { headers });
    const rows = (await pending.json()) as { id: string; soldier_personal_number: string }[];
    const mine = rows.find((r) => r.soldier_personal_number === personalNumber);
    expect(mine, "pending enrollment request").toBeTruthy();
    requestId = mine!.id;
    await api.dispose();

    // Holding-node soldier before approval: no admin/commander-only call is allowed.
    expect(await privilegedStatuses(personalNumber, REGISTERED_PASSWORD)).toEqual([403, 403, 403]);
  });

  test("a team-level commander cannot approve; a mador-level commander can", async () => {
    expect(requestId).not.toBe("");
    const team = await apiAs(TEAM_COMMANDER);
    const denied = await team.api.post(`/api/enrollment-requests/${requestId}/approve`, {
      headers: team.headers,
      data: {},
    });
    expect(denied.status()).toBe(403);
    expect(await denied.json()).toMatchObject({ detail: "sso_approval_requires_mador" });
    await team.api.dispose();

    const mador = await apiAs(MADOR_COMMANDER);
    const ok = await mador.api.post(`/api/enrollment-requests/${requestId}/approve`, {
      headers: mador.headers,
      data: {},
    });
    expect(ok.status()).toBe(200);
    const pending = await mador.api.get("/api/enrollment-requests/pending", { headers: mador.headers });
    expect(((await pending.json()) as { id: string }[]).some((r) => r.id === requestId)).toBeFalsy();
    await mador.api.dispose();

    // After approval the soldier gains only what a normal soldier has (same denials).
    expect(await privilegedStatuses(personalNumber, REGISTERED_PASSWORD)).toEqual([403, 403, 403]);
    expect(await privilegedStatuses("1000003", SEED_PASSWORD)).toEqual([403, 403, 403]);
    const me = await apiAs(personalNumber, REGISTERED_PASSWORD);
    const profile = await me.api.get("/api/soldiers/me/reserve-stats", { headers: me.headers });
    expect(profile.status()).toBeLessThan(500);
    await me.api.dispose();
  });
});

test.describe("legacy flows are unaffected", () => {
  test("personal-number/password login still works and sets the usual session", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("personal-number-input").fill("1000003");
    await page.getByTestId("password-input").fill(SEED_PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL(`${APP}/`);
    expect(await refreshOk(page)).toBeTruthy();
  });

  test("plain invite-code registration still starts with the code and completes", async ({ page }) => {
    const { api, headers } = await apiAs(ADMIN);
    const created = await api.post("/api/admin/invite-codes", { headers, data: { uses_left: 1 } });
    expect(created.ok()).toBeTruthy();
    const code = ((await created.json()) as { code: string }).code;
    await api.dispose();

    await page.goto("/register");
    await expect(page.getByTestId("sso-ad-username")).toHaveCount(0);
    await page.getByLabel("קוד הזמנה").fill(code);
    await page.getByRole("button", { name: "הבא" }).click();
    const personalNumber = String(7000000 + (Date.now() % 900000));
    await page.locator("label", { hasText: "אימייל" }).locator("input").fill(`plain.${personalNumber}@example.test`);
    await fillRegistration(page, personalNumber, "בדיקה רגילה");
    await expect(page).not.toHaveURL(/register/);
  });
});
