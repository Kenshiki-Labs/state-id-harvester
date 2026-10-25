import { beforeAll, describe, expect, it, vi } from "vitest";
import { env } from "cloudflare:workers";
import worker from "../src/worker";
import schema from "../migrations/0001_access.sql?raw";
import { AUP_TEXT, AUP_VERSION } from "../src/core/policy";
import { withPngReceipt } from "../src/core/png";
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
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
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
    await env.DB.prepare("UPDATE api_keys SET expires_at=? WHERE id=?")
      .bind("2000-01-01T00:00:00.000Z", key.key_id)
      .run();
    expect((await call("/v1/specimens", undefined, key.api_key)).status).toBe(
      401,
    );
    await env.DB.prepare("UPDATE api_keys SET expires_at=? WHERE id=?")
      .bind("2999-01-01T00:00:00.000Z", key.key_id)
      .run();
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
    const receipt = downloaded.headers.get("X-Cadastre-Receipt");
    expect(receipt).toMatch(/^dl1\.[a-f0-9-]+\.\d+\.[\w-]+$/);
    const bytes = new Uint8Array(await downloaded.arrayBuffer());
    expect(new TextDecoder().decode(bytes)).toContain(
      "Cadastre-Receipt\0" + receipt,
    );
    const delivery = await env.DB.prepare(
      "SELECT receipt FROM audit_events WHERE key_id=? AND event='specimen_delivered'",
    )
      .bind(key.key_id)
      .first();
    expect(delivery?.receipt).toBe(receipt);
    expect(downloaded.headers.get("Cache-Control")).toBe("private, no-store");
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
    expect((await call("/v1/specimens", undefined, key.api_key)).status).toBe(
      401,
    );
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
  it("a valid DNS proof still cannot list private specimens or claim an unapproved key", async () => {
    const result = await create();
    const half = result.domain_challenge.value.length / 2;
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
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
    expect(
      (await call("/v1/specimens", undefined, result.claim_token)).status,
    ).toBe(401);
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
    const key = (await issued.json()) as { api_key: string };
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
    expect((await call("/v1/specimens", undefined, key.api_key)).status).toBe(
      401,
    );
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
    expect(
      (await call("/v1/specimens", undefined, key.api_key.slice(0, -1) + "!"))
        .status,
    ).toBe(401);
  });
  it("fails closed for private paths and missing credentials", async () => {
    expect((await call("/v1/specimens")).status).toBe(401);
    expect(
      (await call("/internal/objects/indexes/specimens.json")).status,
    ).toBe(401);
    expect((await call("/v1/not-a-real-route")).status).toBe(404);
    expect((await call("/v1")).status).toBe(404);
    expect((await call("/admin/access-requests")).status).toBe(401);
  });
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
    ).toBe(401);
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
describe("adversarial private catalog delivery", () => {
  let apiKey: string, requestId: string;
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
    const result = await create();
    requestId = result.request_id;
    await env.DB.prepare(
      "UPDATE access_requests SET status='approved',domain_verified_at=? WHERE id=?",
    )
      .bind(new Date().toISOString(), requestId)
      .run();
    const response = await call(`/v1/access-requests/${requestId}/claim-key`, {
      claim_token: result.claim_token,
    });
    const issued = (await response.json()) as { api_key: string };
    apiKey = issued.api_key;
  });
  it("fails closed for absent, malformed and unsafe allowlists", async () => {
    await env.VAULT.delete("indexes/specimens.json");
    expect((await call("/v1/specimens", undefined, apiKey)).status).toBe(503);
    for (const value of [
      "null",
      "not json",
      JSON.stringify([{ ...entry, key: "https://evil.invalid/flat.png" }]),
      JSON.stringify([{ ...entry, review_status: "approved" }]),
    ]) {
      await env.VAULT.put("indexes/specimens.json", value);
      expect(
        (await call("/v1/specimens/TX/adversarial", undefined, apiKey)).status,
      ).toBeGreaterThanOrEqual(400);
    }
  });
  it("requires reference-only metadata and matching source and asset hashes before audit or delivery", async () => {
    await env.VAULT.put("indexes/specimens.json", JSON.stringify([entry]));
    await env.VAULT.delete(entry.key);
    expect(
      (await call("/v1/specimens/TX/adversarial", undefined, apiKey)).status,
    ).toBe(503);
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
      expect(
        (await call("/v1/specimens/TX/adversarial", undefined, apiKey)).status,
      ).toBe(503);
    }
    await env.VAULT.put(entry.key, png, {
      httpMetadata: { contentType: "application/octet-stream" },
      customMetadata: metadata,
    });
    expect(
      (await call("/v1/specimens/TX/adversarial", undefined, apiKey)).status,
    ).toBe(503);
    const deliveries = await env.DB.prepare(
      "SELECT COUNT(*) AS count FROM audit_events WHERE request_id=? AND event='specimen_delivered'",
    )
      .bind(requestId)
      .first();
    expect(deliveries?.count).toBe(0);
  });
  it("delivers no PNG if the mandatory audit transaction fails", async () => {
    await env.VAULT.put(entry.key, png, {
      httpMetadata: { contentType: "image/png" },
      customMetadata: {
        cadastreReferenceOnly: "true",
        sha256: entry.asset_sha256,
        sourceSha256: entry.source_sha256,
      },
    });
    await env.DB.prepare(
      "CREATE TRIGGER fail_delivery_audit BEFORE INSERT ON audit_events WHEN NEW.event='specimen_delivered' BEGIN SELECT RAISE(ABORT,'audit unavailable'); END",
    ).run();
    try {
      const response = await call(
        "/v1/specimens/TX/adversarial",
        undefined,
        apiKey,
      );
      expect(response.status).toBe(503);
      expect(response.headers.get("Content-Type")).toContain(
        "application/json",
      );
      expect(await response.json()).toEqual({
        error: { code: "service_unavailable" },
      });
    } finally {
      await env.DB.prepare("DROP TRIGGER fail_delivery_audit").run();
    }
    const response = await call(
      "/v1/specimens/TX/adversarial",
      undefined,
      apiKey,
    );
    expect(response.status).toBe(200);
    await response.arrayBuffer();
  });
  it("rejects truncated or corrupted PNG headers before committing ingest objects", async () => {
    const corrupted = png.slice();
    corrupted[29] ^= 1;
    for (const [index, bytes] of [png.subarray(0, 15), corrupted].entries()) {
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
  it("gates federal specimen ingestion, listing and attributed delivery with the same authority checks", async () => {
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
    expect((await worker.fetch(request, testEnv)).status).toBe(201);
    await env.VAULT.put(
      "indexes/specimens.json",
      JSON.stringify([{ ...federal, nominal_width_mm: 85.6 }]),
    );
    const path = "/v1/specimens/US_FED/passport_reference";
    expect((await call(path)).status).toBe(401);
    expect((await call(path, undefined, "test-ingest-token")).status).toBe(401);
    const listed = (await (
      await call("/v1/specimens", undefined, apiKey)
    ).json()) as { specimens: Record<string, unknown>[] };
    expect(listed.specimens[0]).toMatchObject({
      state: "US_FED",
      source_sha256: federal.source_sha256,
    });
    expect(listed.specimens[0]).not.toHaveProperty("nominal_width_mm");
    expect(listed.specimens[0]).not.toHaveProperty("key");
    const delivered = await call(path, undefined, apiKey);
    expect(delivered.status).toBe(200);
    expect(delivered.headers.get("Content-Disposition")).toContain(
      "US_FED-passport_reference.png",
    );
    const receipt = delivered.headers.get("X-Cadastre-Receipt");
    expect(new TextDecoder().decode(await delivered.arrayBuffer())).toContain(
      "Cadastre-Receipt\0" + receipt,
    );
    const audit = await env.DB.prepare(
      "SELECT receipt FROM audit_events WHERE request_id=? AND asset_id=? AND event='specimen_delivered'",
    )
      .bind(requestId, federal.id)
      .first();
    expect(audit?.receipt).toBe(receipt);
    expect(
      (await call("/v1/specimens/US_FED/other_reference", undefined, apiKey))
        .status,
    ).toBe(404);
    expect(
      (
        await call(
          "/v1/specimens/US_FEDERAL/passport_reference",
          undefined,
          apiKey,
        )
      ).status,
    ).toBe(404);
    await env.DB.prepare("UPDATE api_keys SET revoked_at=? WHERE request_id=?")
      .bind(new Date().toISOString(), requestId)
      .run();
    expect((await call(path, undefined, apiKey)).status).toBe(401);
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
