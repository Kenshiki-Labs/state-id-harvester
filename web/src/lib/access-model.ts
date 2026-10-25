import { object } from "./catalog-model";
export class AccessSubmissionError extends Error {}
export interface AccessPolicy {
  version: string;
  text: string;
  sha256: string;
}
export interface AccessResult {
  request_id: string;
  status: "pending_review";
  domain_challenge: { name: string; value: string };
  claim_token: string;
  attestation_receipt: unknown;
}
export interface DomainVerification {
  request_id: string;
  status: "pending_review" | "approved";
  domain_verified: true;
  approval_granted: false;
}
export function parsePolicy(value: unknown): AccessPolicy {
  const data = object(value);
  if (
    typeof data.version !== "string" ||
    typeof data.text !== "string" ||
    typeof data.sha256 !== "string" ||
    !data.text ||
    !/^[a-f0-9]{64}$/.test(data.sha256)
  )
    throw new Error(
      "The current access policy could not load. Please refresh before submitting.",
    );
  return { version: data.version, text: data.text, sha256: data.sha256 };
}
export function parseAccessResult(value: unknown): AccessResult {
  const body = object(value);
  const challenge = object(body.domain_challenge);
  if (
    body.status !== "pending_review" ||
    typeof body.request_id !== "string" ||
    !body.request_id ||
    typeof challenge.name !== "string" ||
    !challenge.name ||
    typeof challenge.value !== "string" ||
    !challenge.value ||
    typeof body.claim_token !== "string" ||
    !body.claim_token ||
    !body.attestation_receipt
  )
    throw new AccessSubmissionError(
      "The server returned an incomplete receipt. Please try again.",
    );
  return {
    request_id: body.request_id,
    status: body.status,
    domain_challenge: { name: challenge.name, value: challenge.value },
    claim_token: body.claim_token,
    attestation_receipt: body.attestation_receipt,
  };
}
export function applicationPayload(
  data: FormData,
  registrationType: string,
  policy: AccessPolicy,
) {
  const accepted = data.get("attestation") === "on";
  return {
    legal_name: data.get("organization"),
    registration_number: data.get("registration_id"),
    registration_jurisdiction: data.get("registration_jurisdiction"),
    organization_domain: data.get("domain"),
    work_email: data.get("email"),
    applicant_name: data.get("name"),
    use_case: data.get("use_case"),
    ...(registrationType === "UEI" ? { uei: data.get("registration_id") } : {}),
    ...(registrationType === "CAGE"
      ? { cage: data.get("registration_id") }
      : {}),
    attestation: {
      accepted,
      version: policy.version,
      applicant_authorized: accepted,
      legitimate_use: accepted,
      no_replication: accepted,
    },
  };
}
const RESPONSE_ERRORS: ReadonlyMap<string, string> = new Map([
  [
    "work_email_domain_mismatch",
    "Your work email must use the organization domain entered above.",
  ],
  ["work_domain_required", "Use your organization’s domain and work email."],
  [
    "invalid_use_case",
    "Please describe your use case in at least 30 characters.",
  ],
  [
    "attestation_required",
    "Please refresh the page and accept the current access policy.",
  ],
  ["rate_limited", "Too many requests. Please wait before trying again."],
  [
    "service_unavailable",
    "The access service is temporarily unavailable. Please try again later.",
  ],
  [
    "domain_proof_not_found",
    "The TXT record is not visible yet. Check its name and value, allow time for DNS propagation, then try again.",
  ],
  [
    "dns_unavailable",
    "DNS verification is temporarily unavailable. Please try again.",
  ],
  [
    "invalid_claim",
    "This claim token could not verify the request. Use the token from your saved receipt.",
  ],
  [
    "request_rejected",
    "This access request cannot proceed. Contact the Cadastre team about a new request.",
  ],
]);
export function responseError(value: unknown): string {
  const body = object(value);
  const error = object(body.error);
  const code = typeof body.error === "string" ? body.error : error.code;
  const message =
    typeof code === "string" ? RESPONSE_ERRORS.get(code) : undefined;
  return message ?? "Your request could not be submitted. Please try again.";
}
export function accessButtonLabel(
  busy: boolean,
  policy: AccessPolicy | null,
  error: string,
): string {
  if (busy) return "Submitting request…";
  if (policy) return "Request research access";
  if (error) return "Access temporarily unavailable";
  return "Loading access policy…";
}

export async function sendApplication(
  payload: ReturnType<typeof applicationPayload>,
  transport: typeof fetch = fetch,
): Promise<AccessResult> {
  const response = await transport("/v1/access-requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) throw new AccessSubmissionError(responseError(body));
  return parseAccessResult(body);
}
export function submissionError(error: unknown): string {
  return error instanceof AccessSubmissionError
    ? error.message
    : "The access service is unavailable. Please try again.";
}
export function parseDomainVerification(
  value: unknown,
  requestId: string,
): DomainVerification {
  const body = object(value);
  if (
    body.request_id !== requestId ||
    body.domain_verified !== true ||
    body.approval_granted !== false ||
    (body.status !== "pending_review" && body.status !== "approved")
  )
    throw new AccessSubmissionError(
      "The server returned an incomplete domain verification. Please try again.",
    );
  return {
    request_id: requestId,
    status: body.status,
    domain_verified: true,
    approval_granted: false,
  };
}
export async function sendDomainVerification(
  claim: Pick<AccessResult, "request_id" | "claim_token">,
  transport: typeof fetch = fetch,
): Promise<DomainVerification> {
  const response = await transport(
    `/v1/access-requests/${encodeURIComponent(claim.request_id)}/verify-domain`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim_token: claim.claim_token }),
    },
  );
  const body = await response.json();
  if (!response.ok) throw new AccessSubmissionError(responseError(body));
  return parseDomainVerification(body, claim.request_id);
}
export function domainVerificationError(error: unknown): string {
  return error instanceof AccessSubmissionError
    ? error.message
    : "Domain verification is unavailable. Please try again.";
}
export function domainVerificationLabel(
  busy: boolean,
  verified: boolean,
): string {
  if (verified) return "Domain control verified";
  if (busy) return "Checking DNS…";
  return "Verify domain";
}
