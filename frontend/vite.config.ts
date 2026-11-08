import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Фронт в разработке: http://localhost:5173. Запросы /api/* Vite передаёт в API (docker compose, порт 8000),
// поэтому для браузера это один сайт: cookie входа и лента событий (SSE) работают без CORS.
// Адрес API можно поменять переменной окружения: API_URL=http://localhost:8000 npm run dev
const api = process.env.API_URL ?? "http://localhost:8000";

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
