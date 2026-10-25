/** Runtime-neutral policy. Publishing a claim never confers trust or approval. */
export const AUP_VERSION = "2026-10-25";
export const AUP_TEXT =
  "I am authorized to act for the named legal entity. I will use Cadastre references only for legitimate identity verification, document research, or fraud prevention. I will not use them to create, alter, reproduce, or facilitate counterfeit identity documents; impersonate a person or organization; bypass identity controls; or redistribute restricted specimens. I understand that public specimen geometry is not a calibrated physical master and that observations do not independently establish authenticity. Access requires domain proof and manual review of both the entity and my authority. Access may expire or be revoked, and deliveries carry removable attribution receipts for audit purposes.";
const PERSONAL_DOMAINS = new Set([
  "gmail.com",
  "googlemail.com",
  "yahoo.com",
  "ymail.com",
  "hotmail.com",
  "outlook.com",
  "live.com",
  "msn.com",
  "icloud.com",
  "me.com",
  "mac.com",
  "aol.com",
  "proton.me",
  "protonmail.com",
  "pm.me",
  "tutanota.com",
  "tuta.com",
  "fastmail.com",
  "hey.com",
  "mail.com",
  "gmx.com",
  "gmx.de",
  "yandex.com",
  "yandex.ru",
  "qq.com",
  "163.com",
]);
/** Source collections; this value never asserts the depicted credential's issuer. */
export const SOURCE_COLLECTIONS = new Set(
  "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY US_FED".split(
    " ",
  ),
);
export class PolicyError extends Error {
  constructor(
    public code: string,
    public status = 400,
  ) {
    super(code);
  }
}
export function record(input: unknown): Record<string, unknown> {
  if (!input || typeof input !== "object" || Array.isArray(input))
    throw new PolicyError("invalid_json");
  return input as Record<string, unknown>;
}
export function field(
  input: Record<string, unknown>,
  name: string,
  min = 2,
  max = 300,
  multiline = false,
): string {
  const value = input[name];
  const controls = multiline
    ? /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/
    : /[\u0000-\u001f\u007f]/;
  if (
    typeof value !== "string" ||
    value.trim().length < min ||
    value.trim().length > max ||
    controls.test(value)
  )
    throw new PolicyError(`invalid_${name}`);
  return value.trim();
}
export function validateApplication(input: unknown) {
  const body = record(input);
  const domain = field(body, "organization_domain", 4, 253).toLowerCase();
  if (!/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(domain))
    throw new PolicyError("invalid_organization_domain");
  if (
    [...PERSONAL_DOMAINS].some((d) => domain === d || domain.endsWith(`.${d}`))
  )
    throw new PolicyError("work_domain_required");
  const email = field(body, "work_email", 5, 254).toLowerCase();
  if (
    !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+$/i.test(email) ||
    email.split("@").length !== 2 ||
    email.split("@")[1] !== domain
  )
    throw new PolicyError("work_email_domain_mismatch");
  const attestation = record(body.attestation);
  if (
    attestation.version !== AUP_VERSION ||
    attestation.accepted !== true ||
    attestation.applicant_authorized !== true ||
    attestation.legitimate_use !== true ||
    attestation.no_replication !== true
  )
    throw new PolicyError("attestation_required");
  return {
    legal_name: field(body, "legal_name", 2, 200),
    registration_number: field(body, "registration_number", 2, 150),
    registration_jurisdiction: field(body, "registration_jurisdiction", 2, 150),
    organization_domain: domain,
    work_email: email,
    applicant_name: field(body, "applicant_name", 2, 150),
    use_case: field(body, "use_case", 30, 4000, true),
    uei:
      body.uei === undefined || body.uei === ""
        ? null
        : field(body, "uei", 12, 12),
    cage:
      body.cage === undefined || body.cage === ""
        ? null
        : field(body, "cage", 5, 5),
  };
}
export function safeObjectKey(value: string): boolean {
  return (
    value.length <= 500 &&
    /^(snapshots|specimens|indexes)\/[a-zA-Z0-9][a-zA-Z0-9_./-]*$/.test(
      value,
    ) &&
    !value.includes("..") &&
    !value.includes("/./") &&
    !value.includes("//") &&
    !value.endsWith("/")
  );
}
export interface Specimen {
  id: string;
  state: string;
  key: string;
  source_sha256: string;
  asset_sha256: string;
  review_status: "reference_only";
}
export function specimenIndex(input: unknown): Specimen[] {
  const list = Array.isArray(input) ? input : record(input).specimens;
  if (!Array.isArray(list) || list.length > 10000)
    throw new PolicyError("invalid_specimen_index", 503);
  return list.map((item) => {
    const r = record(item);
    if (
      typeof r.id !== "string" ||
      !/^[a-zA-Z0-9_-]{1,150}$/.test(r.id) ||
      typeof r.state !== "string" ||
      !SOURCE_COLLECTIONS.has(r.state) ||
      typeof r.key !== "string" ||
      !safeObjectKey(r.key) ||
      !r.key.startsWith("specimens/") ||
      !r.key.endsWith(".png") ||
      typeof r.source_sha256 !== "string" ||
      !/^[a-f0-9]{64}$/.test(r.source_sha256) ||
      typeof r.asset_sha256 !== "string" ||
      !/^[a-f0-9]{64}$/.test(r.asset_sha256) ||
      r.review_status !== "reference_only"
    )
      throw new PolicyError("invalid_specimen_index", 503);
    return {
      id: r.id,
      state: r.state,
      key: r.key,
      source_sha256: r.source_sha256,
      asset_sha256: r.asset_sha256,
      review_status: r.review_status,
    };
  });
}
