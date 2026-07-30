const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/e2e_merge",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4194",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "./scripts/python.sh tests/e2e_merge/serve_fixture.py",
    url: "http://127.0.0.1:4194/api/v1/meta?project=novel",
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
