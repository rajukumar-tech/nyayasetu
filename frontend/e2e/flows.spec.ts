import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "nyaya-demo-2026"; // seeded local demo accounts (see backend/app/seed.py)

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
}

test("lawyer sees prisoners by urgency and opens an eligible case", async ({ page }) => {
  await login(page, "lawyer@nyayasetu.test");
  await expect(page.getByRole("heading", { name: "My prisoners" })).toBeVisible();
  await expect(page.getByText("Critical: acquitted but detained").filter({ visible: true }).first()).toBeVisible();
  await page.getByRole("link", { name: "Ravi Kumar" }).filter({ visible: true }).first().click();
  await expect(page.getByText("s/o Ramaiah")).toBeVisible();
  await expect(page.getByText("How this was decided")).toBeVisible();
  await expect(page.getByText(/eligible to apply/i).first()).toBeVisible();
});

test("lawyer uses Defense Insights to generate a grounded application", async ({ page }) => {
  await login(page, "lawyer@nyayasetu.test");
  await page.getByRole("link", { name: "Ravi Kumar" }).filter({ visible: true }).first().click();
  await page.getByRole("tab", { name: "Defense insights" }).click();
  const card = page.locator("section", { hasText: "Produced before Magistrate" });
  await expect(card).toBeVisible();
  await expect(card.getByText(/arrest_memo p\.1/)).toBeVisible();
  if (await card.getByRole("button", { name: "Accept" }).isVisible()) await card.getByRole("button", { name: "Accept" }).click();
  await page.getByRole("tab", { name: "Drafts" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByText(/100% of \d+ sentences grounded; 0 rejected/)).toBeVisible();
  await expect(page.getByText(/Produced before Magistrate after/).filter({ visible: true }).last()).toBeVisible();
});

test("jail staff cannot see Defense Insights but can prepare the superintendent's application", async ({ page }) => {
  await login(page, "jail@nyayasetu.test");
  await expect(page.getByText(/eligible for release or overdue/)).toBeVisible();
  await page.getByRole("link", { name: "Ravi Kumar" }).filter({ visible: true }).first().click();
  await expect(page.getByText("How this was decided")).toBeVisible();
  await expect(page.getByRole("tab", { name: "Defense insights" })).toHaveCount(0);
  await page.getByRole("tab", { name: "Drafts" }).click();
  await expect(page.getByText("Prepare superintendent's application")).toBeVisible();
});

test("interface switches to Kannada", async ({ page }) => {
  await login(page, "lawyer@nyayasetu.test");
  await page.getByLabel("Language").selectOption("kn");
  await expect(page.getByRole("heading", { name: "ನನ್ನ ಕೈದಿಗಳು" })).toBeVisible();
  await page.getByLabel("ಭಾಷೆ").selectOption("en");
});

test("no horizontal scroll on key pages", async ({ page }) => {
  await login(page, "lawyer@nyayasetu.test");
  await expect(page.getByRole("heading", { name: "My prisoners" })).toBeVisible();
  const w = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(w[0]).toBeLessThanOrEqual(w[1]);
});
