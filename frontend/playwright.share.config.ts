import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e/artifacts',
  testMatch: /shared-preview-security\.spec\.ts/,
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://localhost:3001',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : {},
  },
  webServer: {
    command: 'PORT=3001 npm run dev',
    url: 'http://localhost:3001',
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
