import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Directory from "../src/components/Directory";
import { normalizeCatalog } from "../src/lib/catalog-model";
import data from "../public/data/catalog.json";
import homepage from "../src/pages/index.astro?raw";
import directoryPage from "../src/pages/catalog/index.astro?raw";

describe("document navigation and page boundaries", () => {
  it("keeps the home page free of the catalog, image fetches and research workspace", () => {
    expect(homepage).not.toMatch(/client:|<Catalog|<Collection|useSpecimens|reference-grid|state-detail|id="catalog"/);
    for (const route of ["/catalog", "/catalog/federal", "/method"]) expect(homepage).toContain(`href="${route}"`);
  });
  it("renders all jurisdiction links before hydration without embedding images or extracted records", () => {
    const html = renderToStaticMarkup(createElement(Directory, { rows: normalizeCatalog(data) }));
    const links = [...html.matchAll(/href="(\/catalog\/[a-z]{2})"/g)].map((match) => match[1]);
    expect(new Set(links).size).toBe(51);
    expect(links).toContain("/catalog/wa");
    expect(links).toContain("/catalog/dc");
    expect(html).not.toMatch(/<img|Source SHA-256|reference-provenance|api_key|<button/);
    expect(directoryPage).not.toMatch(/<Collection|<CatalogDetail|<FederalCatalog|useSpecimens/);
  });
});
