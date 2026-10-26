import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import KnowledgeLibrary from "../src/components/KnowledgeLibrary";
import {
  filterKnowledge, sourcePageUrl, statementFields,
  type KnowledgeDocument, type KnowledgeStatement,
} from "../src/lib/knowledge-model";

const feature: KnowledgeStatement = {
  statement_id: "s1", domain: "credential_design_security", kind: "assertion",
  subject: "Washington · 2018 design", interpretation_status: "unreviewed",
  content: { domain: "credential_design_security", name: "UV state outline", presence: "present", modalities: ["ultraviolet"] },
  conditions: ["Only the specified revision"], exceptions: ["Temporary paper credential excluded"],
  effective_wording: "Beginning September 2018", evidence: [{ page_number: 2, url: "https://agency.gov/guide.pdf#old" }],
};
const issuance: KnowledgeStatement = {
  ...feature, statement_id: "s2", domain: "issuance_administration", subject: null,
  content: { domain: "issuance_administration", procedure: "Bring two original documents.", document_stage: "permanent" },
  conditions: [], exceptions: [], effective_wording: null,
};
const document: KnowledgeDocument = {
  source_sha256: "a".repeat(64), title: "Washington design guide", publisher: "Department of Licensing",
  collection: "WA", source_url: "https://agency.gov/guide.pdf", roles: ["issuer_design_reference"],
  stated_edition: "2018 revision", publication_date_wording: "September 2018",
  statement_count: 2, statements: [feature, issuance], interpretation_status: "unreviewed",
};
const second: KnowledgeDocument = { ...document, source_sha256: "b".repeat(64), title: "Oregon issuance FAQ", collection: "OR", statements: [issuance], statement_count: 1 };

describe("knowledge filtering", () => {
  it("filters matching statements while keeping publication and domain scope together", () => {
    expect(filterKnowledge([document, second], "ultraviolet", "all")).toEqual([{ ...document, statements: [feature] }]);
    expect(filterKnowledge([document, second], " OREGON ", "issuance_administration")).toEqual([second]);
    expect(filterKnowledge([document], "Washington", "issuance_administration")).toEqual([{ ...document, statements: [issuance] }]);
    expect(filterKnowledge([document], "Washington", "inspection_procedure")).toEqual([]);
  });
  it("searches qualifiers and periods without leaking another statement through the filter", () => {
    for (const query of ["September 2018", "Temporary paper", "specified revision", "UV state"]) {
      expect(filterKnowledge([document], query, "all")[0].statements).toEqual([feature]);
    }
    expect(filterKnowledge([document], "No match", "all")).toEqual([]);
    expect(filterKnowledge([], "", "all")).toEqual([]);
  });
  it("exposes only supported content fields with readable values", () => {
    const fields = statementFields({ ...feature, content: { ...feature.content, unknown_private_key: "DO NOT DISPLAY", inspection_level: 1, source_location: null, equipment: [], authority_reference: { authority: "AAMVA", edition: "2020" } } });
    expect(fields).toContainEqual({ label: "Inspection modality", value: "ultraviolet" });
    expect(fields).toContainEqual({ label: "Inspection level", value: "1" });
    expect(fields).toContainEqual({ label: "Authority reference", value: "authority: AAMVA; edition: 2020" });
    expect(JSON.stringify(fields)).not.toContain("DO NOT DISPLAY");
    expect(JSON.stringify(fields)).not.toContain("source_location");
  });
});

describe("public source links", () => {
  it.each([null, "javascript:alert(1)", "data:text/html,bad", "file:///private/secret", "http://agency.gov/guide.pdf", "https://user:secret@agency.gov/guide.pdf", "invalid"])("rejects unsafe or absent source URL %s", (url) => {
    expect(sourcePageUrl(url, 2)).toBeNull();
  });
  it("binds explicit physical PDF pages and rejects invalid page types", () => {
    expect(sourcePageUrl("https://agency.gov/guide.pdf#old", 3)).toBe("https://agency.gov/guide.pdf#page=3");
    expect(sourcePageUrl("https://agency.gov/guide.pdf")).toBe("https://agency.gov/guide.pdf");
    for (const page of [0, -1, 1.5, NaN, Infinity]) expect(sourcePageUrl("https://agency.gov/guide.pdf", page)).toBeNull();
  });
});

describe("knowledge library rendering", () => {
  it("renders source provenance, historical qualifiers and unreviewed status", () => {
    const html = renderToStaticMarkup(createElement(KnowledgeLibrary, { documents: [document] }));
    expect(html).toContain("1 of 1 publications · 2 of 2 statements");
    expect(html).toContain("Explore 2 statements");
    expect(html).toContain("Edition: 2018 revision");
    expect(html).toContain("Published: September 2018");
    expect(html).toContain("Unreviewed interpretation");
    expect(html).toContain("Only the specified revision");
    expect(html).toContain("Temporary paper credential excluded");
    expect(html).toContain("Beginning September 2018");
    expect(html).toContain('href="https://agency.gov/guide.pdf#page=2"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).not.toContain("snapshots/");
  });
  it("escapes source and statement markup and offers no unsafe source link", () => {
    const hostile = { ...document, title: "<script>alert(1)</script>", source_url: "javascript:alert(1)", statements: [{ ...feature, content: { name: "<img onerror=evil>" }, evidence: [{ page_number: 2, url: null }] }] };
    const html = renderToStaticMarkup(createElement(KnowledgeLibrary, { documents: [hostile] }));
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("&lt;img onerror=evil&gt;");
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("<script>");
    expect(html).toContain("Page 2 · source link unavailable");
  });
  it("provides a truthful empty state and native keyboard-operable disclosures", () => {
    const html = renderToStaticMarkup(createElement(KnowledgeLibrary, { documents: [] }));
    expect(html).toContain("No matching statements.");
    expect(html).toContain("All domains");
    expect(html).toContain('aria-live="polite"');
    const one = renderToStaticMarkup(createElement(KnowledgeLibrary, { documents: [{ ...document, statements: [feature], statement_count: 1 }] }));
    expect(one).toContain("Explore 1 statement");
    expect(one).toContain("<details");
    expect(one).toContain("<summary>");
  });
});

// A shared publication is the join boundary; a state name is never sufficient.
describe("card and knowledge source pairing", () => {
  it("pairs only exact PDF bytes, regardless of collection/title similarity", async () => {
    const { knowledgeForSource } = await import("../src/lib/knowledge-model");
    expect(knowledgeForSource([document, second], document.source_sha256)).toEqual([document]);
    expect(knowledgeForSource([document], "c".repeat(64))).toEqual([]);
    expect(knowledgeForSource([document], "WA")).toEqual([]);
  });
  it("creates card-context links for exact source references and rejects malformed identities", async () => {
    const { referenceContextUrl } = await import("../src/lib/knowledge-model");
    const paired = { ...document, references: [{ id: "sample_01", state: "WA", asset_sha256: "b".repeat(64) }] };
    expect(referenceContextUrl(paired)).toBe(`/catalog/wa?source=${document.source_sha256}&reference=sample_01`);
    expect(referenceContextUrl({ ...paired, references: [{ ...paired.references[0], state: "US_FED" }] })).toContain("/catalog/federal?");
    expect(referenceContextUrl(document)).toBeNull();
    expect(referenceContextUrl({ ...paired, references: [{ ...paired.references[0], id: "../private" }] })).toBeNull();
    expect(referenceContextUrl({ ...paired, source_sha256: "unverified" })).toBeNull();
  });
  it("opens a requested image only when reference ID and source hash both match", async () => {
    const { requestedReferenceIndex } = await import("../src/lib/knowledge-model");
    const items = [{ id: "one", source_sha256: document.source_sha256 }, { id: "two", source_sha256: second.source_sha256 }];
    expect(requestedReferenceIndex(items, `?source=${document.source_sha256}&reference=one`)).toBe(0);
    expect(requestedReferenceIndex(items, `?source=${document.source_sha256}`)).toBe(0);
    expect(requestedReferenceIndex(items, `?source=${document.source_sha256}&reference=two`)).toBeNull();
    expect(requestedReferenceIndex(items, "?reference=one")).toBeNull();
    expect(requestedReferenceIndex(items, "?source=bad")).toBeNull();
  });
  it("shows a representative image and a direct inspection link beside source knowledge", () => {
    const paired = { ...document, references: [{ id: "sample_01", state: "WA", asset_sha256: "b".repeat(64) }] };
    const html = renderToStaticMarkup(createElement(KnowledgeLibrary, { documents: [paired] }));
    expect(html).toContain(`href="/catalog/wa?source=${document.source_sha256}&amp;reference=sample_01"`);
    expect(html).toContain("/v1/specimens/WA/sample_01?view=thumbnail");
    expect(html).toContain("Inspect card with source guidance");
  });
});

describe("image-page evidence scope", () => {
  it("prioritizes exact physical PDF page citations and keeps broader claims separate", async () => {
    const { statementsByImagePage } = await import("../src/lib/knowledge-model");
    const elsewhere = { ...issuance, evidence: [{ page_number: 4, url: null }] };
    expect(statementsByImagePage([feature, elsewhere], 2)).toEqual({ samePage: [feature], broader: [elsewhere] });
    expect(statementsByImagePage([feature], 3)).toEqual({ samePage: [], broader: [feature] });
    expect(statementsByImagePage([feature], undefined)).toEqual({ samePage: [], broader: [feature] });
    expect(statementsByImagePage([feature], -1)).toEqual({ samePage: [], broader: [feature] });
  });
});
