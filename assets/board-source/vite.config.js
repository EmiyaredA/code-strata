import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: {
    hmr: process.env.CODE_STRATA_DEV_VITE_PORT
      ? { host: '127.0.0.1', clientPort: Number(process.env.CODE_STRATA_DEV_VITE_PORT) }
      : undefined,
  },
  build: { outDir: "../board", emptyOutDir: true },
});
