import { defineConfig, devices } from "@playwright/test";

/** Expects the API (seeded, demo mode) on NYAYA_API_URL and runs the web app itself. */
const API = process.env.NYAYA_API_URL ?? "http://localhost:8000";

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  workers: 1,
  expect: { timeout: 20_000 },
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000/login",
    reuseExistingServer: true,
    env: { NEXT_PUBLIC_API_URL: API },
    timeout: 120_000,
  },
});
