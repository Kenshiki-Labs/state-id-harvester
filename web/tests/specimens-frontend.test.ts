import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import homepage from "../src/pages/index.astro?raw";
import accessPage from "../src/pages/access.astro?raw";
import SpecimenGallery from "../src/components/SpecimenGallery";
import { joinNormalizations, loadNormalizations, parseNormalizations, loadSpecimens, parseSpecimens, specimenUrl, type GalleryState } from "../src/lib/specimens";
const specimen = { id: "reference_01", state: "WA", source_sha256: "a".repeat(64), asset_sha256: "b".repeat(64), review_status: "reference_only" as const };
const ready: GalleryState = { items: [specimen, { ...specimen, state: "US_FED" }], loading: false, error: false, retry: () => {} };
const render = (gallery = ready, sources = [] as { title: string; url: string; hostname: string; relevance: "candidate"; sha256: string }[], state = "WA") => renderToStaticMarkup(createElement(SpecimenGallery, { gallery, sources, state, name: "Washington" }));

describe("public image metadata boundary", () => {
  it("accepts state and federal references while stripping private storage fields", () => {
    const items = parseSpecimens({ specimens: [{ ...specimen, key: "private/object.png", unexpected: "ignored" }, { ...specimen, state: "US_FED" }] });
    expect(items).toEqual(ready.items);
    expect(specimenUrl(items[0])).toBe("/v1/specimens/WA/reference_01");
  });
  it.each([null, {}, { specimens: {} }, { specimens: [specimen, specimen] }])("rejects unavailable or ambiguous index %j", (value) => { expect(() => parseSpecimens(value)).toThrow(); });
  it("bounds metadata response size", () => { expect(() => parseSpecimens({ specimens: new Array(10001).fill(specimen) })).toThrow(); });
  it.each([{ id: "../private" }, { id: 'x\" onerror=\"alert(1)' }, { state: "ZZ" }, { state: "__proto__" }, { source_sha256: "not a fingerprint" }, { asset_sha256: null }, { review_status: "accepted" }])("rejects hostile reference fields %j", (fields) => { expect(() => parseSpecimens({ specimens: [{ ...specimen, ...fields }] })).toThrow(); });
  it("loads images anonymously and passes cancellation to the request", async () => {
    const signal = new AbortController().signal;
    const transport = vi.fn(async () => Response.json({ specimens: [specimen] })) as unknown as typeof fetch;
    expect(await loadSpecimens(signal, transport)).toEqual([specimen]);
    expect(transport).toHaveBeenCalledWith("/v1/specimens", { signal, credentials: "omit" });
  });
  it("propagates failed HTTP and malformed responses instead of inventing an empty gallery", async () => {
    for (const response of [new Response("private diagnostics", { status: 503 }), Response.json({ specimens: [{ ...specimen, id: "../secret" }] })]) {
      await expect(loadSpecimens(new AbortController().signal, (async () => response) as typeof fetch)).rejects.toThrow();
    }
  });
});
describe("public gallery rendering", () => {
  it("limits images to the selected collection, opens a dialog and escapes source titles", () => {
    const html = render(ready, [{ title: '<script>alert("source")</script>', url: "https://agency.gov/guide.pdf", hostname: "agency.gov", relevance: "candidate", sha256: specimen.source_sha256 }]);
    expect(html).toContain('src="/v1/specimens/WA/reference_01"');
    expect(html).toContain('aria-haspopup="dialog"');
    expect(html).not.toContain('href="/v1/specimens/');
    expect(html).not.toContain("/v1/specimens/US_FED/");
    expect(html).toContain('target="_blank" rel="noopener noreferrer"');
    expect(html).toContain('alt="Washington source reference 1; research specimen, review pending"');
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).toContain(specimen.source_sha256);
    expect(html).toContain(specimen.asset_sha256);
    expect(html).toContain('href="https://agency.gov/guide.pdf"');
    expect(render(ready, [], "US_FED")).toContain('src="/v1/specimens/US_FED/reference_01"');
  });
  it("shows loading and retrieval errors without stale images or false coverage counts", () => {
    const loading = render({ ...ready, loading: true });
    expect(loading).toContain('<output class="reference-message">Loading reference images…</output>');
    expect(loading).not.toContain("<img");
    const error = render({ ...ready, error: true });
    expect(error).toContain('role="alert"');
    expect(error).toContain("Try again");
    expect(error).not.toContain("0 available");
    expect(error).not.toContain("<img");
  });
  it("reports a publication gap separately from a missing source citation", () => {
    expect(render({ ...ready, items: [] })).toContain("No reference images are published");
    expect(render()).toContain("A matching citation is not available");
  });
  it("removes the visitor application and directs legacy entry to the catalog", () => {
    const page = homepage;
    expect(page).not.toMatch(/AccessForm|Request access|DNS TXT|restricted research materials/i);
    expect(accessPage).toContain('Astro.redirect("/catalog", 301)');
  });
});

describe("ID-1 display identity boundary", () => {
  const normalized = { ...specimen, asset_sha256: "c".repeat(64), original_reference_sha256: specimen.asset_sha256, canonical_asset_sha256: "d".repeat(64), width_px: 4280, height_px: 2699, boundary_basis: "visual_native_extent" as const };
  it("joins only the exact original identity and defaults its thumbnail to ID-1", () => {
    const rows = joinNormalizations([specimen], parseNormalizations({ specimens: [{ ...normalized, key: "private" }] }));
    expect(rows[0].normalization).toEqual(normalized);
    expect(rows[0].asset_sha256).toBe(specimen.asset_sha256);
    const html = render({ ...ready, items: rows, normalizationStatus: "ready" });
    expect(html).toContain('src="/v1/id1-normalizations/WA/reference_01"');
    expect(html).toContain("ID-1 normalized");
    expect(html).toContain(`<dt>Image SHA-256</dt><dd>${normalized.asset_sha256}</dd>`);
    expect(html).toContain(`<dt>Original image SHA-256</dt><dd>${specimen.asset_sha256}</dd>`);
    expect(html).not.toContain(`<dt>Image SHA-256</dt><dd>${specimen.asset_sha256}</dd>`);
    expect(html).not.toContain(`<dt>Original image SHA-256</dt><dd>${normalized.asset_sha256}</dd>`);
    expect(html).toContain("Native image extent (approximate)");
    expect(html).toContain("4280 × 2699 px");
    expect(html).not.toContain("private");
  });
  it("labels visually identified card corners independently of the native extent basis", () => {
    const items = joinNormalizations([specimen], [{ ...normalized, boundary_basis: "visual_card_corners" }]);
    expect(render({ ...ready, items })).toContain("Visually identified card corners");
  });
  it.each([{ id: "other" }, { state: "OR" }, { source_sha256: "e".repeat(64) }, { original_reference_sha256: "e".repeat(64) }])("rejects mismatched normalization %j", (change) => {
    expect(joinNormalizations([specimen], [{ ...normalized, ...change }])[0].normalization).toBeUndefined();
  });
  it.each([{ state: "US_FED" }, { canonical_asset_sha256: "bad" }, { original_reference_sha256: null }, { width_px: 856 }, { height_px: 2700 }, { boundary_basis: "automatic" }])("rejects invalid normalized metadata %j", (change) => {
    expect(() => parseNormalizations({ specimens: [{ ...normalized, ...change }] })).toThrow();
  });
  it("accepts portrait ID-1 and rejects duplicate identities", () => {
    expect(parseNormalizations({ specimens: [{ ...normalized, width_px: 2699, height_px: 4280 }] })[0].height_px).toBe(4280);
    expect(() => parseNormalizations({ specimens: [normalized, normalized] })).toThrow();
  });
  it("strips previous normalization if a replacement index has no matching entry", () => {
    expect(joinNormalizations([{ ...specimen, normalization: normalized }], [])[0]).toEqual(specimen);
  });
  it("retains selected collection filtering for normalized references", () => {
    const items = joinNormalizations([specimen, { ...specimen, state: "OR" }], [normalized]);
    const html = render({ ...ready, items }, [], "OR");
    expect(html).toContain('src="/v1/specimens/OR/reference_01"');
    expect(html).not.toContain("/v1/id1-normalizations/WA/");
  });
  it("shows originals with an honest message if normalization retrieval fails", async () => {
    expect(render({ ...ready, normalizationStatus: "unavailable" })).toContain("Original references remain available");
    expect(render({ ...ready, normalizationStatus: "unavailable" })).toContain('src="/v1/specimens/WA/reference_01"');
    const transport = vi.fn(async () => Response.json({ specimens: [normalized] })) as unknown as typeof fetch;
    const signal = new AbortController().signal;
    expect(await loadNormalizations(signal, transport)).toEqual([normalized]);
    expect(transport).toHaveBeenCalledWith("/v1/id1-normalizations", { signal, credentials: "omit" });
    await expect(loadNormalizations(signal, (async () => new Response(null, { status: 404 })) as typeof fetch)).rejects.toThrow();
  });
});
