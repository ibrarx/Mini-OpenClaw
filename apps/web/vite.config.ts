import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // Required for SSE: configure the proxy to not buffer responses
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes, req) => {
            // Disable buffering for SSE endpoints so events stream through
            if (
              req.url?.includes("/stream") ||
              proxyRes.headers["content-type"]?.includes("text/event-stream")
            ) {
              proxyRes.headers["cache-control"] = "no-cache";
              proxyRes.headers["x-accel-buffering"] = "no";
            }
          });
        },
      },
    },
  },
});
