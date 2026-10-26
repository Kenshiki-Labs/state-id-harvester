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
  it("renders jurisdiction links and decorative state artwork before hydration without extracted records", () => {
    const rows = normalizeCatalog(data);
    const html = renderToStaticMarkup(createElement(Directory, { rows }));
    const links = [...html.matchAll(/href="(\/catalog\/[a-z]{2})"/g)].map((match) => match[1]);
    expect(new Set(links).size).toBe(51);
    expect(links).toContain("/catalog/wa");
    expect(links).toContain("/catalog/dc");
    const artwork = [...html.matchAll(/<img[^>]+src="([^"]+)"[^>]*>/g)];
    expect(artwork.map((match) => match[1])).toEqual(rows.map((row) => `/artwork/states/${row.code}.svg`));
    for (const image of artwork) {
      expect(image[0]).toContain('alt=""');
      expect(image[0]).toContain('width="80" height="80"');
      expect(image[0]).toContain('loading="lazy"');
    }
    expect(html).not.toMatch(/\/v1\/specimens\/|Source SHA-256|reference-provenance|api_key|<button/);
    expect(directoryPage).not.toMatch(/<Collection(?:\s|>)|<CatalogDetail|<FederalCatalog|useSpecimens/);
  });
});
