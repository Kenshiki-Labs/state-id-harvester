import { beforeAll, describe, expect, it, vi } from "vitest";
import { createElement, isValidElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { env } from "cloudflare:workers";
import worker from "../src/worker";
import schema from "../migrations/0001_access.sql?raw";
import { AUP_VERSION } from "../src/core/policy";
import AccessManager, {
  AccessManagerView,
  KeyReceipt,
} from "../src/components/AccessManager";
import {
  canClaim,
  claimKey,
  claimFromForm,
  parseClaimedKey,
  parseRequestStatus,
  requestStatus,
  savedClaim,
  statusMessage,
  verifySavedDomain,
} from "../src/lib/manager-model";

const origin = "https://cadastre.kenshikilabs.com";
const requestId = "12345678-1234-1234-1234-123456789abc";
const token = "t".repeat(43);
const claim = { request_id: requestId, claim_token: token };
const keyId = "a".repeat(24);
const receipt = {
  api_key: `kl_live_${keyId}_${"b".repeat(43)}`,
  key_id: keyId,
  expires_at: "2026-11-25T00:00:00.000Z",
};
const approved = {
  request_id: requestId,
  status: "approved",
  domain_verified: true,
  key_claimed: false,
};

function renderedButtons(
  node: unknown,
): { children?: unknown; onClick?: () => void }[] {
  if (Array.isArray(node)) return node.flatMap(renderedButtons);
  if (!isValidElement<{ children?: unknown; onClick?: () => void }>(node))
    return [];
  if (typeof node.type === "function") {
    const component = node.type as (props: typeof node.props) => unknown;
    return renderedButtons(component(node.props));
  }
  const nested = renderedButtons(node.props.children);
  return node.type === "button" ? [node.props, ...nested] : nested;
}

describe("saved request client boundary", () => {
  it("accepts string credentials from a form and rejects File or oversized entries", () => {
    const data = new FormData();
    data.set("request_id", requestId);
    data.set("claim_token", token);
    expect(claimFromForm(data)).toEqual(claim);
    data.set("claim_token", new File([token], "claim.txt"));
    expect(() => claimFromForm(data)).toThrow("saved receipt");
    data.set("claim_token", token);
    data.set("request_id", new File([requestId], "request.txt"));
    expect(() => claimFromForm(data)).toThrow("saved receipt");
    data.set("request_id", requestId);
    data.set("claim_token", "x".repeat(129));
    expect(() => claimFromForm(data)).toThrow("saved receipt");
    data.delete("claim_token");
    expect(() => claimFromForm(data)).toThrow("saved receipt");
  });
  it("wires visible proof, refresh, claim and clear buttons to their matching actions", () => {
    const manager = {
      claim,
      status: parseRequestStatus(
        { ...approved, domain_verified: false },
        requestId,
      ),
      key: null,
      busy: false,
      error: "",
      notice: "",
      submit: vi.fn(),
      act: vi.fn(),
      clear: vi.fn(),
    };
    const buttons = renderedButtons(
      createElement(AccessManagerView, { manager, ready: true }),
    );
    buttons.find((button) => button.children === "Refresh status")?.onClick?.();
    buttons.find((button) => button.children === "Verify domain")?.onClick?.();
    buttons
      .find((button) => button.children === "Clear credentials from this page")
      ?.onClick?.();
    const eligible = renderedButtons(
      createElement(AccessManagerView, {
        ready: true,
        manager: {
          ...manager,
          status: parseRequestStatus(approved, requestId),
        },
      }),
    );
    eligible
      .find((button) => button.children === "Claim one-time research key")
      ?.onClick?.();
    expect(manager.act.mock.calls).toEqual([["status"], ["verify"], ["claim"]]);
    expect(manager.clear).toHaveBeenCalledTimes(1);
  });
  it.each([
    "https://example.gov/?token=secret",
    "../admin",
    requestId + "?claim_token=secret",
  ])("rejects request IDs that could alter endpoint routing: %s", (id) => {
    expect(() => savedClaim(id, token)).toThrow("saved receipt");
  });
  it.each(["", "constructor", token + "?secret", "☃".repeat(43)])(
    "rejects malformed claim tokens",
    (invalid) => {
      expect(() => savedClaim(requestId, invalid)).toThrow("saved receipt");
    },
  );
  it.each([
    null,
    {},
    { ...approved, request_id: "different" },
    { ...approved, domain_verified: "true" },
    { ...approved, status: "self_approved" },
    { ...approved, key_claimed: null },
  ])("does not invent a request status from malformed responses", (value) => {
    expect(() => parseRequestStatus(value, requestId)).toThrow(
      "incomplete request status",
    );
  });
  it.each([
    null,
    {},
    { ...receipt, key_id: "f".repeat(24) },
    { ...receipt, expires_at: "tomorrow" },
    { ...receipt, expires_at: "2026-02-31T00:00:00.000Z" },
    { ...receipt, api_key: receipt.api_key + "\n<script>" },
  ])("rejects incomplete or inconsistent one-time keys", (value) => {
    expect(() => parseClaimedKey(value)).toThrow("complete key receipt");
  });
  it("only offers claim when the latest server status is approved, verified, and unclaimed", () => {
    const status = parseRequestStatus(approved, requestId);
    expect(canClaim(status)).toBe(true);
    expect(canClaim({ ...status, status: "pending_review" })).toBe(false);
    expect(canClaim({ ...status, status: "rejected" })).toBe(false);
    expect(canClaim({ ...status, domain_verified: false })).toBe(false);
    expect(canClaim({ ...status, key_claimed: true })).toBe(false);
    expect(canClaim(null)).toBe(false);
    expect(statusMessage({ ...status, status: "pending_review" })).toContain(
      "does not grant access",
    );
  });
  it("uses fixed same-origin POST endpoints with credentials only in the JSON body", async () => {
    const transport = vi.fn().mockResolvedValue(Response.json(approved));
    await requestStatus(claim, transport as typeof fetch);
    const [path, init] = transport.mock.calls[0];
    expect(path).toBe(`/v1/access-requests/${requestId}/status`);
    expect(String(path)).not.toContain(token);
    expect(init.method).toBe("POST");
    expect(init.cache).toBe("no-store");
    expect(init.credentials).toBe("same-origin");
    expect(init.redirect).toBe("manual");
    expect(JSON.parse(init.body)).toEqual({ claim_token: token });
    expect(init.headers.Authorization).toBeUndefined();
  });
  it("does not turn attacker-selected error names into authored approval or arbitrary output", async () => {
    const transport = vi
      .fn()
      .mockResolvedValue(
        Response.json(
          { error: { code: "constructor", message: "Approved!" }, ...approved },
          { status: 403 },
        ),
      );
    await expect(
      requestStatus(claim, transport as typeof fetch),
    ).rejects.toThrow("could not be submitted");
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it("never displays a key from a failed HTTP response", async () => {
    const transport = vi
      .fn()
      .mockResolvedValue(Response.json(receipt, { status: 403 }));
    await expect(claimKey(claim, transport as typeof fetch)).rejects.toThrow();
  });
  it("does not follow a redirect or accept a key/status hidden in its response", async () => {
    const transport = vi.fn().mockResolvedValue(
      Response.json(approved, {
        status: 307,
        headers: { Location: "https://attacker.invalid/" },
      }),
    );
    await expect(
      requestStatus(claim, transport as typeof fetch),
    ).rejects.toThrow();
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][1].redirect).toBe("manual");
  });
  it.each(["pending_review", "rejected", "approved"] as const)(
    "renders %s as server-reported state without implying proof grants access",
    (status) => {
      const state = parseRequestStatus({ ...approved, status }, requestId);
      const manager = {
        claim,
        status: state,
        key: null,
        busy: false,
        error: "",
        notice: "",
        submit: vi.fn(),
        act: vi.fn(),
        clear: vi.fn(),
      };
      const markup = renderToStaticMarkup(
        createElement(AccessManagerView, { manager, ready: true }),
      );
      expect(markup).not.toContain(token);
      expect(markup).not.toContain('name="claim_token"');
      expect(markup.includes("Claim one-time research key")).toBe(
        status === "approved",
      );
      expect(markup).toContain("Clear credentials from this page");
    },
  );
  it("offers DNS verification for pending unproved requests and suppresses claim after its one-time receipt", () => {
    const manager = {
      claim,
      status: parseRequestStatus(
        { ...approved, status: "pending_review", domain_verified: false },
        requestId,
      ),
      key: null,
      busy: false,
      error: "Check DNS again",
      notice: "Domain review remains separate",
      submit: vi.fn(),
      act: vi.fn(),
      clear: vi.fn(),
    };
    const pending = renderToStaticMarkup(
      createElement(AccessManagerView, { manager, ready: true }),
    );
    expect(pending).toContain("Verify domain");
    expect(pending).not.toContain("Claim one-time research key");
    expect(pending).toContain('role="alert"');
    const issued = renderToStaticMarkup(
      createElement(AccessManagerView, {
        ready: true,
        manager: {
          ...manager,
          status: parseRequestStatus(approved, requestId),
          key: receipt,
          busy: true,
        },
      }),
    );
    expect(issued).toContain("Save your key now");
    expect(issued).not.toContain("Claim one-time research key");
    expect(issued).toContain("disabled");
  });
  it("explains rejected, already claimed, and proof-required outcomes without approval guesses", () => {
    const status = parseRequestStatus(approved, requestId);
    expect(statusMessage({ ...status, status: "rejected" })).toContain(
      "rejected",
    );
    expect(statusMessage({ ...status, key_claimed: true })).toContain(
      "cannot be displayed again",
    );
    expect(statusMessage({ ...status, domain_verified: false })).toContain(
      "verification is still required",
    );
    expect(statusMessage(status)).toContain("server checks eligibility again");
  });
  it("renders a password field with no prefilled credentials and an explicit one-time save instruction", () => {
    const initial = renderToStaticMarkup(createElement(AccessManager));
    expect(initial).toContain('type="password"');
    expect(initial).not.toContain(token);
    expect(initial).not.toContain(receipt.api_key);
    expect(initial).not.toContain("Claim one-time research key");
    const key = renderToStaticMarkup(createElement(KeyReceipt, { receipt }));
    expect(key).toContain("This is its only display");
    expect(key).toContain("readOnly");
    expect(key).toContain(receipt.api_key);
  });
  it("prevents credential GET submission before hydration or when JavaScript is unavailable", () => {
    const initial = renderToStaticMarkup(createElement(AccessManager));
    expect(initial).toContain('method="post"');
    expect(initial).toContain('action="/access"');
    expect((initial.match(/disabled=""/g) ?? []).length).toBe(3);
    expect(initial).toContain("Preparing request manager…");
    expect(initial).toContain("Enable JavaScript");
    expect(initial).not.toContain('method="get"');
  });
});

const testEnv = {
  ...env,
  CADASTRE_ADMIN_KEY_HASH: "",
  CADASTRE_INGEST_KEY_HASH: "",
  CADASTRE_TRACE_KEY: "manager-tests-only-not-production",
  RATE_LIMITER: { limit: async () => ({ success: true }) },
  INGEST_LIMITER: { limit: async () => ({ success: true }) },
};
const transport = (async (input, init) =>
  worker.fetch(
    new Request(origin + String(input), {
      ...init,
      headers: {
        ...Object.fromEntries(new Headers(init?.headers)),
        Origin: origin,
      },
    }),
    testEnv,
  )) as typeof fetch;
beforeAll(async () => {
  for (const statement of schema
    .split(";")
    .map((value) => value.trim())
    .filter(Boolean))
    await env.DB.prepare(statement).run();
});
async function createRequest() {
  const result = await transport("/v1/access-requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      legal_name: "Manager integration research",
      registration_number: "CA-manager-test",
      registration_jurisdiction: "California",
      organization_domain: "example.gov",
      work_email: "researcher@example.gov",
      applicant_name: "Integration Researcher",
      use_case:
        "Evaluate source document topology for controlled identity research.",
      attestation: {
        accepted: true,
        version: AUP_VERSION,
        applicant_authorized: true,
        legitimate_use: true,
        no_replication: true,
      },
    }),
  });
  expect(result.status).toBe(201);
  return (await result.json()) as {
    request_id: string;
    claim_token: string;
    domain_challenge: { name: string; value: string };
  };
}
describe("request manager against the actual Worker", () => {
  it("keeps pending domain-proved applicants gated, then returns one key only after server approval", async () => {
    const application = await createRequest();
    const initial = await requestStatus(application, transport);
    expect(initial.status).toBe("pending_review");
    await expect(claimKey(application, transport)).rejects.toThrow("approval");
    const dns = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        Status: 0,
        Answer: [
          {
            name: application.domain_challenge.name,
            type: 16,
            data: `"${application.domain_challenge.value}"`,
          },
        ],
      }),
    );
    try {
      expect(await verifySavedDomain(application, transport)).toMatchObject({
        approval_granted: false,
        domain_verified: true,
      });
    } finally {
      dns.mockRestore();
    }
    expect(canClaim(await requestStatus(application, transport))).toBe(false);
    await expect(claimKey(application, transport)).rejects.toThrow("approval");
    await env.DB.prepare(
      "UPDATE access_requests SET status='approved',approved_at=? WHERE id=?",
    )
      .bind(new Date().toISOString(), application.request_id)
      .run();
    expect(canClaim(await requestStatus(application, transport))).toBe(true);
    const key = await claimKey(application, transport);
    expect(key.api_key).toMatch(/^kl_live_/);
    expect((await requestStatus(application, transport)).key_claimed).toBe(
      true,
    );
    await expect(claimKey(application, transport)).rejects.toThrow(
      "already claimed",
    );
  });
  it("shows rejected state and cannot claim despite a previously approved client view", async () => {
    const application = await createRequest();
    await env.DB.prepare(
      "UPDATE access_requests SET status='approved',domain_verified_at=? WHERE id=?",
    )
      .bind(new Date().toISOString(), application.request_id)
      .run();
    const stale = await requestStatus(application, transport);
    expect(canClaim(stale)).toBe(true);
    await env.DB.prepare(
      "UPDATE access_requests SET status='rejected' WHERE id=?",
    )
      .bind(application.request_id)
      .run();
    expect((await requestStatus(application, transport)).status).toBe(
      "rejected",
    );
    await expect(claimKey(application, transport)).rejects.toThrow("approval");
  });
  it("rejects cross-request tokens without exposing request status or issuing keys", async () => {
    const first = await createRequest();
    const second = await createRequest();
    const crossed = {
      request_id: first.request_id,
      claim_token: second.claim_token,
    };
    await expect(requestStatus(crossed, transport)).rejects.toThrow(
      "saved receipt",
    );
    await expect(claimKey(crossed, transport)).rejects.toThrow("saved receipt");
  });
});
