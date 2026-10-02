import { test, expect, type Page } from "@playwright/test";

/**
 * SSO browser journeys against the in-process mock provider
 * (backend/tests/support/mock_oidc.py, MockOidcProvider().asgi_app()).
 *
 * These need a dedicated backend: OIDC_ISSUER/OIDC_CLIENT_ID/OIDC_REDIRECT_URI
 * pointing at the mock provider (OIDC_ALLOW_INSECURE_LOCAL=true when it is served
 * over http on loopback) and FRONTEND_URL set to the app under test. They are
 * skipped unless E2E_OIDC_MOCK_URL (the mock's base URL) is set, so the default
 * e2e run is unaffected. The "unconfigured" test instead needs E2E_OIDC_DISABLED=1
 * and a backend with no OIDC_* settings.
 *
 * The mock selects who the next login is via POST /__identity.
 */
const MOCK_URL = process.env.E2E_OIDC_MOCK_URL;
const DISABLED = process.env.E2E_OIDC_DISABLED === "1";

async function selectIdentity(
  page: Page,
  identity: { subject: string; email: string; email_verified: boolean },
) {
  const response = await page.request.post(`${MOCK_URL}/__identity`, { data: identity });
  expect(response.ok()).toBeTruthy();
}

async function expectNoSensitiveValues(page: Page, forbidden: string[]) {
  const url = page.url();
  const storage = await page.evaluate(() =>
    JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
  );
  for (const value of forbidden) {
    expect(url).not.toContain(value);
    expect(storage).not.toContain(value);
  }
  expect(url).not.toMatch(/[?&](code|state|id_token|access_token|token|email)=/);
}

test.describe("SSO login UI", () => {
  test("unconfigured server shows no SSO button and password login stays usable", async ({ page }) => {
    test.skip(!DISABLED, "needs a backend without OIDC settings (E2E_OIDC_DISABLED=1)");
    await page.goto("/login");
    await expect(page.getByTestId("login-form")).toBeVisible();
    await expect(page.getByTestId("sso-login-button")).toHaveCount(0);
    await expect(page.getByTestId("personal-number-input")).toBeVisible();
  });

  test("configured server shows the SSO button next to password login", async ({ page }) => {
    test.skip(!MOCK_URL, "needs the mock OIDC provider (E2E_OIDC_MOCK_URL)");
    await page.goto("/login");
    await expect(page.getByTestId("sso-login-button")).toBeVisible();
    await expect(page.getByTestId("personal-number-input")).toBeVisible();
    await expect(page.getByTestId("login-submit")).toBeVisible();
  });

  test("a failed SSO callback shows only the generic banner", async ({ page }) => {
    test.skip(!MOCK_URL, "needs the mock OIDC provider (E2E_OIDC_MOCK_URL)");
    // Unverified email: the callback must reject it with the generic error redirect.
    await selectIdentity(page, { subject: "sub-unverified", email: "nobody@corp.example", email_verified: false });
    await page.goto("/login");
    await page.getByTestId("sso-login-button").click();
    await expect(page).toHaveURL(/\/login\?sso_error=1$/);
    await expect(page.getByTestId("sso-error")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("nobody@corp.example");
    await expectNoSensitiveValues(page, ["nobody@corp.example", "sub-unverified"]);
  });
});

test.describe("SSO registration", () => {
  test("an unmatched identity lands on registration with read-only identity and no invite code", async ({ page }) => {
    test.skip(!MOCK_URL, "needs the mock OIDC provider (E2E_OIDC_MOCK_URL)");
    const email = `new.person.${Date.now()}@corp.example`;
    await selectIdentity(page, { subject: `sub-${Date.now()}`, email, email_verified: true });
    await page.goto("/login");
    await page.getByTestId("sso-login-button").click();

    await expect(page).toHaveURL(/\/register\?sso=1$/);
    // Invite step is skipped; the personal-details step is shown directly.
    await expect(page.getByText("פרטים אישיים")).toBeVisible();
    await expect(page.getByLabel("קוד הזמנה")).toHaveCount(0);

    const emailInput = page.getByLabel(/אימייל/);
    await expect(emailInput).toHaveValue(email);
    await expect(emailInput).toHaveAttribute("readonly", "");
    await expect(page.getByTestId("sso-ad-username")).toHaveValue(email.split("@")[0]);
    await expect(page.getByTestId("sso-ad-username")).toHaveAttribute("readonly", "");

    await expectNoSensitiveValues(page, [email]);
  });

  test("plain registration still starts with the invite code", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByLabel("קוד הזמנה")).toBeVisible();
    await expect(page.getByTestId("sso-ad-username")).toHaveCount(0);
  });
});
