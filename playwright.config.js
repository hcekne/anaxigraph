import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/visual",
  timeout: 30_000,
  fullyParallel: false,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.ANAXIGRAPH_VISUAL_URL || "http://127.0.0.1:8765",
    viewport: { width: 1440, height: 1100 },
    colorScheme: "dark",
    reducedMotion: "reduce",
  },
});
