import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:8765',
    viewport: { width: 1920, height: 1080 },
    colorScheme: 'dark',
    reducedMotion: 'reduce',
  },
  webServer: {
    command: 'PYTHONPATH=../src python3 -m audio_competition_agents --mode mock serve --host 127.0.0.1 --port 8765',
    url: 'http://127.0.0.1:8765/api/health',
    reuseExistingServer: true,
    timeout: 20_000,
  },
})
