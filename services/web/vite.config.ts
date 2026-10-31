import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development Vite forwards /api to FastAPI, the same way nginx will in the container.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8010",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
