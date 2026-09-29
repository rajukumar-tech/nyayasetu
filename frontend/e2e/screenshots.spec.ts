import { test, type Page } from "@playwright/test";

// Captures README screenshots: SCREENSHOTS=1 npx playwright test screenshots --project=desktop
test.skip(!process.env.SCREENSHOTS, "screenshots only on demand");
const OUT = "../docs/screenshots";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill("nyaya-demo-2026");
  await page.getByRole("button", { name: /sign in/i }).click();
}

test("capture", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/login");
  await page.screenshot({ path: `${OUT}/login.png` });
  await login(page, "lawyer@nyayasetu.test");
  await page.getByText("Critical: acquitted but detained").filter({ visible: true }).first().waitFor();
  await page.screenshot({ path: `${OUT}/lawyer-dashboard.png` });
  await page.getByRole("link", { name: "Ravi Kumar" }).filter({ visible: true }).first().click();
  await page.getByText("How this was decided").waitFor();
  await page.screenshot({ path: `${OUT}/eligibility.png`, fullPage: true });
  await page.getByRole("tab", { name: "Timeline" }).click();
  await page.getByText("Hearings & delay attribution").waitFor();
  await page.screenshot({ path: `${OUT}/timeline.png` });
  await page.getByRole("tab", { name: "Defense insights" }).click();
  await page.getByText("Produced before Magistrate").first().waitFor();
  await page.screenshot({ path: `${OUT}/defense-insights.png` });
  await page.getByRole("tab", { name: "Drafts" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByText(/sentences grounded/).waitFor();
  await page.screenshot({ path: `${OUT}/draft.png` });
  await page.getByRole("tab", { name: "Facts & documents" }).click();
  await page.getByRole("button", { name: /arrest_memo/ }).click();
  await page.getByText("Extracted facts").waitFor();
  await page.screenshot({ path: `${OUT}/source-highlights.png` });
  await login(page, "dlsa@nyayasetu.test");
  await page.getByText("Overdue undertrials by district").waitFor();
  await page.screenshot({ path: `${OUT}/dlsa.png` });
});
