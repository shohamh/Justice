import { expect, test, type Browser, type BrowserContext } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { journeyActorStorageState, roleStorageState } from "./fixtures/auth";

const resourceId = "00000000-0000-4000-8000-000000000001";
const fileId = "00000000-0000-4000-8000-000000000002";
const attachmentId = "00000000-0000-4000-8000-000000000003";
const commentId = "00000000-0000-4000-8000-000000000004";
const fixtureDirectory = dirname(fileURLToPath(import.meta.url));
const workbookPath = resolve(fixtureDirectory, "fixtures/storage-import.xlsx");
const workbookName = "storage-import.xlsx";
const pngBytes = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL+WQAAAABJRU5ErkJggg==",
  "base64",
);

const protectedDownloads = [
  ["exemption request file", `/api/file-download/exemption-requests/${resourceId}/files/${fileId}`],
  ["exemption file", `/api/file-download/exemptions/${resourceId}/files/${fileId}`],
  ["gimelim attachment", `/api/file-download/gimelim/${resourceId}/attachments/${attachmentId}`],
  ["bug report screenshot", `/api/file-download/bug-reports/${resourceId}/screenshot`],
  [
    "bug report comment attachment",
    `/api/file-download/bug-reports/${resourceId}/comments/${commentId}/attachments/${attachmentId}`,
  ],
  ["Excel import workbook", `/api/file-download/import-sessions/${resourceId}/workbook`],
] as const;

async function authenticatedContext(
  browser: Browser,
  baseURL: string,
  storageState: string,
): Promise<BrowserContext> {
  return browser.newContext({ baseURL, storageState });
}

async function accessToken(context: BrowserContext): Promise<string> {
  // Refresh cookies are same-origin browser state. APIRequestContext does not
  // reliably share the browser's cookie jar on every supported Playwright
  // setup, so obtain the short-lived access token through the app origin.
  const page = await context.newPage();
  try {
    await page.goto("/");
    const result = await page.evaluate(async () => {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "include",
      });
      return {
        status: response.status,
        accessToken: response.ok
          ? ((await response.json()) as { access_token: string }).access_token
          : null,
      };
    });
    expect(result.status).toBe(200);
    if (!result.accessToken) throw new Error("Refresh response did not include an access token.");
    return result.accessToken;
  } finally {
    await page.close();
  }
}

async function expectBrowserDownload(
  context: BrowserContext,
  token: string,
  path: string,
  expectedName: string,
  expectedBytes: Buffer,
): Promise<void> {
  const page = await context.newPage();
  await page.goto("/");
  const downloaded = await page.evaluate(
    async ({ downloadPath, accessTokenValue }) => {
      const response = await fetch(downloadPath, {
        headers: { Authorization: `Bearer ${accessTokenValue}` },
      });
      const bytes = new Uint8Array(await response.arrayBuffer());
      return {
        status: response.status,
        disposition: response.headers.get("content-disposition"),
        error: response.ok ? null : new TextDecoder().decode(bytes),
        bytes: Array.from(bytes),
      };
    },
    { downloadPath: path, accessTokenValue: token },
  );
  if (downloaded.status !== 200) {
    throw new Error(
      `Download returned HTTP ${downloaded.status}; gateway detail: ${downloaded.error ?? "<empty>"}`,
    );
  }
  expect(downloaded.disposition).toContain(`filename="${expectedName}"`);
  expect(Buffer.from(downloaded.bytes)).toEqual(expectedBytes);
  await page.close();
}

const isolatedStorageE2E = process.env.STORAGE_E2E_ISOLATED === "1";

test.describe("file download gateway", () => {
  for (const [label, path] of protectedDownloads) {
    test(`denies an anonymous request for a ${label}`, async ({ request }) => {
      const response = await request.get(path);

      expect(response.status()).toBe(401);
      expect(response.headers()["content-type"]).toContain("application/json");
    });
  }

  test("downloads a real bug report screenshot and comment attachment only for their owner", async ({
    browser,
    baseURL,
  }) => {
    test.skip(!isolatedStorageE2E, "Persistent upload coverage runs only in the disposable Task 8 Compose project.");
    if (!baseURL) throw new Error("Playwright baseURL is required");

    const owner = await authenticatedContext(browser, baseURL, roleStorageState("soldier"));
    const other = await authenticatedContext(
      browser,
      baseURL,
      journeyActorStorageState("constrainedSoldier"),
    );
    const admin = await authenticatedContext(browser, baseURL, roleStorageState("admin"));
    try {
      const ownerToken = await accessToken(owner);
      const otherToken = await accessToken(other);
      const adminToken = await accessToken(admin);
      const ownerHeaders = { Authorization: `Bearer ${ownerToken}` };
      const otherHeaders = { Authorization: `Bearer ${otherToken}` };
      const adminHeaders = { Authorization: `Bearer ${adminToken}` };
      const description = `storage-e2e-${Date.now()}`;
      const created = await owner.request.post("/api/bug-reports", {
        data: {
          description,
          severity: "low",
          route: "/settings",
          screenshot: pngBytes.toString("base64"),
        },
        headers: ownerHeaders,
      });
      expect(created.status()).toBe(201);

      const reportsResponse = await owner.request.get("/api/my/bug-reports", {
        headers: ownerHeaders,
      });
      expect(reportsResponse.status()).toBe(200);
      const reports = await reportsResponse.json();
      const report = reports.items.find((item: { description: string }) => item.description === description);
      expect(report).toBeDefined();
      const reportId = report.id as string;

      const commentResponse = await owner.request.post(`/api/bug-reports/${reportId}/comments`, {
        data: { body: "Storage download E2E attachment." },
        headers: ownerHeaders,
      });
      expect(commentResponse.status()).toBe(201);
      const comment = await commentResponse.json();

      const attachmentResponse = await owner.request.post(
        `/api/bug-reports/${reportId}/comments/${comment.id}/attachments`,
        {
          multipart: {
            file: {
              name: "storage-e2e.png",
              mimeType: "image/png",
              buffer: pngBytes,
            },
          },
          headers: ownerHeaders,
        },
      );
      expect(attachmentResponse.status()).toBe(201);
      const attachment = await attachmentResponse.json();

      await expectBrowserDownload(
        owner,
        ownerToken,
        `/api/file-download/bug-reports/${reportId}/screenshot`,
        `screenshot-${reportId}.png`,
        pngBytes,
      );
      await expectBrowserDownload(
        owner,
        ownerToken,
        `/api/file-download/bug-reports/${reportId}/comments/${comment.id}/attachments/${attachment.id}`,
        "storage-e2e.png",
        pngBytes,
      );

      const denied = await other.request.get(`/api/file-download/bug-reports/${reportId}/screenshot`, {
        headers: otherHeaders,
      });
      expect([403, 404]).toContain(denied.status());

      const typesResponse = await owner.request.get("/api/auth/exemption-types", {
        headers: ownerHeaders,
      });
      expect(typesResponse.status()).toBe(200);
      const exemptionTypes = await typesResponse.json();
      expect(exemptionTypes.length).toBeGreaterThan(0);
      const requestFileBytes = Buffer.from("%PDF-1.7\nstorage e2e request file\n%%EOF\n");
      const exemptionRequestResponse = await owner.request.post("/api/me/exemption-requests", {
        multipart: {
          payload: JSON.stringify({
            exemption_type_id: exemptionTypes[0].id,
            start_date: "2026-09-29",
            reason: "Storage E2E file permission check",
          }),
          files: {
            name: "storage-e2e.pdf",
            mimeType: "application/pdf",
            buffer: requestFileBytes,
          },
        },
        headers: ownerHeaders,
      });
      expect(exemptionRequestResponse.status()).toBe(201);
      const exemptionRequest = await exemptionRequestResponse.json();
      expect(exemptionRequest.files).toHaveLength(1);
      const requestFile = exemptionRequest.files[0];
      await expectBrowserDownload(
        owner,
        ownerToken,
        `/api/file-download/exemption-requests/${exemptionRequest.id}/files/${requestFile.id}`,
        requestFile.file_name,
        requestFileBytes,
      );
      const requestFileDenied = await other.request.get(
        `/api/file-download/exemption-requests/${exemptionRequest.id}/files/${requestFile.id}`,
        { headers: otherHeaders },
      );
      expect([403, 404]).toContain(requestFileDenied.status());

      const exemption = await admin.request.post(
        `/api/soldiers/${report.reporter_id}/exemptions`,
        {
          data: {
            exemption_type_id: exemptionTypes[0].id,
            start_date: "2026-09-30",
            reason: "Storage E2E soldier exemption attachment",
            is_medical: false,
          },
          headers: adminHeaders,
        },
      );
      expect(exemption.status()).toBe(201);
      const exemptionData = await exemption.json();
      const exemptionFileBytes = Buffer.from("%PDF-1.7\nstorage e2e exemption file\n%%EOF\n");
      const exemptionFileResponse = await admin.request.post(
        `/api/soldiers/${report.reporter_id}/exemptions/${exemptionData.id}/files`,
        {
          multipart: {
            file: {
              name: "storage-exemption.pdf",
              mimeType: "application/pdf",
              buffer: exemptionFileBytes,
            },
          },
          headers: adminHeaders,
        },
      );
      expect(exemptionFileResponse.status()).toBe(201);
      const exemptionFile = await exemptionFileResponse.json();
      await expectBrowserDownload(
        owner,
        ownerToken,
        `/api/file-download/exemptions/${exemptionData.id}/files/${exemptionFile.id}`,
        exemptionFile.file_name,
        exemptionFileBytes,
      );
      const exemptionFileDenied = await other.request.get(
        `/api/file-download/exemptions/${exemptionData.id}/files/${exemptionFile.id}`,
        { headers: otherHeaders },
      );
      expect([403, 404]).toContain(exemptionFileDenied.status());

      const gimelimDismissalId = process.env.STORAGE_E2E_GIMELIM_DISMISSAL_ID;
      if (!gimelimDismissalId) throw new Error("The isolated gimelim fixture was not provided.");
      const gimelimOwner = await authenticatedContext(
        browser,
        baseURL,
        journeyActorStorageState("assignedGimelim"),
      );
      try {
        const gimelimToken = await accessToken(gimelimOwner);
        const gimelimHeaders = { Authorization: `Bearer ${gimelimToken}` };
        const webpBytes = Buffer.from([
          0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50, 0x66, 0x61, 0x6b, 0x65,
        ]);
        const attachmentResponse = await gimelimOwner.request.post(
          `/api/gimelim/${gimelimDismissalId}/attachments`,
          {
            multipart: {
              file: {
                name: "storage-gimelim.webp",
                mimeType: "image/webp",
                buffer: webpBytes,
              },
            },
            headers: gimelimHeaders,
          },
        );
        expect(attachmentResponse.status()).toBe(201);
        const gimelimAttachment = await attachmentResponse.json();
        await expectBrowserDownload(
          gimelimOwner,
          gimelimToken,
          `/api/file-download/gimelim/${gimelimDismissalId}/attachments/${gimelimAttachment.id}`,
          gimelimAttachment.file_name,
          webpBytes,
        );
        const gimelimDenied = await other.request.get(
          `/api/file-download/gimelim/${gimelimDismissalId}/attachments/${gimelimAttachment.id}`,
          { headers: otherHeaders },
        );
        expect([403, 404]).toContain(gimelimDenied.status());
      } finally {
        await gimelimOwner.close();
      }
    } finally {
      await owner.close();
      await other.close();
      await admin.close();
    }
  });

  test("uploads, reparses, and downloads the same Excel workbook", async ({ browser, baseURL }) => {
    test.skip(!isolatedStorageE2E, "Persistent upload coverage runs only in the disposable Task 8 Compose project.");
    if (!baseURL) throw new Error("Playwright baseURL is required");

    const admin = await authenticatedContext(browser, baseURL, roleStorageState("admin"));
    const other = await authenticatedContext(browser, baseURL, roleStorageState("soldier"));
    try {
      const adminToken = await accessToken(admin);
      const otherToken = await accessToken(other);
      const adminHeaders = { Authorization: `Bearer ${adminToken}` };
      const otherHeaders = { Authorization: `Bearer ${otherToken}` };
      const workbook = await readFile(workbookPath);
      const uploaded = await admin.request.post("/api/import/sessions", {
        multipart: {
          file: {
            name: workbookName,
            mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            buffer: workbook,
          },
        },
        headers: adminHeaders,
      });
      const uploadStatus = uploaded.status();
      const uploadDetail = uploadStatus === 200 ? "" : await uploaded.text();
      expect(uploadStatus, `Excel upload returned HTTP ${uploadStatus}: ${uploadDetail}`).toBe(200);
      const sessionId = (await uploaded.json()).session_id as string;

      const reparsed = await admin.request.post(`/api/import/sessions/${sessionId}/reparse`, {
        headers: adminHeaders,
      });
      expect(reparsed.status()).toBe(200);
      expect((await reparsed.json()).id).toBe(sessionId);

      await expectBrowserDownload(
        admin,
        adminToken,
        `/api/file-download/import-sessions/${sessionId}/workbook`,
        workbookName,
        workbook,
      );
      const denied = await other.request.get(
        `/api/file-download/import-sessions/${sessionId}/workbook`,
        { headers: otherHeaders },
      );
      expect([403, 404]).toContain(denied.status());
    } finally {
      await admin.close();
      await other.close();
    }
  });
});
