import {
  AccessSubmissionError,
  responseError,
  sendDomainVerification,
} from "./access-model";
import { object } from "./catalog-model";

export interface SavedClaim {
  request_id: string;
  claim_token: string;
}
export interface RequestStatus {
  request_id: string;
  status: "pending_review" | "approved" | "rejected";
  domain_verified: boolean | null;
  key_claimed: boolean | null;
}
export interface ClaimedKey {
  api_key: string;
  key_id: string;
  expires_at: string;
}

export function savedClaim(requestId: string, token: string): SavedClaim {
  const request_id = requestId.trim();
  const claim_token = token.trim();
  if (
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(
      request_id,
    ) ||
    !/^[A-Za-z0-9_-]{43}$/.test(claim_token)
  ) {
    throw new AccessSubmissionError(
      "Enter the request ID and claim token from your saved receipt.",
    );
  }
  return { request_id, claim_token };
}

export function parseRequestStatus(
  value: unknown,
  requestId: string,
): RequestStatus {
  const body = object(value);
  if (
    body.request_id !== requestId ||
    (body.status !== "pending_review" &&
      body.status !== "approved" &&
      body.status !== "rejected") ||
    typeof body.domain_verified !== "boolean" ||
    typeof body.key_claimed !== "boolean"
  ) {
    throw new AccessSubmissionError(
      "The server returned an incomplete request status. Please try again.",
    );
  }
  return {
    request_id: requestId,
    status: body.status,
    domain_verified: body.domain_verified,
    key_claimed: body.key_claimed,
  };
}

function isoTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const timestamp = Date.parse(value);
  return (
    Number.isFinite(timestamp) && new Date(timestamp).toISOString() === value
  );
}
export function parseClaimedKey(value: unknown): ClaimedKey {
  const body = object(value);
  if (
    typeof body.api_key !== "string" ||
    !/^kl_live_[a-f0-9]{24}_[A-Za-z0-9_-]{43}$/.test(body.api_key) ||
    typeof body.key_id !== "string" ||
    body.api_key.split("_")[2] !== body.key_id ||
    !isoTimestamp(body.expires_at)
  ) {
    throw new AccessSubmissionError(
      "A complete key receipt was not received. Do not retry blindly: check request status; a claimed key cannot be displayed again.",
    );
  }
  return {
    api_key: body.api_key,
    key_id: body.key_id,
    expires_at: body.expires_at,
  };
}

const MANAGER_ERRORS = new Map([
  [
    "approval_required",
    "Organization approval, domain verification, and the current access policy are required before a key can be claimed.",
  ],
  [
    "key_already_claimed",
    "This key was already claimed and cannot be displayed again. Use your saved key or contact the maintainers about replacement.",
  ],
]);
function managerError(body: unknown): string {
  const code = object(object(body).error).code;
  const message =
    typeof code === "string" ? MANAGER_ERRORS.get(code) : undefined;
  return message ?? responseError(body);
}
async function postClaim(
  claim: SavedClaim,
  action: "status" | "claim-key",
  transport: typeof fetch,
) {
  const checked = savedClaim(claim.request_id, claim.claim_token);
  const response = await transport(
    `/v1/access-requests/${checked.request_id}/${action}`,
    {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "manual",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim_token: checked.claim_token }),
    },
  );
  const body: unknown = await response.json();
  return { response, body };
}
export async function requestStatus(
  claim: SavedClaim,
  transport: typeof fetch = fetch,
): Promise<RequestStatus> {
  const { response, body } = await postClaim(claim, "status", transport);
  if (!response.ok) {
    if (
      response.status === 403 &&
      object(object(body).error).code === "request_rejected"
    ) {
      return {
        request_id: claim.request_id,
        status: "rejected",
        domain_verified: null,
        key_claimed: null,
      };
    }
    throw new AccessSubmissionError(managerError(body));
  }
  return parseRequestStatus(body, claim.request_id);
}
export async function claimKey(
  claim: SavedClaim,
  transport: typeof fetch = fetch,
): Promise<ClaimedKey> {
  const { response, body } = await postClaim(claim, "claim-key", transport);
  if (!response.ok) throw new AccessSubmissionError(managerError(body));
  return parseClaimedKey(body);
}
export async function verifySavedDomain(
  claim: SavedClaim,
  transport: typeof fetch = fetch,
) {
  return sendDomainVerification(
    savedClaim(claim.request_id, claim.claim_token),
    (input, init) =>
      transport(input, {
        ...init,
        credentials: "same-origin",
        cache: "no-store",
        redirect: "manual",
      }),
  );
}
export function canClaim(status: RequestStatus | null): boolean {
  return (
    status?.status === "approved" &&
    status.domain_verified === true &&
    status.key_claimed === false
  );
}
export function statusMessage(status: RequestStatus): string {
  if (status.status === "rejected")
    return "This request was rejected. Contact the maintainers about a new request; this token does not authorize access.";
  if (status.status === "pending_review")
    return "Pending organization and applicant authority review. Domain proof alone does not grant access.";
  if (status.key_claimed)
    return "Approved. Your key was already claimed and cannot be displayed again. Use your saved key; contact the maintainers if it was lost.";
  if (!status.domain_verified)
    return "Approved, but domain verification is still required before a key can be claimed.";
  return "Approved and domain control verified. You may request your one-time key; the server checks eligibility again.";
}
