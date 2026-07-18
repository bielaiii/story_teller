const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/e2e_static",
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4193",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "./scripts/python.sh tests/e2e_v3/serve_static_fixture.py",
    url: "http://127.0.0.1:4193/project.snapshot.json",
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
