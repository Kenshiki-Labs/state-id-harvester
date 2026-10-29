import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "astro/config";
import { CADASTRE_EDGE_BASE } from "./src/core/edge-catalog.ts";

const catalogEdge = new URL(CADASTRE_EDGE_BASE).origin;

export default defineConfig({
  site: "https://cadastre.kenshikilabs.com",
  output: "static",
  trailingSlash: "never",
  build: { inlineStylesheets: "never" },
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
  markdown: { syntaxHighlight: false },
  security: {
    csp: {
      directives: [
        "default-src 'none'", `connect-src 'self' ${catalogEdge}`, `img-src 'self' data: ${catalogEdge}`,
        "font-src 'self'", "base-uri 'none'", "form-action 'self'",
      ],
    },
  },
});
