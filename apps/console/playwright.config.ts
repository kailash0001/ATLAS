import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  use: {
    baseURL: process.env.ATLAS_TEST_URL || "http://127.0.0.1:3100",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  reporter: "list",
});
