import { expect, test, type Page } from "@playwright/test";

// Captures the README screenshots from the default demo seed (Ravi Kumar + Suresh Kumar):
//   SCREENSHOTS=1 PW_CHANNEL=chrome npx playwright test screenshots --project=desktop
test.skip(!process.env.SCREENSHOTS, "screenshots only on demand");
const OUT = "../docs/screenshots";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: /email/i }).fill(email);
  await page.locator('input[autocomplete="current-password"]').fill("nyaya-demo-2026");
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function logout(page: Page) {
  await page.getByRole("button", { name: /Sign out|ಲಾಗ್ ಔಟ್|साइन आउट/ }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("capture", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/login");
  await expect(page.getByText("Demo accounts (synthetic data)")).toBeVisible();
  await page.screenshot({ path: `${OUT}/login.png` });

  // lawyer: dashboard, the two demo prisoners, timeline, documents, insights, draft
  await login(page, "lawyer@nyayasetu.test");
  await expect(page.getByRole("link", { name: "Suresh Kumar" }).first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/lawyer-dashboard.png` });
  await page.getByRole("link", { name: "Ravi Kumar" }).filter({ visible: true }).first().click();
  await expect(page.getByText(/242 < 366/)).toBeVisible();
  await page.screenshot({ path: `${OUT}/not-eligible.png`, fullPage: true });
  await page.goBack();
  await page.getByRole("link", { name: "Suresh Kumar" }).filter({ visible: true }).first().click();
  await expect(page.getByText(/961 ≥ 853/)).toBeVisible();
  await page.screenshot({ path: `${OUT}/eligibility.png`, fullPage: true });
  await page.getByRole("tab", { name: "Timeline" }).click();
  await page.getByText("Hearings & delay attribution").first().waitFor();
  await page.screenshot({ path: `${OUT}/timeline.png` });
  await page.getByRole("tab", { name: "Facts & documents" }).click();
  await page.getByRole("button", { name: /arrest memo/ }).first().click();
  await page.getByText(/Extracted facts/).waitFor();
  await page.screenshot({ path: `${OUT}/source-highlights.png` });
  await page.getByRole("tab", { name: "Defense insights" }).click();
  await page.getByText("Evidence in the record").first().waitFor();
  await page.screenshot({ path: `${OUT}/defense-insights.png` });
  await page.getByRole("tab", { name: "Drafts" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByText(/sentences grounded/).waitFor();
  await page.screenshot({ path: `${OUT}/draft.png` });
  // Kannada and Hindi
  await page.getByRole("tab", { name: "Eligibility" }).click();
  await page.getByRole("combobox").first().selectOption("kn");
  await expect(page.getByText(/961 ≥ 853/)).toBeVisible();
  await page.screenshot({ path: `${OUT}/kannada.png` });
  await page.getByRole("combobox").first().selectOption("hi");
  await expect(page.getByText(/961 ≥ 853/)).toBeVisible();
  await page.screenshot({ path: `${OUT}/hindi.png` });
  await page.getByRole("combobox").first().selectOption("en");
  await logout(page);

  // admin: dashboard (register, audit log)
  await login(page, "admin@nyayasetu.test");
  await expect(page.getByRole("heading", { name: "Prisoner register" })).toBeVisible();
  await page.screenshot({ path: `${OUT}/admin.png` });
  await logout(page);

  // reviewer
  await login(page, "reviewer@nyayasetu.test");
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  await page.getByRole("button", { name: "Delay attribution", exact: true }).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/reviewer.png` });
  await logout(page);

  // DLSA
  await login(page, "dlsa@nyayasetu.test");
  await page.getByText("Overdue undertrials by district").waitFor();
  await page.screenshot({ path: `${OUT}/dlsa.png` });
});
