import { expect, test, type Page } from "@playwright/test";

// Presses the buttons on every screen, for every role, against the demo seed. Any uncaught error in the page
// (like the blocked window.prompt that broke "Reset password") fails the test.
const PASSWORD = "nyaya-demo-2026";

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function login(page: Page, email: string, password = PASSWORD) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: /email/i }).fill(email);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("admin: reset password really changes the password; every admin button works", async ({ page }) => {
  const errors = watchErrors(page);
  await login(page, "admin@nyayasetu.test");
  await expect(page.getByRole("heading", { name: "Prisoner register" })).toBeVisible();
  // audit log toggles
  await page.getByRole("button", { name: "All entries" }).click();
  await page.getByRole("button", { name: "This session" }).click();
  // run nightly
  await page.getByRole("button", { name: "Run nightly monitoring" }).click();
  await expect(page.getByText(/Recomputed \d+ prisoners/)).toBeVisible();
  // deactivate → confirmation dialog → cancel (nothing changes)
  const farhan = page.locator("tr", { hasText: "lawyer2@nyayasetu.test" });
  await farhan.getByRole("button", { name: "Deactivate" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  await expect(farhan.getByText("active", { exact: true })).toBeVisible();
  // reset password: too short is refused in the dialog, then a real reset
  await farhan.getByRole("button", { name: "Reset password" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.locator("input").fill("short");
  await expect(dlg.getByRole("button", { name: "Reset password" })).toBeDisabled();
  await dlg.locator("input").fill("farhan-new-pass-9");
  await dlg.getByRole("button", { name: "Reset password" }).click();
  await expect(page.getByText("Password reset.")).toBeVisible();
  // legal data verify dialog → cancel
  await page.getByRole("button", { name: "Mark unverified" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await logout(page);
  // the old password no longer works, the new one does
  await page.getByRole("textbox", { name: /email/i }).fill("lawyer2@nyayasetu.test");
  await page.locator('input[autocomplete="current-password"]').fill(PASSWORD);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await expect(page.getByText("Incorrect email or password.")).toBeVisible();
  await login(page, "lawyer2@nyayasetu.test", "farhan-new-pass-9");
  await expect(page.getByRole("heading", { name: "My prisoners" })).toBeVisible();
  await logout(page);
  // restore the demo password
  await login(page, "admin@nyayasetu.test");
  await page.locator("tr", { hasText: "lawyer2@nyayasetu.test" }).getByRole("button", { name: "Reset password" }).click();
  await page.getByRole("dialog").locator("input").fill(PASSWORD);
  await page.getByRole("dialog").getByRole("button", { name: "Reset password" }).click();
  await expect(page.getByText("Password reset.")).toBeVisible();
  // lawyers page: deactivate asks first
  await page.getByRole("link", { name: "Lawyers" }).click();
  await page.locator("tr", { hasText: "lawyer2@nyayasetu.test" }).getByRole("button", { name: "Deactivate" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("link", { name: "Add prisoner" }).click();
  await page.getByRole("button", { name: "Add section" }).click();
  await page.getByRole("button", { name: "Remove" }).first().click();
  expect(errors).toEqual([]);
});

test("lawyer: every tab and case button works", async ({ page }) => {
  const errors = watchErrors(page);
  await login(page, "lawyer@nyayasetu.test");
  for (const f of ["Act now", "Needs review", "All"]) await page.getByRole("button", { name: f, exact: true }).click();
  await page.getByRole("link", { name: "Suresh Kumar" }).filter({ visible: true }).first().click();
  await page.getByRole("button", { name: "Recompute" }).click();
  await expect(page.getByText(/Recomputed from the current records/)).toBeVisible();
  for (const tab of ["Timeline", "Facts & documents", "Defense insights", "Drafts", "Eligibility"]) {
    await page.getByRole("tab", { name: tab }).click();
  }
  // facts: open a document, open the correction dialog, cancel
  await page.getByRole("tab", { name: "Facts & documents" }).click();
  await page.getByRole("button", { name: /arrest memo/ }).first().click();
  await expect(page.getByText(/Extracted facts/)).toBeVisible();
  const correct = page.getByRole("button", { name: "Correct", exact: true }).first();
  if (await correct.isVisible()) {
    await correct.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  }
  // insights: accept then undo
  await page.getByRole("tab", { name: "Defense insights" }).click();
  const accept = page.getByRole("button", { name: "Accept" }).first();
  if (await accept.isVisible()) {
    await accept.click();
    await page.getByRole("button", { name: "Undo" }).first().click();
  }
  // drafts: create, approve, export both formats
  await page.getByRole("tab", { name: "Drafts" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByText(/sentences grounded/)).toBeVisible();
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PDF" }).click();
  expect((await dl).suggestedFilename()).toMatch(/\.pdf$/);
  const dl2 = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export DOCX" }).click();
  expect((await dl2).suggestedFilename()).toMatch(/\.docx$/);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("link", { name: "Alerts" }).click();
  const ack = page.getByRole("button", { name: "Acknowledge" }).first();
  if (await ack.isVisible()) await ack.click();
  expect(errors).toEqual([]);
});

test("jail staff, DLSA and reviewer buttons work", async ({ page }) => {
  const errors = watchErrors(page);
  await login(page, "jail@nyayasetu.test");
  await page.getByRole("link", { name: "Ravi Kumar" }).filter({ visible: true }).first().click();
  for (const b of ["Transfer", "Record release"]) {
    await page.getByRole("button", { name: b, exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  }
  await logout(page);
  await login(page, "dlsa@nyayasetu.test");
  await expect(page.getByText("Overdue undertrials by district")).toBeVisible();
  await page.getByRole("button", { name: "Unassigned", exact: true }).click();
  await page.getByRole("button", { name: "All", exact: true }).click();
  await logout(page);
  await login(page, "reviewer@nyayasetu.test");
  for (const k of ["New prisoners", "Extractions", "Delay attribution", "Identity matches", "Document mismatches", "Document type", "All"]) {
    await page.getByRole("button", { name: k, exact: true }).click();
  }
  await page.getByRole("button", { name: "Scan for duplicate identities" }).click();
  await expect(page.getByText(/candidate pair\(s\) queued/)).toBeVisible();
  const item = page.locator("main ul button").first();
  if (await item.isVisible()) await item.click();
  expect(errors).toEqual([]);
});
