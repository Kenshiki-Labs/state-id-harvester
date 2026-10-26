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
