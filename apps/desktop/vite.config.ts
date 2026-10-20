import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Production CSP (meta tag). Dev keeps Vite's HMR working, so the strict policy applies to built files only.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "media-src 'self' blob:",
  "connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join("; ");

const csp = (): Plugin => ({
  name: "zonic-csp",
  apply: "build",
  transformIndexHtml: (html) => html.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`),
});

export default defineConfig({
  base: "./",
  plugins: [react(), csp()],
  server: { port: 5173, strictPort: true, host: "127.0.0.1" },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1200 },
  test: { environment: "node", include: ["src/**/*.test.ts", "electron/**/*.test.ts"] },
});
