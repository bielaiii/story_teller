const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4191",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "python3 tests/e2e/serve_fixture.py",
    url: "http://127.0.0.1:4191/api/capabilities?project=novel",
    timeout: 15_000,
    reuseExistingServer: false,
  },
});
