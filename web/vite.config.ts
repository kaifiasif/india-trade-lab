import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Built into the Python skill so running the dashboard needs no Node.
export default defineConfig({
  plugins: [react()],
  base: "/",
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "../skills/day-trader-india/assets/observatory",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
});
