import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Dev: Vite on :5173 proxies app API endpoints to FastAPI on :8000.
// Prod: `npm run build` emits ./dist which FastAPI serves directly.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": apiProxyTarget,
        "/healthz": apiProxyTarget,
        "/metrics": apiProxyTarget,
      },
    },
    build: {
      outDir: "dist",
      sourcemap: false,
    },
  };
});
