import { describe, expect, it } from "vitest";
import {
  AUP_VERSION,
  field,
  record,
  safeObjectKey,
  specimenIndex,
  validateApplication,
} from "../src/core/policy";
const application = {
  legal_name: "Research Corporation",
  registration_number: "Registration-123",
  registration_jurisdiction: "California",
  organization_domain: "EXAMPLE.GOV",
  work_email: "Tester@EXAMPLE.GOV",
  applicant_name: "Research User",
  use_case:
    "Research document topology for legitimate verification applications.",
  attestation: {
    accepted: true,
    version: AUP_VERSION,
    applicant_authorized: true,
    legitimate_use: true,
    no_replication: true,
  },
};
const specimen = {
  id: "ca_adult",
  state: "CA",
  key: "specimens/ca/flat.png",
  source_sha256: "a".repeat(64),
  asset_sha256: "b".repeat(64),
  review_status: "reference_only",
};
describe("adversarial policy contracts", () => {
  it.each([null, [], true, "record", 17])(
    "rejects non-object input %s",
    (value) => {
      expect(() => record(value)).toThrow("invalid_json");
    },
  );
  it.each([
    "gmail.com",
    "GOOGLEMAIL.COM",
    "division.gmail.com",
    "PROTON.ME",
    "staff.outlook.com",
  ])("rejects personal mail domain %s", (domain) => {
    expect(() =>
      validateApplication({
        ...application,
        organization_domain: domain,
        work_email: `test@${domain}`,
      }),
    ).toThrow("work_domain_required");
  });
  it.each([
    "localhost",
    "https://example.gov",
    "example.gov/path",
    "a..gov",
    "-host.gov",
    "host-.gov",
    "example.gov.",
    "example.gov:443",
    "example.gov@evil.gov",
    "a".repeat(64) + ".gov",
    "_domain.gov",
  ])("rejects malformed domain %s", (domain) => {
    expect(() =>
      validateApplication({ ...application, organization_domain: domain }),
    ).toThrow();
  });
  it.each([
    "test@example.gov.evil.com",
    "test@sub.example.gov",
    "test@@example.gov",
    "test@example.gov\u0000",
    "test\r\n@example.gov",
    "missing-at.example.gov",
  ])("rejects mismatched or malformed email %s", (email) => {
    expect(() =>
      validateApplication({ ...application, work_email: email }),
    ).toThrow();
  });
  it("normalizes case without granting authority or inventing a status", () => {
    const accepted = validateApplication({
      ...application,
      status: "approved",
      domain_verified: true,
      admin: true,
    });
    expect(accepted.organization_domain).toBe("example.gov");
    expect(accepted.work_email).toBe("tester@example.gov");
    expect(accepted).not.toHaveProperty("status");
    expect(accepted).not.toHaveProperty("admin");
  });
  it.each([
    "accepted",
    "applicant_authorized",
    "legitimate_use",
    "no_replication",
  ])("requires explicit boolean %s", (name) => {
    expect(() =>
      validateApplication({
        ...application,
        attestation: { ...application.attestation, [name]: "true" },
      }),
    ).toThrow("attestation_required");
  });
  it("requires all business registration and applicant fields", () => {
    for (const name of [
      "legal_name",
      "registration_number",
      "registration_jurisdiction",
      "applicant_name",
      "use_case",
    ])
      expect(() =>
        validateApplication({ ...application, [name]: "" }),
      ).toThrow();
    expect(() => field({ value: "a\u007fb" }, "value")).toThrow();
    expect(() => field({ value: 30 }, "value")).toThrow();
    expect(() =>
      validateApplication({ ...application, uei: "short" }),
    ).toThrow();
    expect(() =>
      validateApplication({ ...application, cage: "too long" }),
    ).toThrow();
    expect(
      validateApplication({
        ...application,
        uei: "ABCDEFGHIJKL",
        cage: "1AB23",
      }),
    ).toMatchObject({ uei: "ABCDEFGHIJKL", cage: "1AB23" });
  });
  it.each([
    "snapshots/../secrets",
    "specimens//flat.png",
    "specimens/%2e%2e/key",
    "https://evil.invalid/image.png",
    "private/source.pdf",
    "/specimens/x.png",
    "indexes/",
    "specimens/./x.png",
    "specimens/x.png?key=value",
    "specimens/x\\flat.png",
  ])("rejects untrusted object path %s", (key) => {
    expect(safeObjectKey(key)).toBe(false);
  });
  it("allows bounded object namespaces only", () => {
    expect(safeObjectKey("snapshots/run/part-0001.bin")).toBe(true);
    expect(safeObjectKey("indexes/specimens.json")).toBe(true);
    expect(safeObjectKey("specimens/ca/flat.png")).toBe(true);
    expect(safeObjectKey("specimens/" + "a".repeat(501))).toBe(false);
  });
  it("validates a private allowlist and ignores untrusted extras in its result", () => {
    expect(
      specimenIndex({
        specimens: [
          {
            ...specimen,
            host: "https://evil.invalid",
            extra_path: "private/credentials",
          },
        ],
      }),
    ).toEqual([specimen]);
  });
  it("accepts the separate federal source collection without assigning it ID-1 geometry", () => {
    const federal = {
      ...specimen,
      state: "US_FED",
      key: "specimens/US_FED/reference.png",
    };
    expect(specimenIndex([federal])).toEqual([federal]);
    expect(() =>
      specimenIndex([{ ...federal, state: "US_FEDERAL" }]),
    ).toThrow();
    expect(() => specimenIndex([{ ...federal, state: "ZZ" }])).toThrow();
  });
  it.each([
    { key: "https://evil.invalid/x.png" },
    { key: "snapshots/x.png" },
    { key: "specimens/../x.png" },
    { key: "specimens/x.pdf" },
    { id: "../../secret" },
    { state: "ZZZ" },
    { review_status: "approved" },
    { asset_sha256: "invalid" },
    { source_sha256: "g".repeat(64) },
  ])("rejects malformed allowlist entry %s", (extra) => {
    expect(() => specimenIndex([{ ...specimen, ...extra }])).toThrow();
  });
  it("rejects malformed or unbounded indexes", () => {
    expect(() => specimenIndex({ specimens: {} })).toThrow();
    expect(() => specimenIndex(new Array(10001).fill(specimen))).toThrow();
  });
});
