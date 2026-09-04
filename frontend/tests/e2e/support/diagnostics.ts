import type { Page, TestInfo } from "@playwright/test";

export function installDiagnostics(page: Page, testInfo: TestInfo): void {
  page.on("pageerror", (error) => testInfo.attach("page-error", { body: error.stack ?? error.message, contentType: "text/plain" }));
  page.on("console", (message) => {
    if (message.type() === "error") {
      void testInfo.attach("console-error", { body: message.text(), contentType: "text/plain" });
    }
  });
  page.on("requestfailed", (request) => {
    void testInfo.attach("failed-request", {
      body: `${request.method()} ${request.url()}\n${request.failure()?.errorText ?? "unknown failure"}`,
      contentType: "text/plain",
    });
  });
}
