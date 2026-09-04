import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("feedback screenshot includes a lower marker from the app scroll container", async ({ page }) => {
  await page.goto("/profile");

  const scrollContainer = page.locator("[data-bug-report-scroll-container]");
  await expect(scrollContainer).toBeVisible();

  await page.locator("[data-bug-report-scroll-content]").evaluate((content) => {
    const marker = document.createElement("div");
    marker.dataset.testid = "feedback-screenshot-lower-marker";
    marker.style.cssText = "margin-top: 1200px; height: 48px; background: rgb(255, 0, 255);";
    content.append(marker);
  });
  await scrollContainer.evaluate((container) => {
    const marker = container.querySelector<HTMLElement>("[data-testid='feedback-screenshot-lower-marker']");
    container.scrollTop = marker!.offsetTop - 120;
  });

  await page.getByTestId("bug-report-trigger").click();
  const screenshot = page.locator("[data-testid='bug-report-modal-overlay'] img");
  await expect(screenshot).toBeVisible({ timeout: 10_000 });

  const lowerMarkerIsCaptured = await screenshot.evaluate(async (image) => {
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d")!;
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index] === 255 && pixels[index + 1] === 0 && pixels[index + 2] === 255) return true;
    }
    return false;
  });

  expect(lowerMarkerIsCaptured).toBe(true);
});
