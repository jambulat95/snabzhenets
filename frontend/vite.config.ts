import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Фронт в разработке: http://localhost:5173. Запросы /api/* Vite передаёт в API (docker compose, порт 8010),
// поэтому для браузера это один сайт: cookie входа работает без CORS.
const api = process.env.API_URL ?? "http://localhost:8010";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: api, changeOrigin: false },
    },
  },
});
