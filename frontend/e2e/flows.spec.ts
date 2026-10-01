import { expect, test, type Page } from "@playwright/test";

// Runs against the default demo seed (python -m app.seed --reset): Ravi Kumar (not eligible), Suresh Kumar (eligible).
const PASSWORD = "nyaya-demo-2026"; // seeded local demo accounts (see backend/app/seed.py)

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
}

async function open(page: Page, name: string) {
  await page.getByRole("link", { name }).filter({ visible: true }).first().click();
  await expect(page.getByRole("heading", { name: new RegExp(name) })).toBeVisible();
}

test("Ravi Kumar is not eligible and the calculation is shown", async ({ page }) => {
  await login(page, "lawyer@nyayasetu.test");
  await expect(page.getByRole("heading", { name: "My prisoners" })).toBeVisible();
  await open(page, "Ravi Kumar");
  await expect(page.getByText("Not yet eligible").first()).toBeVisible();
  await expect(page.getByText(/Counted detention: 263 − 21 = 242 days/)).toBeVisible();
  await expect(page.getByText(/242 < 366: 124 more days needed/)).toBeVisible();
  await expect(page.getByText("Default bail — BNSS s.187(3)")).toBeVisible();
});

test("Suresh Kumar is eligible, with threshold and eligibility date", async ({ page }) => {
  await login(page, "lawyer@nyayasetu.test");
  await open(page, "Suresh Kumar");
  await expect(page.getByText("Eligible (479)").first()).toBeVisible();
  await expect(page.getByText(/Counted detention: 991 − 30 = 961 days/)).toBeVisible();
  await expect(page.getByText(/961 ≥ 853: the threshold was reached on .*; 108 counted days beyond it/)).toBeVisible();
  await page.getByRole("tab", { name: "Drafts" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByText(/sentences grounded; 0 rejected/)).toBeVisible();
});

test("jail staff: no Defense Insights, no document upload, superintendent's application available", async ({ page }) => {
  await login(page, "jail@nyayasetu.test");
  await open(page, "Suresh Kumar");
  await expect(page.getByRole("tab", { name: "Defense insights" })).toHaveCount(0);
  await expect(page.getByText("Upload document")).toHaveCount(0);
  await page.getByRole("tab", { name: "Drafts" }).click();
  await expect(page.getByText("Prepare superintendent's application")).toBeVisible();
});

test("admin sees only technical work", async ({ page }) => {
  await login(page, "admin@nyayasetu.test");
  const nav = page.getByRole("navigation");
  await expect(nav.getByRole("link")).toHaveText(["Admin"]);
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  await expect(page.getByText("Suresh Kumar")).toHaveCount(0); // no prisoners at all on the admin's screen
  await page.goto("/prisoners/new");
  await expect(page.getByText("Your role cannot open this page.")).toBeVisible();
  await page.goto("/lawyers");
  await expect(page.getByText("Your role cannot open this page.")).toBeVisible();
});

test("jail staff add prisoners; the DLSA manages lawyers", async ({ page }) => {
  await login(page, "jail@nyayasetu.test");
  await expect(page.getByRole("navigation").getByRole("link")).toHaveText(["Prisoners", "Add prisoner", "Alerts"]);
  await page.getByRole("button", { name: "Sign out" }).click();
  await login(page, "dlsa@nyayasetu.test");
  await expect(page.getByRole("navigation").getByRole("link")).toHaveText(["District", "Lawyers", "Alerts"]);
});

test("another lawyer cannot open the prisoner by URL", async ({ page }) => {
  await login(page, "lawyer@nyayasetu.test");
  await open(page, "Suresh Kumar");
  const url = page.url();
  await page.getByRole("button", { name: "Sign out" }).click();
  await login(page, "lawyer2@nyayasetu.test");
  await expect(page.getByText(/No prisoners are assigned to you yet/)).toBeVisible();
  await page.goto(url);
  await expect(page.getByText("Record not found, or not available to your account.")).toBeVisible();
  await expect(page.getByText("Suresh Kumar")).toHaveCount(0);
});

test("interface switches to Kannada and Hindi", async ({ page }) => {
  await login(page, "lawyer@nyayasetu.test");
  await page.getByLabel("Language").selectOption("kn");
  await expect(page.getByRole("heading", { name: "ನನ್ನ ಕೈದಿಗಳು" })).toBeVisible();
  await page.getByLabel("ಭಾಷೆ").selectOption("hi");
  await expect(page.getByRole("heading", { name: "मेरे बंदी" })).toBeVisible();
  await open(page, "Ravi Kumar");
  await expect(page.getByText(/गिनी गई हिरासत: 263 − 21 = 242 दिन/)).toBeVisible();
  await page.getByLabel("भाषा").selectOption("en");
});

test("no horizontal scroll on key pages", async ({ page }) => {
  await login(page, "lawyer@nyayasetu.test");
  await expect(page.getByRole("heading", { name: "My prisoners" })).toBeVisible();
  for (const lang of ["en", "kn", "hi"]) {
    await page.getByRole("combobox").first().selectOption(lang);
    await open(page, "Suresh Kumar");
    const w = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(w[0]).toBeLessThanOrEqual(w[1]);
    await page.goBack();
  }
  await page.getByRole("combobox").first().selectOption("en");
});
