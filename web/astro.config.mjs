import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "astro/config";

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
        "default-src 'none'", "connect-src 'self'", "img-src 'self' data:",
        "font-src 'self'", "base-uri 'none'", "form-action 'self'",
      ],
    },
  },
});
