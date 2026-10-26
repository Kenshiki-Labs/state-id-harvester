import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ImageViewer from "../src/components/ImageViewer";
const item = { id: "reference_01", state: "WA", source_sha256: "a".repeat(64), asset_sha256: "b".repeat(64), review_status: "reference_only" as const };
const items = [item, { ...item, id: "reference_02" }];
const render = (index: number, name = "Washington") => renderToStaticMarkup(createElement(ImageViewer, { items, index, name, onNavigate: () => {}, onClose: () => {} }));
describe("image viewer boundaries", () => {
  it.each([-1, 2, 100])("renders no image or dialog for an invalid selection (%i)", (index) => {
    expect(render(index)).toBe("");
  });
  it("labels the native modal, escapes publication names and keeps downloads on the public image route", () => {
    const html = render(0, '<img src=x onerror="alert(1)">');
    expect(html).toContain("<dialog");
    expect(html).toContain("aria-labelledby=");
    expect(html).toContain("aria-describedby=");
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img src=x");
    expect(html).toContain('href="/v1/specimens/WA/reference_01" download="WA-reference_01.png"');
    expect(html).not.toContain('target="_blank"');
    expect(html).toContain(`src="/v1/specimens/WA/reference_01?view=display&amp;v=${item.asset_sha256}"`);
    expect(html).toContain('aria-label="Close image viewer"');
  });
  it("disables paging at each boundary and starts in fitted mode", () => {
    const first = render(0), last = render(1);
    expect(first).toContain('aria-label="Previous reference" disabled=""');
    expect(first).not.toContain('aria-label="Next reference" disabled=""');
    expect(last).toContain('aria-label="Next reference" disabled=""');
    expect(last).not.toContain('aria-label="Previous reference" disabled=""');
    expect(first).toContain('data-zoom="0"');
    expect(first).toContain('aria-label="Zoom out" disabled=""');
  });
});

describe("normalized image viewer", () => {
  const normalization = { ...item, asset_sha256: "c".repeat(64), original_reference_sha256: item.asset_sha256, canonical_asset_sha256: "d".repeat(64), width_px: 4280, height_px: 2699, boundary_basis: "visual_card_corners" as const };
  it("defaults normalized display and download to the matching ID-1 endpoint with an original control inside the modal", () => {
    const html = renderToStaticMarkup(createElement(ImageViewer, { items: [{ ...item, normalization }], index: 0, name: "Washington", onNavigate: () => {}, onClose: () => {} }));
    expect(html).toContain('src="/v1/id1-normalizations/WA/reference_01?view=display&amp;v=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"');
    expect(html).toContain('href="/v1/id1-normalizations/WA/reference_01" download="WA-reference_01-id1.png"');
    expect(html).toContain('aria-label="Image version"');
    expect(html).toContain('aria-pressed="true">ID-1</button>');
    expect(html).toContain('aria-pressed="false">Original</button>');
    expect(html).toContain("ID-1 normalized · review pending");
    expect(html).not.toContain('<a href="/v1/id1-normalizations/WA/reference_01?view=display');
    expect(html).not.toContain('src="/v1/id1-normalizations/WA/reference_01"');
    expect(html).not.toContain('target="_blank"');
  });
  it("does not offer a misleading ID-1 control for originals", () => {
    expect(render(0)).not.toContain('aria-label="Image version"');
    expect(render(0)).toContain("Original reference · review pending");
  });
});
