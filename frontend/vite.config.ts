import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // fs.allow: the development samples read the hand-made fixtures in ../tests/fixtures.
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
    fs: { allow: [".."] },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    css: false,
  },
});
