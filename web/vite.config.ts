import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
      // The mock layer reads the assessment's own fixtures, so the UI shows
      // real numbers before the API exists and can't drift from the dataset.
      "@data": path.resolve(import.meta.dirname, "../data"),
    },
  },
  server: {
    port: 5173,
    fs: { allow: [path.resolve(import.meta.dirname, ".."), path.resolve(import.meta.dirname)] },
    // The API is served by the Python container in compose; in local dev it's
    // uvicorn on 8000. Same-origin either way, so no CORS config is needed.
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
})
