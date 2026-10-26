import { beforeAll, describe, expect, it, vi } from "vitest";
import { env } from "cloudflare:workers";
import worker from "../src/worker";
import schema from "../migrations/0001_access.sql?raw";
import { AUP_TEXT, AUP_VERSION } from "../src/core/policy";
import { withPngReceipt } from "../src/core/png";
import { sendDomainVerification } from "../src/lib/access-model";
const origin = "https://cadastre.kenshikilabs.com";
const hash = async (s: string) =>
  [
    ...new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)),
    ),
  ]
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
let seq = 0;
const app = (extra = {}) => ({
  legal_name: "Example Research",
  registration_number: "CA-12345",
  registration_jurisdiction: "California",
  organization_domain: "example.gov",
  work_email: "reviewer@example.gov",
  applicant_name: "Example Reviewer",
  use_case:
    "Evaluate document topology for identity verification in a controlled research environment.",
  attestation: {
    accepted: true,
    version: AUP_VERSION,
    applicant_authorized: true,
    legitimate_use: true,
    no_replication: true,
  },
  ...extra,
});
const testEnv = {
  ...env,
  CADASTRE_ADMIN_KEY_HASH: "",
  CADASTRE_INGEST_KEY_HASH: "",
  CADASTRE_TRACE_KEY: "test-only-trace-secret-long-enough",
  RATE_LIMITER: { limit: async () => ({ success: true }) },
  INGEST_LIMITER: { limit: async () => ({ success: true }) },
  PUBLIC_READ_LIMITER: { limit: async () => ({ success: true }) },
};
async function call(
  path: string,
  body?: unknown,
  token?: string,
  method?: string,
  headers: Record<string, string> = {},
) {
  const request = new Request(origin + path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers: {
      Origin: origin,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  return worker.fetch(request, testEnv);
}
async function create(extra = {}) {
  const response = await call(
    "/v1/access-requests",
    app({ ...extra, registration_number: `CA-${++seq}` }),
  );
  expect(response.status).toBe(201);
  return (await response.json()) as {
    request_id: string;
    claim_token: string;
    domain_challenge: { name: string; value: string };
    attestation_receipt: string;
  };
}
beforeAll(async () => {
  for (const statement of schema
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean))
    await env.DB.prepare(statement).run();
  testEnv.CADASTRE_ADMIN_KEY_HASH = await hash("test-admin-token");
  testEnv.CADASTRE_INGEST_KEY_HASH = await hash("test-ingest-token");
});
describe("server-side access authority", () => {
  it.each([200, 302])(
    "uses the edge-supported redirect policy and rejects missing proof or a redirect (%i)",
    async (status) => {
      const result = await create();
      const spy = vi
        .spyOn(globalThis, "fetch")
        .mockImplementation(async (_input, init) => {
          // The real Cloudflare edge rejects redirect:error even though a local
          // mocked fetch accepts it. Reproduce that platform constraint here.
          if (init?.redirect !== "manual")
            throw new TypeError("Unsupported edge redirect policy");
          return status === 200
            ? Response.json({ Status: 0, Answer: [] })
            : new Response(null, {
                status,
                headers: { Location: "https://untrusted.invalid/" },
              });
        });
      try {
        const response = await call(
          `/v1/access-requests/${result.request_id}/verify-domain`,
          {
            claim_token: result.claim_token,
          },
        );
        expect(response.status).toBe(status === 200 ? 409 : 503);
        expect(spy).toHaveBeenCalledTimes(1);
        const row = await env.DB.prepare(
          "SELECT domain_verified_at FROM access_requests WHERE id=?",
        )
          .bind(result.request_id)
          .first();
        expect(row?.domain_verified_at).toBeNull();
      } finally {
        spy.mockRestore();
      }
    },
  );
  it("accepts the frontend proof helper contract while keeping organization review pending", async () => {
    const result = await create();
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        Status: 0,
        Answer: [
          {
            name: result.domain_challenge.name,
            type: 16,
            data: `"${result.domain_challenge.value}"`,
          },
        ],
      }),
    );
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
    try {
      expect(await sendDomainVerification(result, transport)).toMatchObject({
        request_id: result.request_id,
        status: "pending_review",
        domain_verified: true,
        approval_granted: false,
      });
    } finally {
      spy.mockRestore();
    }
    expect(
      (
        await call(`/v1/access-requests/${result.request_id}/claim-key`, {
          claim_token: result.claim_token,
        })
      ).status,
    ).toBe(403);
  });
  it("publishes the exact accepted policy and opaque health response", async () => {
    expect(await (await call("/v1/policy")).json()).toEqual({
      version: AUP_VERSION,
      text: AUP_TEXT,
      sha256: await hash(AUP_TEXT),
    });
    expect(await (await call("/health")).json()).toEqual({ ok: true });
  });
  it("never approves government domain or UEI claims and stores a versioned receipt", async () => {
    const result = await create({ uei: "ABCDEFGHIJKL" });
    const status = await call(
      `/v1/access-requests/${result.request_id}/status`,
      { claim_token: result.claim_token },
    );
    expect(await status.json()).toMatchObject({
      status: "pending_review",
      domain_verified: false,
      key_claimed: false,
    });
    const row = await env.DB.prepare(
      "SELECT claim_hash,aup_text,aup_hash,attestation_receipt FROM access_requests WHERE id=?",
    )
      .bind(result.request_id)
      .first();
    expect(row?.claim_hash).toBe(await hash(result.claim_token));
    expect(row?.aup_text).toBe(AUP_TEXT);
    expect(row?.aup_hash).toBe(await hash(AUP_TEXT));
    expect(row?.attestation_receipt).toBe(result.attestation_receipt);
    expect(
      (
        await call(`/v1/access-requests/${result.request_id}/claim-key`, {
          claim_token: result.claim_token,
        })
      ).status,
    ).toBe(403);
  });
  it("rejects personal email, mismatched email, old AUP, cross-origin and oversized JSON", async () => {
    expect(
      (
        await call(
          "/v1/access-requests",
          app({ organization_domain: "gmail.com", work_email: "x@gmail.com" }),
        )
      ).status,
    ).toBe(400);
    expect(
      (await call("/v1/access-requests", app({ work_email: "x@other.gov" })))
        .status,
    ).toBe(400);
    expect(
      (
        await call(
          "/v1/access-requests",
          app({ attestation: { accepted: true, version: "old" } }),
        )
      ).status,
    ).toBe(400);
    expect(
      (
        await call("/v1/access-requests", app(), undefined, undefined, {
          Origin: "https://other.invalid",
        })
      ).status,
    ).toBe(403);
    expect(
      (await call("/v1/access-requests", app({ use_case: "x".repeat(17000) })))
        .status,
    ).toBe(413);
  });
  it("proves only DNS possession; approval needs entity and authorization evidence", async () => {
    const result = await create();
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        Status: 0,
        Answer: [
          {
            name: result.domain_challenge.name + ".",
            type: 16,
            data: `"${result.domain_challenge.value}"`,
          },
        ],
      }),
    );
    const proof = await call(
      `/v1/access-requests/${result.request_id}/verify-domain`,
      { claim_token: result.claim_token },
    );
    expect(await proof.json()).toMatchObject({
      domain_verified: true,
      status: "pending_review",
      approval_granted: false,
    });
    spy.mockRestore();
    expect(
      (
        await call(
          `/admin/access-requests/${result.request_id}/approve`,
          {
            reviewer: "Test reviewer",
            entity_evidence: "Verified public entity record",
          },
          "test-admin-token",
        )
      ).status,
    ).toBe(400);
    expect(
      (
        await call(
          `/admin/access-requests/${result.request_id}/approve`,
          {
            reviewer: "Test reviewer",
            entity_evidence: "Verified public entity record",
            authorization_evidence:
              "Verified applicant delegation independently",
          },
          "wrong-token",
        )
      ).status,
    ).toBe(401);
    expect(
      (
        await call(
          `/admin/access-requests/${result.request_id}/approve`,
          {
            reviewer: "Test reviewer",
            entity_evidence: "Verified public entity record",
            authorization_evidence:
              "Verified applicant delegation independently",
          },
          "test-admin-token",
        )
      ).status,
    ).toBe(200);
    const issued = await call(
      `/v1/access-requests/${result.request_id}/claim-key`,
      { claim_token: result.claim_token },
    );
    expect(issued.status).toBe(200);
    const key = (await issued.json()) as { api_key: string; key_id: string };
    expect(key.api_key).toMatch(/^kl_live_[a-f0-9]{24}_[\w-]{43}$/);
    expect(
      (
        await call(`/v1/access-requests/${result.request_id}/claim-key`, {
          claim_token: result.claim_token,
        })
      ).status,
    ).toBe(409);
    const stored = await env.DB.prepare(
      "SELECT key_hash FROM api_keys WHERE id=?",
    )
      .bind(key.key_id)
      .first();
    expect(stored?.key_hash).toBe(await hash(key.api_key));
    const png = Uint8Array.from(
      atob(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVNQAAAAASUVORK5CYII=",
      ),
      (c) => c.charCodeAt(0),
    );
    const pngHash = [
      ...new Uint8Array(await crypto.subtle.digest("SHA-256", png)),
    ]
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
    const upload = new Request(
      origin + "/internal/objects/specimens/test/example.png",
      {
        method: "PUT",
        headers: {
          Authorization: "Bearer test-ingest-token",
          "Content-Type": "image/png",
          "Content-Length": String(png.length),
          "x-content-sha256": pngHash,
          "x-cadastre-reference-only": "true",
          "x-cadastre-source-sha256": "a".repeat(64),
        },
        body: png,
      },
    );
    const uploaded = await worker.fetch(upload, testEnv);
    expect(uploaded.status).toBe(201);
    await env.VAULT.put(
      "indexes/specimens.json",
      JSON.stringify([
        {
          id: "test",
          state: "CA",
          key: "specimens/test/example.png",
          source_sha256: "a".repeat(64),
          asset_sha256: pngHash,
          review_status: "reference_only",
        },
      ]),
    );
    expect((await call("/v1/specimens", undefined, key.api_key)).status).toBe(
      200,
    );
    const downloaded = await call(
      "/v1/specimens/CA/test",
      undefined,
      key.api_key,
    );
    expect(downloaded.status).toBe(200);
    expect(downloaded.headers.get("X-Cadastre-Receipt")).toBeNull();
    expect(new Uint8Array(await downloaded.arrayBuffer())).toEqual(png);
    expect(downloaded.headers.get("Cache-Control")).toBe("public, max-age=300");
    expect(
      (await call("/v1/specimens/CA/arbitrary-path", undefined, key.api_key))
        .status,
    ).toBe(404);
    expect(
      (
        await call(
          `/admin/keys/${key.key_id}/revoke`,
          { reviewer: "Test reviewer", reason: "Research access ended" },
          "test-admin-token",
        )
      ).status,
    ).toBe(200);
    expect((await call("/v1/specimens")).status).toBe(200);
    const revoked = await env.DB.prepare(
      "SELECT revoked_at FROM api_keys WHERE id=?",
    )
      .bind(key.key_id)
      .first();
    expect(revoked?.revoked_at).not.toBeNull();
  });
  it("does not approve before DNS verification or accept incorrect claim token", async () => {
    const result = await create();
    expect(
      (
        await call(
          `/admin/access-requests/${result.request_id}/approve`,
          {
            reviewer: "Test reviewer",
            entity_evidence: "Verified entity public record",
            authorization_evidence: "Verified individual delegation",
          },
          "test-admin-token",
        )
      ).status,
    ).toBe(409);
    expect(
      (
        await call(`/v1/access-requests/${result.request_id}/status`, {
          claim_token: "A".repeat(43),
        })
      ).status,
    ).toBe(403);
  });
  it("cannot use a claim token across applications or make self-approval flags authoritative", async () => {
    const first = await create({
        status: "approved",
        approved: true,
        domain_verified: true,
        reviewer: "self",
      }),
      second = await create();
    expect(
      (
        await call(`/v1/access-requests/${second.request_id}/status`, {
          claim_token: first.claim_token,
        })
      ).status,
    ).toBe(403);
    expect(
      (
        await call(`/v1/access-requests/${first.request_id}/claim-key`, {
          claim_token: first.claim_token,
          approved: true,
          admin: true,
        })
      ).status,
    ).toBe(403);
    expect(
      (
        await call(
          `/admin/access-requests/${first.request_id}/approve`,
          {
            reviewer: "self",
            entity_evidence: "I declare this company valid",
            authorization_evidence: "I declare my own authority",
          },
          first.claim_token,
        )
      ).status,
    ).toBe(401);
    expect(
      await (
        await call(`/v1/access-requests/${first.request_id}/status`, {
          claim_token: first.claim_token,
        })
      ).json(),
    ).toMatchObject({ status: "pending_review", domain_verified: false });
  });
  it("does not grant access on failed, unrelated, huge, redirected or unavailable DNS answers", async () => {
    const result = await create();
    for (const answer of [
      { Status: 3, Answer: [] },
      {
        Status: 0,
        Answer: [
          {
            name: "unrelated.example.gov",
            type: 16,
            data: `"${result.domain_challenge.value}"`,
          },
        ],
      },
      {
        Status: 0,
        Answer: [
          {
            name: result.domain_challenge.name,
            type: 1,
            data: `"${result.domain_challenge.value}"`,
          },
        ],
      },
      {
        Status: 0,
        Answer: [
          {
            name: result.domain_challenge.name,
            type: 16,
            data: '"cadastre=wrong"',
          },
        ],
      },
    ]) {
      const spy = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(Response.json(answer));
      try {
        expect(
          (
            await call(
              `/v1/access-requests/${result.request_id}/verify-domain`,
              { claim_token: result.claim_token },
            )
          ).status,
        ).toBe(409);
      } finally {
        spy.mockRestore();
      }
    }
    for (const response of [
      new Response("bad gateway", { status: 502 }),
      new Response("x".repeat(65537)),
      new Response("not valid JSON"),
    ]) {
      const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
      try {
        expect(
          (
            await call(
              `/v1/access-requests/${result.request_id}/verify-domain`,
              { claim_token: result.claim_token },
            )
          ).status,
        ).toBeGreaterThanOrEqual(400);
      } finally {
        spy.mockRestore();
      }
    }
    expect(
      (
        await call(`/v1/access-requests/${result.request_id}/claim-key`, {
          claim_token: result.claim_token,
        })
      ).status,
    ).toBe(403);
    const row = await env.DB.prepare(
      "SELECT domain_verified_at FROM access_requests WHERE id=?",
    )
      .bind(result.request_id)
      .first();
    expect(row?.domain_verified_at).toBeNull();
  });
  it("a valid DNS proof cannot claim an unapproved key while marked references remain public", async () => {
    const result = await create();
    const half = result.domain_challenge.value.length / 2;
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        Status: 0,
        Answer: [
          {
            name: result.domain_challenge.name,
            type: 16,
            data: `"${result.domain_challenge.value.slice(0, half)}" "${result.domain_challenge.value.slice(half)}"`,
          },
        ],
      }),
    );
    try {
      expect(
        (
          await call(`/v1/access-requests/${result.request_id}/verify-domain`, {
            claim_token: result.claim_token,
          })
        ).status,
      ).toBe(200);
    } finally {
      spy.mockRestore();
    }
    expect(
      (
        await call(`/v1/access-requests/${result.request_id}/claim-key`, {
          claim_token: result.claim_token,
        })
      ).status,
    ).toBe(403);
    await env.VAULT.put("indexes/specimens.json", "[]");
    expect((await call("/v1/specimens")).status).toBe(200);
  });
  it("refuses stale accepted policy versions or hashes even for previously approved applicants", async () => {
    for (const [column, value] of [
      ["aup_version", "old"],
      ["aup_hash", "0".repeat(64)],
    ]) {
      const result = await create();
      await env.DB.prepare(
        `UPDATE access_requests SET status='approved',domain_verified_at=?,${column}=? WHERE id=?`,
      )
        .bind(new Date().toISOString(), value, result.request_id)
        .run();
      expect(
        (
          await call(`/v1/access-requests/${result.request_id}/claim-key`, {
            claim_token: result.claim_token,
          })
        ).status,
      ).toBe(403);
      expect(
        await env.DB.prepare("SELECT id FROM api_keys WHERE request_id=?")
          .bind(result.request_id)
          .first(),
      ).toBeNull();
    }
  });
  it("rejects an approved organization immediately and prevents issue or proof after rejection", async () => {
    const result = await create();
    await env.DB.prepare(
      "UPDATE access_requests SET status='approved',domain_verified_at=? WHERE id=?",
    )
      .bind(new Date().toISOString(), result.request_id)
      .run();
    const issued = await call(
      `/v1/access-requests/${result.request_id}/claim-key`,
      { claim_token: result.claim_token },
    );
    expect(issued.status).toBe(200);
    await issued.json();
    const rejection = await call(
      `/admin/access-requests/${result.request_id}/reject`,
      {
        reviewer: "Independent reviewer",
        entity_evidence: "Entity authorization withdrawn",
        authorization_evidence: "Applicant has left the approved organization",
      },
      "test-admin-token",
    );
    expect(rejection.status).toBe(200);
    expect((await call("/v1/specimens")).status).toBe(200);
    expect(
      (
        await call(`/v1/access-requests/${result.request_id}/verify-domain`, {
          claim_token: result.claim_token,
        })
      ).status,
    ).toBe(403);
    expect(
      (
        await call(`/v1/access-requests/${result.request_id}/claim-key`, {
          claim_token: result.claim_token,
        })
      ).status,
    ).toBe(403);
    const row = await env.DB.prepare(
      "SELECT status FROM access_requests WHERE id=?",
    )
      .bind(result.request_id)
      .first();
    expect(row?.status).toBe("rejected");
  });
  it("fails closed for private paths and missing credentials", async () => {
    await env.VAULT.put("indexes/specimens.json", "[]");
    expect((await call("/v1/specimens")).status).toBe(200);
    expect(
      (await call("/internal/objects/indexes/specimens.json")).status,
    ).toBe(401);
    expect((await call("/v1/not-a-real-route")).status).toBe(404);
    expect((await call("/v1")).status).toBe(404);
    expect((await call("/admin/access-requests")).status).toBe(401);
  });
  it.each(["GET", "HEAD"])(
    "redirects the legacy request manager without retaining credentials (%s)",
    async (method) => {
      const response = await call(
        "/access?request_id=old-request&claim_token=private-legacy-token",
        undefined,
        undefined,
        method,
      );
      expect(response.status).toBe(301);
      expect(response.headers.get("Location")).toBe(origin + "/#catalog");
      expect(await response.text()).toBe("");
    },
  );
  it("isolates ingest credentials and rejects checksum mismatches without committing bytes", async () => {
    const upload = (token: string, checksum: string) =>
      new Request(origin + "/internal/objects/snapshots/test/part.bin", {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/octet-stream",
          "Content-Length": "4",
          "x-content-sha256": checksum,
        },
        body: "test",
      });
    expect(
      (
        await worker.fetch(
          upload("test-admin-token", await hash("test")),
          testEnv,
        )
      ).status,
    ).toBe(401);
    expect(
      (await worker.fetch(upload("test-ingest-token", "0".repeat(64)), testEnv))
        .status,
    ).toBe(400);
    expect(await env.VAULT.get("snapshots/test/part.bin")).toBeNull();
    expect(
      (
        await worker.fetch(
          upload("test-ingest-token", await hash("test")),
          testEnv,
        )
      ).status,
    ).toBe(201);
    const retrieved = await call(
      "/internal/objects/snapshots/test/part.bin",
      undefined,
      "test-ingest-token",
    );
    expect(new TextDecoder().decode(await retrieved.arrayBuffer())).toBe(
      "test",
    );
    expect(
      (
        await call(
          "/internal/objects/not-allowed/file",
          undefined,
          "test-ingest-token",
        )
      ).status,
    ).toBe(400);
    expect(
      (await call("/admin/access-requests", undefined, "test-ingest-token"))
        .status,
    ).toBe(401);
    expect(
      (await call("/v1/specimens", undefined, "test-ingest-token")).status,
    ).toBe(200);
    expect(
      (await call("/admin/access-requests", undefined, "test-admin-token"))
        .status,
    ).toBe(200);
    expect(
      (await call("/admin/anything", undefined, "test-admin-token")).status,
    ).toBe(404);
    expect(
      (
        await call(
          "/internal/objects/snapshots/missing",
          undefined,
          "test-ingest-token",
        )
      ).status,
    ).toBe(404);
    expect(
      (
        await call(
          "/internal/objects/snapshots/test/part.bin",
          {},
          "test-ingest-token",
          "POST",
        )
      ).status,
    ).toBe(405);
  });
  it("rejects wrong-sized, missing-checksum, restricted and encoded-traversal ingestion", async () => {
    const cases = [
      {
        key: "snapshots/test/short.bin",
        length: "5",
        checksum: await hash("test"),
      },
      {
        key: "snapshots/test/long.bin",
        length: "3",
        checksum: await hash("test"),
      },
      {
        key: "snapshots/test/no-length.bin",
        length: "",
        checksum: await hash("test"),
      },
      {
        key: "snapshots/test/huge.bin",
        length: String(51 * 1024 * 1024),
        checksum: await hash("test"),
      },
      { key: "snapshots/test/no-sha.bin", length: "4", checksum: "" },
      {
        key: "private/secrets.json",
        length: "4",
        checksum: await hash("test"),
      },
      {
        key: "specimens/test/unmarked.png",
        length: "4",
        checksum: await hash("test"),
      },
      {
        key: "snapshots/test/%2e%2e%2fsecrets",
        length: "4",
        checksum: await hash("test"),
      },
    ];
    for (const item of cases) {
      const request = new Request(origin + "/internal/objects/" + item.key, {
        method: "PUT",
        headers: {
          Authorization: "Bearer test-ingest-token",
          "Content-Length": item.length,
          "x-content-sha256": item.checksum,
        },
        body: "test",
      });
      expect(
        (await worker.fetch(request, testEnv)).status,
      ).toBeGreaterThanOrEqual(400);
      expect(await env.VAULT.get(item.key)).toBeNull();
    }
  });
  it("rejects malformed JSON, wrong content type, null body and forged authority headers", async () => {
    for (const request of [
      new Request(origin + "/v1/access-requests", {
        method: "POST",
        headers: { Origin: origin, "Content-Type": "application/json" },
        body: "[",
      }),
      new Request(origin + "/v1/access-requests", {
        method: "POST",
        headers: { Origin: origin, "Content-Type": "text/plain" },
        body: "{}",
      }),
      new Request(origin + "/v1/access-requests", {
        method: "POST",
        headers: { Origin: origin, "Content-Type": "application/json" },
      }),
      new Request("https://evil.invalid/v1/access-requests", {
        method: "POST",
        headers: {
          Origin: origin,
          "Content-Type": "application/json",
          "X-Forwarded-Host": "cadastre.kenshikilabs.com",
        },
        body: JSON.stringify(app()),
      }),
      ...["application/jsonp", "application/json-unsafe"].map(
        (type) =>
          new Request(origin + "/v1/access-requests", {
            method: "POST",
            headers: { Origin: origin, "Content-Type": type },
            body: JSON.stringify(app()),
          }),
      ),
    ])
      expect(
        (await worker.fetch(request, testEnv)).status,
      ).toBeGreaterThanOrEqual(400);
    const limited = await worker.fetch(new Request(origin + "/v1/policy"), {
      ...testEnv,
      RATE_LIMITER: { limit: async () => ({ success: false }) },
    });
    expect(limited.status).toBe(429);
    const unavailable = await worker.fetch(
      new Request(origin + "/v1/access-requests", {
        method: "POST",
        headers: { Origin: origin, "Content-Type": "application/json" },
        body: JSON.stringify(app()),
      }),
      { ...testEnv, CADASTRE_TRACE_KEY: "" },
    );
    expect(unavailable.status).toBe(503);
  });
  it("rolls back one-time key claim when its required audit insert fails", async () => {
    const result = await create();
    await env.DB.prepare(
      "UPDATE access_requests SET status='approved',domain_verified_at=? WHERE id=?",
    )
      .bind(new Date().toISOString(), result.request_id)
      .run();
    await env.DB.prepare(
      "CREATE TRIGGER fail_claim_audit BEFORE INSERT ON audit_events WHEN NEW.event='key_claimed' BEGIN SELECT RAISE(ABORT,'audit unavailable'); END",
    ).run();
    try {
      expect(
        (
          await call(`/v1/access-requests/${result.request_id}/claim-key`, {
            claim_token: result.claim_token,
          })
        ).status,
      ).toBe(503);
      expect(
        await env.DB.prepare("SELECT id FROM api_keys WHERE request_id=?")
          .bind(result.request_id)
          .first(),
      ).toBeNull();
      const row = await env.DB.prepare(
        "SELECT claimed_at FROM access_requests WHERE id=?",
      )
        .bind(result.request_id)
        .first();
      expect(row?.claimed_at).toBeNull();
    } finally {
      await env.DB.prepare("DROP TRIGGER fail_claim_audit").run();
    }
    const results = await Promise.all([
      call(`/v1/access-requests/${result.request_id}/claim-key`, {
        claim_token: result.claim_token,
      }),
      call(`/v1/access-requests/${result.request_id}/claim-key`, {
        claim_token: result.claim_token,
      }),
    ]);
    expect(results.map((r) => r.status).sort()).toEqual([200, 409]);
  });
});
describe("adversarial public marked-reference delivery", () => {
  const png = Uint8Array.from(
    atob(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVNQAAAAASUVORK5CYII=",
    ),
    (c) => c.charCodeAt(0),
  );
  const entry = {
    id: "adversarial",
    state: "TX",
    key: "specimens/security/flat.png",
    source_sha256: "a".repeat(64),
    asset_sha256: "b".repeat(64),
    review_status: "reference_only",
  };
  beforeAll(async () => {
    entry.asset_sha256 = [
      ...new Uint8Array(await crypto.subtle.digest("SHA-256", png)),
    ]
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
  });
  async function seedPublicReference() {
    await env.VAULT.put(
      "indexes/specimens.json",
      JSON.stringify([
        {
          ...entry,
          private_note: "not-public",
          work_email: "private@example.gov",
        },
      ]),
    );
    await env.VAULT.put(entry.key, png, {
      sha256: entry.asset_sha256,
      httpMetadata: { contentType: "image/png" },
      customMetadata: {
        cadastreReferenceOnly: "true",
        sha256: entry.asset_sha256,
        sourceSha256: entry.source_sha256,
      },
    });
  }
  it("allows anonymous GET and HEAD with bounded public caching and no storage-key leakage", async () => {
    await seedPublicReference();
    const listed = await worker.fetch(
      new Request(origin + "/v1/specimens"),
      testEnv,
    );
    expect(listed.status).toBe(200);
    expect(listed.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(await listed.json()).toEqual({
      specimens: [
        {
          id: entry.id,
          state: entry.state,
          source_sha256: entry.source_sha256,
          asset_sha256: entry.asset_sha256,
          review_status: "reference_only",
        },
      ],
    });
    const listHead = await call("/v1/specimens", undefined, undefined, "HEAD");
    expect(listHead.status).toBe(200);
    expect(listHead.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(await listHead.text()).toBe("");
    const image = await worker.fetch(
      new Request(origin + "/v1/specimens/TX/adversarial", {
        headers: {
          Origin: "https://other.example",
          Authorization: "Bearer irrelevant-invalid-token",
        },
      }),
      testEnv,
    );
    expect(image.status).toBe(200);
    expect(image.headers.get("Content-Type")).toBe("image/png");
    expect(image.headers.get("Content-Length")).toBe(String(png.length));
    expect(image.headers.get("Cache-Control")).toBe("public, max-age=300");
    expect(image.headers.get("Content-Disposition")).toBe(
      'inline; filename="TX-adversarial.png"',
    );
    expect(image.headers.get("ETag")).toBe(`"${entry.asset_sha256}"`);
    expect(image.headers.get("X-Cadastre-Receipt")).toBeNull();
    expect(new Uint8Array(await image.arrayBuffer())).toEqual(png);
    const head = await call(
      "/v1/specimens/TX/adversarial",
      undefined,
      undefined,
      "HEAD",
    );
    expect(head.status).toBe(200);
    expect(head.headers.get("Content-Length")).toBe(String(png.length));
    expect(head.headers.get("ETag")).toBe(`"${entry.asset_sha256}"`);
    expect(await head.text()).toBe("");
  });
  it("reads public references with no database, signing secret, or delivery-audit dependency", async () => {
    await seedPublicReference();
    const db = new Proxy(env.DB, {
      get() {
        throw new Error("Public reference read reached private D1");
      },
    });
    const withoutAuthority = {
      ...testEnv,
      DB: db,
      CADASTRE_TRACE_KEY: "",
      CADASTRE_ADMIN_KEY_HASH: "",
      CADASTRE_INGEST_KEY_HASH: "",
    };
    for (const path of ["/v1/specimens", "/v1/specimens/TX/adversarial"]) {
      const response = await worker.fetch(
        new Request(origin + path),
        withoutAuthority,
      );
      expect(response.status).toBe(200);
      await response.arrayBuffer();
    }
  });
  it("keeps raw objects, unindexed references and encoded paths out of public access", async () => {
    await seedPublicReference();
    await env.VAULT.put("snapshots/security/raw.pdf", "PRIVATE_RAW_PDF");
    await env.VAULT.put("specimens/security/unindexed.png", png);
    for (const path of [
      "/v1/specimens/TX/unindexed",
      "/v1/specimens/TX/security%2fflat.png",
      "/v1/specimens/TX/%2e%2e/snapshots/security/raw.pdf",
      "/v1/specimens/TX/..%2f..%2fsnapshots%2fsecurity%2fraw.pdf",
      "/v1/specimens/TX/specimens/security/flat.png",
      "/v1/specimens/ZZ/adversarial",
      "/v1/specimens/tx/adversarial",
    ]) {
      const response = await call(path);
      expect(response.status).toBe(404);
      expect(await response.text()).not.toContain("PRIVATE_RAW_PDF");
    }
    expect(
      (await call("/internal/objects/snapshots/security/raw.pdf")).status,
    ).toBe(401);
    expect((await call("/internal/objects/" + entry.key)).status).toBe(401);
    expect((await call("/admin/access-requests")).status).toBe(401);
    const query = await call(
      "/v1/specimens/TX/adversarial?key=snapshots/security/raw.pdf",
    );
    expect(query.status).toBe(200);
    expect(new Uint8Array(await query.arrayBuffer())).toEqual(png);
  });
  it.each(["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])(
    "refuses public specimen writes and preflight (%s)",
    async (method) => {
      await seedPublicReference();
      const get = vi.spyOn(env.VAULT, "get");
      const put = vi.spyOn(env.VAULT, "put");
      const remove = vi.spyOn(env.VAULT, "delete");
      try {
        const response = await worker.fetch(
          new Request(origin + "/v1/specimens/TX/adversarial", {
            method,
            headers: { Authorization: "Bearer test-ingest-token" },
          }),
          testEnv,
        );
        expect(response.status).toBe(404);
        expect(get).not.toHaveBeenCalled();
        expect(put).not.toHaveBeenCalled();
        expect(remove).not.toHaveBeenCalled();
      } finally {
        get.mockRestore();
        put.mockRestore();
        remove.mockRestore();
      }
    },
  );
  it("uses an isolated anonymous read limit without starving policy or protected administration", async () => {
    await seedPublicReference();
    const publicLimit = vi.fn().mockResolvedValue({ success: true });
    const privateLimit = vi.fn().mockResolvedValue({ success: false });
    const isolated = {
      ...testEnv,
      PUBLIC_READ_LIMITER: { limit: publicLimit },
      RATE_LIMITER: { limit: privateLimit },
    };
    const readable = await worker.fetch(
      new Request(origin + "/v1/specimens"),
      isolated,
    );
    expect(readable.status).toBe(200);
    await readable.arrayBuffer();
    expect(publicLimit).toHaveBeenCalledTimes(1);
    expect(privateLimit).not.toHaveBeenCalled();
    const denied = {
      ...testEnv,
      PUBLIC_READ_LIMITER: { limit: async () => ({ success: false }) },
    };
    const get = vi.spyOn(env.VAULT, "get");
    try {
      const response = await worker.fetch(
        new Request(origin + "/v1/specimens/TX/adversarial"),
        denied,
      );
      expect(response.status).toBe(429);
      expect(await response.json()).toEqual({
        error: { code: "rate_limited" },
      });
      expect(get).not.toHaveBeenCalled();
      expect(
        (await worker.fetch(new Request(origin + "/v1/policy"), denied)).status,
      ).toBe(200);
      expect(
        (
          await worker.fetch(
            new Request(origin + "/admin/access-requests"),
            denied,
          )
        ).status,
      ).toBe(401);
    } finally {
      get.mockRestore();
    }
  });
  it("fails closed for absent, malformed and unsafe allowlists", async () => {
    await env.VAULT.delete("indexes/specimens.json");
    expect((await call("/v1/specimens")).status).toBe(503);
    for (const value of [
      "null",
      "not json",
      JSON.stringify([{ ...entry, key: "https://evil.invalid/flat.png" }]),
      JSON.stringify([{ ...entry, review_status: "approved" }]),
    ]) {
      await env.VAULT.put("indexes/specimens.json", value);
      expect(
        (await call("/v1/specimens/TX/adversarial")).status,
      ).toBeGreaterThanOrEqual(400);
    }
  });
  it("requires reference-only metadata and matching source and asset hashes before public delivery", async () => {
    await env.VAULT.put("indexes/specimens.json", JSON.stringify([entry]));
    await env.VAULT.delete(entry.key);
    expect((await call("/v1/specimens/TX/adversarial")).status).toBe(503);
    const metadata = {
      cadastreReferenceOnly: "true",
      sha256: entry.asset_sha256,
      sourceSha256: entry.source_sha256,
    };
    for (const patch of [
      { cadastreReferenceOnly: "false" },
      { sha256: "c".repeat(64) },
      { sourceSha256: "d".repeat(64) },
    ]) {
      await env.VAULT.put(entry.key, png, {
        httpMetadata: { contentType: "image/png" },
        customMetadata: { ...metadata, ...patch },
      });
      expect((await call("/v1/specimens/TX/adversarial")).status).toBe(503);
    }
    await env.VAULT.put(entry.key, png, {
      httpMetadata: { contentType: "application/octet-stream" },
      customMetadata: metadata,
    });
    expect((await call("/v1/specimens/TX/adversarial")).status).toBe(503);
  });
  it("refuses forged hash metadata and duplicate asset identities before delivering public bytes", async () => {
    const metadata = {
      cadastreReferenceOnly: "true",
      sha256: entry.asset_sha256,
      sourceSha256: entry.source_sha256,
    };
    await env.VAULT.put(entry.key, png, {
      httpMetadata: { contentType: "image/png" },
      customMetadata: metadata,
    });
    expect((await call("/v1/specimens/TX/adversarial")).status).toBe(503);
    const forged = "c".repeat(64);
    await env.VAULT.put(entry.key, png, {
      sha256: entry.asset_sha256,
      httpMetadata: { contentType: "image/png" },
      customMetadata: { ...metadata, sha256: forged },
    });
    await env.VAULT.put(
      "indexes/specimens.json",
      JSON.stringify([{ ...entry, asset_sha256: forged }]),
    );
    expect((await call("/v1/specimens/TX/adversarial")).status).toBe(503);
    await env.VAULT.put(
      "indexes/specimens.json",
      JSON.stringify([
        entry,
        { ...entry, key: "specimens/elsewhere/flat.png" },
      ]),
    );
    expect((await call("/v1/specimens")).status).toBe(503);
    await env.VAULT.put("indexes/specimens.json", JSON.stringify([entry]));
    await env.VAULT.put(entry.key, png, {
      sha256: entry.asset_sha256,
      httpMetadata: { contentType: "image/png" },
      customMetadata: metadata,
    });
  });
  it("rejects truncated or corrupted PNG headers before committing ingest objects", async () => {
    const corrupted = png.slice();
    corrupted[29] ^= 1;
    for (const [index, bytes] of [
      png.subarray(0, 15),
      png.subarray(0, 33),
      png.subarray(0, 45),
      png.subarray(0, png.length - 12),
      corrupted,
    ].entries()) {
      const digest = [
        ...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      ]
        .map((x) => x.toString(16).padStart(2, "0"))
        .join("");
      const objectKey = `specimens/security/bad-${index}.png`;
      const request = new Request(origin + "/internal/objects/" + objectKey, {
        method: "PUT",
        headers: {
          Authorization: "Bearer test-ingest-token",
          "Content-Type": "image/png",
          "Content-Length": String(bytes.length),
          "x-content-sha256": digest,
          "x-cadastre-reference-only": "true",
          "x-cadastre-source-sha256": entry.source_sha256,
        },
        body: bytes,
      });
      expect((await worker.fetch(request, testEnv)).status).toBe(400);
      expect(await env.VAULT.get(objectKey)).toBeNull();
    }
    const missingSource = new Request(
      origin + "/internal/objects/specimens/security/no-source.png",
      {
        method: "PUT",
        headers: {
          Authorization: "Bearer test-ingest-token",
          "Content-Type": "image/png",
          "Content-Length": String(png.length),
          "x-content-sha256": "b".repeat(64),
          "x-cadastre-reference-only": "true",
        },
        body: png,
      },
    );
    expect((await worker.fetch(missingSource, testEnv)).status).toBe(400);
  });
  it("keeps federal ingestion protected while indexed marked federal references are public", async () => {
    const federal = {
      ...entry,
      state: "US_FED",
      id: "passport_reference",
      key: "specimens/US_FED/reference.png",
      asset_sha256: [
        ...new Uint8Array(await crypto.subtle.digest("SHA-256", png)),
      ]
        .map((x) => x.toString(16).padStart(2, "0"))
        .join(""),
    };
    const request = new Request(origin + "/internal/objects/" + federal.key, {
      method: "PUT",
      headers: {
        Authorization: "Bearer test-ingest-token",
        "Content-Type": "image/png",
        "Content-Length": String(png.length),
        "x-content-sha256": federal.asset_sha256,
        "x-cadastre-reference-only": "true",
        "x-cadastre-source-sha256": federal.source_sha256,
      },
      body: png,
    });
    const anonymousHeaders = new Headers(request.headers);
    anonymousHeaders.delete("Authorization");
    expect(
      (
        await worker.fetch(
          new Request(request.clone(), { headers: anonymousHeaders }),
          testEnv,
        )
      ).status,
    ).toBe(401);
    expect((await worker.fetch(request, testEnv)).status).toBe(201);
    await env.VAULT.put(
      "indexes/specimens.json",
      JSON.stringify([{ ...federal, nominal_width_mm: 85.6 }]),
    );
    const path = "/v1/specimens/US_FED/passport_reference";
    expect((await call(path)).status).toBe(200);
    const listed = (await (await call("/v1/specimens")).json()) as {
      specimens: Record<string, unknown>[];
    };
    expect(listed.specimens[0]).toMatchObject({
      state: "US_FED",
      source_sha256: federal.source_sha256,
    });
    expect(listed.specimens[0]).not.toHaveProperty("nominal_width_mm");
    expect(listed.specimens[0]).not.toHaveProperty("key");
    const delivered = await call(path);
    expect(delivered.status).toBe(200);
    expect(delivered.headers.get("Content-Disposition")).toContain(
      "US_FED-passport_reference.png",
    );
    expect(delivered.headers.get("X-Cadastre-Receipt")).toBeNull();
    expect(new Uint8Array(await delivered.arrayBuffer())).toEqual(png);
    const head = await call(path, undefined, undefined, "HEAD");
    expect(head.status).toBe(200);
    expect(head.headers.get("Cache-Control")).toBe("public, max-age=300");
    expect(await head.text()).toBe("");
    expect((await call("/internal/objects/" + federal.key)).status).toBe(401);
    expect((await call("/v1/specimens/US_FED/other_reference")).status).toBe(
      404,
    );
    expect(
      (await call("/v1/specimens/US_FEDERAL/passport_reference")).status,
    ).toBe(404);
  });
});
describe("streaming PNG attribution", () => {
  it("preserves original PNG bytes and inserts tEXt with valid CRC across one-byte chunks", async () => {
    const original = Uint8Array.from(
      atob(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVNQAAAAASUVORK5CYII=",
      ),
      (c) => c.charCodeAt(0),
    );
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of original) controller.enqueue(new Uint8Array([byte]));
        controller.close();
      },
    });
    const bytes = new Uint8Array(
      await new Response(
        withPngReceipt(stream, "dl1.test.signature"),
      ).arrayBuffer(),
    );
    expect(bytes.subarray(0, 33)).toEqual(original.subarray(0, 33));
    const length = new DataView(bytes.buffer).getUint32(33);
    expect(new TextDecoder().decode(bytes.subarray(37, 41))).toBe("tEXt");
    expect(new TextDecoder().decode(bytes.subarray(41, 41 + length))).toBe(
      "Cadastre-Receipt\0dl1.test.signature",
    );
    let crc = 0xffffffff;
    for (const byte of bytes.subarray(37, 41 + length)) {
      crc ^= byte;
      for (let b = 0; b < 8; b++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
    expect(new DataView(bytes.buffer).getUint32(41 + length)).toBe(
      (crc ^ 0xffffffff) >>> 0,
    );
    expect(bytes.subarray(45 + length)).toEqual(original.subarray(33));
  });
  it("rejects invalid or truncated PNG streams", async () => {
    await expect(
      new Response(
        withPngReceipt(new Blob(["not png"]).stream(), "receipt"),
      ).arrayBuffer(),
    ).rejects.toThrow();
    const invalid = new Uint8Array(33);
    await expect(
      new Response(
        withPngReceipt(new Blob([invalid]).stream(), "receipt"),
      ).arrayBuffer(),
    ).rejects.toThrow("invalid_png");
  });
});
