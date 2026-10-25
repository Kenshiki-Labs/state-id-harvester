import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import CatalogDetail from "../src/components/CatalogDetail";
import FederalCatalog from "../src/components/FederalCatalog";
import { AccessReceipt } from "../src/components/AccessForm";
import { describe, expect, it } from "vitest";
import {
  blankCatalog,
  filterCatalog,
  normalizeCatalog,
  normalizeFederal,
  catalogFilter,
} from "../src/lib/catalog-model";
import {
  applicationPayload,
  accessButtonLabel,
  parseAccessResult,
  parsePolicy,
  responseError,
  sendApplication,
  submissionError,
  sendDomainVerification,
  parseDomainVerification,
  domainVerificationError,
  domainVerificationLabel,
  type AccessResult,
} from "../src/lib/access-model";
const fingerprint = "a".repeat(64);
const policy = {
  version: "2026-10-25",
  text: "Full reviewed policy",
  sha256: fingerprint,
};
const manifest = {
  jurisdictions: [
    {
      code: "TX",
      name: "Unexpected replacement",
      counts: {
        sources: 2,
        relevant_sources: 1,
        embedded_images: 10,
        rendered_pages: 3,
        crop_candidates: 4,
        accepted_cohorts: 0,
      },
      sources: [
        {
          title: "Official source",
          url: "https://www.dps.texas.gov/example.pdf",
          sha256: fingerprint,
          relevance: "candidate",
        },
      ],
    },
  ],
};

describe("public catalog boundary", () => {
  it("keeps all 50 states and DC, canonical names, discovery gaps, and measured counts", () => {
    const rows = normalizeCatalog(manifest);
    expect(rows).toHaveLength(51);
    expect(new Set(rows.map((row) => row.code)).size).toBe(51);
    expect(rows.find((row) => row.code === "DC")?.name).toBe(
      "District of Columbia",
    );
    expect(rows.find((row) => row.code === "TX")).toMatchObject({
      name: "Texas",
      proposals: 4,
      acceptedCohorts: 0,
      nativeImages: 10,
    });
    expect(rows.find((row) => row.code === "AK")?.sources).toEqual([]);
  });
  it.each([null, {}, "not JSON", { jurisdictions: null }])(
    "fails visibly for an invalid manifest %j",
    (value) => {
      expect(() => normalizeCatalog(value)).toThrow("Invalid source index");
    },
  );
  it("drops active, malformed, credential-bearing, and non-HTTPS URLs", () => {
    const sources = [
      "javascript:alert(1)",
      "data:image/svg+xml,<svg/>",
      "http://agency.gov/file.pdf",
      "https://%",
      "https://user:secret@agency.gov/file.pdf",
      "file:///private/file.pdf",
    ].map((url) => ({ url, title: "Rejected source" }));
    expect(
      normalizeCatalog({ jurisdictions: [{ code: "TX", sources }] }).find(
        (row) => row.code === "TX",
      )?.sources,
    ).toEqual([]);
  });
  it("preserves source text as text and quarantined status; rejects fake hashes", () => {
    const row = normalizeCatalog({
      jurisdictions: [
        {
          code: "TX",
          sources: [
            {
              url: "https://agency.gov/file.pdf",
              title: "<img src=x onerror=alert(1)>",
              sha256: "not-a-hash",
              relevance: "quarantined",
            },
          ],
        },
      ],
    }).find((row) => row.code === "TX");
    expect(row?.sources[0]).toEqual({
      url: "https://agency.gov/file.pdf",
      hostname: "agency.gov",
      title: "<img src=x onerror=alert(1)>",
      relevance: "quarantined",
    });
  });
  it("does not manufacture negative, fractional, infinite, or string counts", () => {
    const row = normalizeCatalog({
      jurisdictions: [
        {
          code: "TX",
          counts: {
            relevant_sources: -1,
            embedded_images: 1.5,
            rendered_pages: Infinity,
            crop_candidates: "9000",
          },
        },
      ],
    }).find((row) => row.code === "TX");
    expect([
      row?.relevantPdfs,
      row?.nativeImages,
      row?.renderedPages,
      row?.proposals,
    ]).toEqual([0, 0, 0, 0]);
  });
  it("combines literal case-insensitive search with source filters", () => {
    const rows = normalizeCatalog(manifest);
    expect(
      filterCatalog(rows, "  tX  ", "sources").map((row) => row.code),
    ).toEqual(["TX"]);
    expect(filterCatalog(rows, "Texas", "awaiting")).toEqual([]);
    expect(filterCatalog(rows, "[.*<script>", "all")).toEqual([]);
    expect(filterCatalog(blankCatalog(), "", "awaiting")).toHaveLength(51);
  });
});

describe("catalog rendering boundary", () => {
  it("renders hostile document titles as literal text and never creates active markup", () => {
    const rows = normalizeCatalog({
      jurisdictions: [
        {
          code: "TX",
          sources: [
            {
              title: "<img src=x onerror=alert(1)><script>attack()</script>",
              url: "https://agency.gov/reference.pdf",
            },
            { title: "Active URL", url: "javascript:alert(1)" },
          ],
        },
      ],
    });
    const detail = rows.find((row) => row.code === "TX")!;
    const html = renderToStaticMarkup(
      createElement(CatalogDetail, { detail, unavailable: false }),
    );
    expect(html).toContain("&lt;img");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("javascript:");
    expect(html).toContain('rel="noopener noreferrer"');
  });
  it("does not report zero evidence when the manifest is unavailable", () => {
    const html = renderToStaticMarkup(
      createElement(CatalogDetail, {
        detail: blankCatalog()[0],
        unavailable: true,
      }),
    );
    expect(html).toContain(
      "An unavailable index does not establish a coverage gap.",
    );
    expect(html).not.toContain("Source PDFs");
    expect(html).not.toContain("No source documents");
  });
});

describe("access application boundary", () => {
  it("requires a complete pending receipt, and never interprets approval as request success", () => {
    const receipt = {
      request_id: "request-123",
      status: "pending_review",
      domain_challenge: {
        name: "_cadastre-verification.example.com",
        value: "challenge",
      },
      claim_token: "private-token",
      attestation_receipt: "signed-receipt",
    };
    expect(parseAccessResult(receipt)).toEqual(receipt);
    for (const invalid of [
      null,
      {},
      { ...receipt, status: "approved" },
      { ...receipt, claim_token: "" },
      { ...receipt, domain_challenge: {} },
      { ...receipt, attestation_receipt: null },
    ])
      expect(() => parseAccessResult(invalid)).toThrow();
  });
  it("fails closed on an unavailable or incomplete current policy", () => {
    expect(parsePolicy(policy)).toEqual(policy);
    for (const invalid of [
      {},
      { ...policy, sha256: "wrong" },
      { ...policy, text: "" },
      null,
    ])
      expect(() => parsePolicy(invalid)).toThrow();
  });
  it("binds every attestation assertion to explicit acceptance and policy version", () => {
    const form = new FormData();
    form.set("organization", "Example Organization");
    form.set("registration_id", "A".repeat(12));
    form.set("registration_jurisdiction", "US / SAM.gov");
    form.set("domain", "example.com");
    form.set("email", "research@example.com");
    form.set("name", "Test Applicant");
    form.set("use_case", "Independent document reference research.");
    expect(applicationPayload(form, "UEI", policy)).toMatchObject({
      legal_name: "Example Organization",
      uei: "A".repeat(12),
      attestation: {
        accepted: false,
        version: policy.version,
        applicant_authorized: false,
        legitimate_use: false,
        no_replication: false,
      },
    });
    form.set("attestation", "on");
    const accepted = applicationPayload(form, "state_registration", policy);
    expect(accepted.attestation).toEqual({
      accepted: true,
      version: policy.version,
      applicant_authorized: true,
      legitimate_use: true,
      no_replication: true,
    });
    expect("uei" in accepted).toBe(false);
    expect("cage" in accepted).toBe(false);
  });
  it("handles failed responses and transport errors without disclosing diagnostics or showing success", async () => {
    const form = new FormData();
    const payload = applicationPayload(form, "state_registration", policy);
    const untrusted = "<script>secret token</script>";
    for (const status of [409, 503]) {
      const transport = (async () =>
        new Response(
          JSON.stringify({
            error: untrusted,
            message: untrusted,
            request_id: "fake",
            status: "pending_review",
          }),
          { status, headers: { "Content-Type": "application/json" } },
        )) as typeof fetch;
      await expect(sendApplication(payload, transport)).rejects.toThrow(
        "Your request could not be submitted. Please try again.",
      );
    }
    const network = (async () => {
      throw new Error("INTERNAL network topology and secret");
    }) as typeof fetch;
    let failure: unknown;
    try {
      await sendApplication(payload, network);
    } catch (error) {
      failure = error;
    }
    expect(submissionError(failure)).toBe(
      "The access service is unavailable. Please try again.",
    );
    expect(submissionError(new SyntaxError("private response text"))).toBe(
      "The access service is unavailable. Please try again.",
    );
  });
  it("does not echo arbitrary server errors or sensitive data into the page", () => {
    expect(
      responseError({ error: { code: "work_email_domain_mismatch" } }),
    ).toContain("work email");
    expect(
      responseError({
        error: { code: "rate_limited", message: "secret diagnostics" },
      }),
    ).toBe("Too many requests. Please wait before trying again.");
    expect(responseError({ error: "work_email_domain_mismatch" })).toContain(
      "work email",
    );
    expect(
      responseError({
        error: "<script>secret token</script>",
        message: "private debug detail",
      }),
    ).toBe("Your request could not be submitted. Please try again.");
    expect(responseError(null)).toBe(
      "Your request could not be submitted. Please try again.",
    );
  });
});

describe("federal collection boundary", () => {
  const federal = {
    code: "US_FED",
    name: "United States federal",
    credential_format: "unclassified",
    counts: {
      sources: 5,
      relevant_sources: 3,
      embedded_images: 303,
      rendered_pages: 30,
      crop_candidates: 0,
      accepted_cohorts: 0,
    },
    sources: [
      {
        title: "Normative PIV reference",
        url: "https://nvlpubs.nist.gov/reference.pdf",
        sha256: fingerprint,
        relevance: "candidate",
      },
    ],
  };
  it("keeps federal source metadata separate from the 51 state jurisdictions", () => {
    const catalog = { ...manifest, federal };
    expect(normalizeCatalog(catalog)).toHaveLength(51);
    expect(normalizeCatalog(catalog).some((row) => row.code === "US_FED")).toBe(
      false,
    );
    expect(normalizeFederal(catalog)).toMatchObject({
      code: "US_FED",
      credentialFormat: "unclassified",
      nativeImages: 303,
      renderedPages: 30,
      proposals: 0,
      acceptedCohorts: 0,
    });
    const html = renderToStaticMarkup(
      createElement(FederalCatalog, { collection: normalizeFederal(catalog) }),
    );
    expect(html).toContain("Separate federal source collection");
    expect(html).toContain("not normalized as ID-1");
    expect(html).toContain("Normative PIV reference");
  });
  it("supports an absent collection and rejects federal ID1 classification", () => {
    expect(normalizeFederal(manifest)).toBeNull();
    expect(normalizeFederal({ ...manifest, federal: null })).toBeNull();
    expect(normalizeCatalog({ ...manifest, federal: null })).toHaveLength(51);
    expect(
      renderToStaticMarkup(createElement(FederalCatalog, { collection: null })),
    ).toBe("");
    expect(() =>
      normalizeFederal({ federal: { ...federal, credential_format: "ID1" } }),
    ).toThrow("Invalid federal source index");
    expect(() =>
      normalizeFederal({ federal: { ...federal, code: "TX" } }),
    ).toThrow("Invalid federal source index");
  });
});

describe("frontend control boundaries", () => {
  it.each(["constructor", "__proto__", "toString", "hasOwnProperty"])(
    "treats inherited error name %s as an unknown reason",
    (error) => {
      expect(responseError({ error })).toBe(
        "Your request could not be submitted. Please try again.",
      );
      expect(responseError({ error: { code: error } })).toBe(
        "Your request could not be submitted. Please try again.",
      );
    },
  );
  it("uses authored submit labels across policy and request states", () => {
    expect(accessButtonLabel(true, policy, "")).toBe("Submitting request…");
    expect(accessButtonLabel(false, policy, "")).toBe(
      "Request research access",
    );
    expect(accessButtonLabel(false, null, "unavailable")).toBe(
      "Access temporarily unavailable",
    );
    expect(accessButtonLabel(false, null, "")).toBe("Loading access policy…");
  });
  it("constrains arbitrary filter values to the known catalog filters", () => {
    expect(catalogFilter("constructor")).toBe("all");
    expect(catalogFilter("sources")).toBe("sources");
    expect(catalogFilter("awaiting")).toBe("awaiting");
  });
});
describe("domain proof application boundary", () => {
  const receipt: AccessResult = {
    request_id: "12345678-1234-4234-8234-123456789abc",
    status: "pending_review",
    domain_challenge: {
      name: "_cadastre-verification.example.gov",
      value: "cadastre=challenge",
    },
    claim_token: "private-claim-token",
    attestation_receipt: "signed-receipt",
  };
  const proof = {
    request_id: receipt.request_id,
    status: "pending_review",
    domain_verified: true,
    approval_granted: false,
  };
  it("sends the claim token in a JSON POST body and validates proof without granting access", async () => {
    const transport = (async (input, init) => {
      expect(input).toBe(
        `/v1/access-requests/${receipt.request_id}/verify-domain`,
      );
      expect(String(input)).not.toContain(receipt.claim_token);
      expect(init?.method).toBe("POST");
      expect(new Headers(init?.headers).get("Content-Type")).toBe(
        "application/json",
      );
      expect(new Headers(init?.headers).has("Authorization")).toBe(false);
      expect(JSON.parse(String(init?.body))).toEqual({
        claim_token: receipt.claim_token,
      });
      return Response.json(proof);
    }) as typeof fetch;
    expect(await sendDomainVerification(receipt, transport)).toEqual(proof);
  });
  it("maps actual nested DNS errors to authored feedback and never displays arbitrary response diagnostics", async () => {
    for (const code of [
      "domain_proof_not_found",
      "dns_unavailable",
      "invalid_claim",
    ]) {
      const transport = (async () =>
        Response.json(
          { error: { code, message: "private diagnostics" } },
          { status: 409 },
        )) as typeof fetch;
      let failure: unknown;
      try {
        await sendDomainVerification(receipt, transport);
      } catch (error) {
        failure = error;
      }
      expect(domainVerificationError(failure)).toBe(
        responseError({ error: { code } }),
      );
      expect(domainVerificationError(failure)).not.toContain(
        "private diagnostics",
      );
    }
    expect(domainVerificationError(new Error("secret response"))).toBe(
      "Domain verification is unavailable. Please try again.",
    );
  });
  it("rejects forged, incomplete and cross-request proof responses", () => {
    for (const invalid of [
      null,
      {},
      { ...proof, request_id: "other-request" },
      { ...proof, domain_verified: false },
      { ...proof, approval_granted: true },
      { ...proof, status: "rejected" },
    ])
      expect(() =>
        parseDomainVerification(invalid, receipt.request_id),
      ).toThrow();
    expect(
      parseDomainVerification(
        { ...proof, status: "approved" },
        receipt.request_id,
      ).approval_granted,
    ).toBe(false);
  });
  it("renders an actionable proof button, native feedback and a separate organization review requirement", () => {
    const props = {
      result: receipt,
      verificationBusy: false,
      verificationError: "",
      domainVerified: false,
      verifyDomain: () => {},
    };
    const pending = renderToStaticMarkup(createElement(AccessReceipt, props));
    expect(pending).toContain('type="button"');
    expect(pending).toContain("Verify domain");
    const verified = renderToStaticMarkup(
      createElement(AccessReceipt, { ...props, domainVerified: true }),
    );
    expect(verified).toContain(
      '<output aria-live="polite">Domain control verified.',
    );
    expect(verified).toContain("this step does not grant access.");
    expect(verified).toContain('disabled=""');
    expect(verified).toContain("Pending review.");
    const failed = renderToStaticMarkup(
      createElement(AccessReceipt, {
        ...props,
        verificationError: responseError({
          error: { code: "domain_proof_not_found" },
        }),
      }),
    );
    expect(failed).toContain('role="alert"');
    expect(failed).toContain("TXT record is not visible yet");
    expect(domainVerificationLabel(true, false)).toBe("Checking DNS…");
    expect(domainVerificationLabel(false, true)).toBe(
      "Domain control verified",
    );
  });
});
