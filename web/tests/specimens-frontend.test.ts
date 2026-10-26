import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import homepage from "../src/pages/index.astro?raw";
import accessPage from "../src/pages/access.astro?raw";
import SpecimenGallery from "../src/components/SpecimenGallery";
import { loadSpecimens, parseSpecimens, specimenUrl, type GalleryState } from "../src/lib/specimens";
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
  it("limits images to the selected collection, links full-size images and escapes source titles", () => {
    const html = render(ready, [{ title: '<script>alert("source")</script>', url: "https://agency.gov/guide.pdf", hostname: "agency.gov", relevance: "candidate", sha256: specimen.source_sha256 }]);
    expect(html).toContain('src="/v1/specimens/WA/reference_01"');
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
    expect(loading).toContain('role="status"');
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
