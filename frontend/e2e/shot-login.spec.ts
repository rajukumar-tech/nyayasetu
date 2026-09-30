import { expect, test } from "@playwright/test";

// Captures the sign-in page for review: SCREENSHOTS=1 npx playwright test shot-login
test.skip(!process.env.SCREENSHOTS, "screenshots only on demand");

test("sign-in page", async ({ page }, info) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByText("Demo accounts (synthetic data)")).toBeVisible();
  await page.screenshot({ path: `../docs/screenshots/login-${info.project.name}.png`, fullPage: true });
  await page.getByLabel("Language").selectOption("kn");
  await expect(page.getByRole("heading", { name: "ಲಾಗಿನ್" })).toBeVisible();
  await page.screenshot({ path: `../docs/screenshots/login-${info.project.name}-kn.png`, fullPage: true });
  await page.getByLabel("ಭಾಷೆ").selectOption("en");
});
