import {
  AUP_TEXT,
  AUP_VERSION,
  PolicyError,
  field,
  record,
  safeObjectKey,
  specimenIndex,
  type Specimen,
  validateApplication,
} from "./core/policy";
import { validatePngHeader } from "./core/png";
import { id1NormalizationIndex } from "./core/id1-normalizations";
import { timingSafeEqual } from "node:crypto";
import { catalogCors } from "./catalog-cors";

const encoder = new TextEncoder();
const JSON_LIMIT = 16 * 1024;
const OBJECT_LIMIT = 50 * 1024 * 1024;
const now = () => new Date().toISOString();
const id = () => crypto.randomUUID();
const hex = (bytes: ArrayBuffer | Uint8Array) =>
  [...new Uint8Array(bytes)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
const randomHex = (n: number) => hex(crypto.getRandomValues(new Uint8Array(n)));
const base64url = (bytes: Uint8Array) =>
  btoa(String.fromCodePoint(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .split("=", 1)[0];
const sha = async (value: string) =>
  hex(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
function secureEqual(left: string, right: string): boolean {
  return (
    left.length === right.length &&
    timingSafeEqual(encoder.encode(left), encoder.encode(right))
  );
}
async function sign(env: Env, value: string): Promise<string> {
  if (!env.CADASTRE_TRACE_KEY || env.CADASTRE_TRACE_KEY.length < 24)
    throw new PolicyError("service_unavailable", 503);
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(env.CADASTRE_TRACE_KEY),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return `${value}.${base64url(new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(value))))}`;
}
function json(value: unknown, status = 200): Response {
  return Response.json(value, {
    status,
    headers: { "Cache-Control": "private, no-store" },
  });
}
async function boundedBytes(
  body: ReadableStream<Uint8Array> | null,
  limit: number,
): Promise<Uint8Array> {
  if (!body) throw new PolicyError("body_required");
  const chunks: Uint8Array[] = [];
  let size = 0;
  // Async iteration preserves the stream's sequential dependency and cancels
  // the reader automatically on an oversized body or interrupted operation.
  for await (const chunk of body) {
    size += chunk.length;
    if (size > limit) throw new PolicyError("body_too_large", 413);
    chunks.push(chunk);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return bytes;
}
async function bodyJson(request: Request): Promise<Record<string, unknown>> {
  const mediaType = request.headers
    .get("Content-Type")
    ?.split(";", 1)[0]
    .trim()
    .toLowerCase();
  if (mediaType !== "application/json")
    throw new PolicyError("json_required", 415);
  const length = request.headers.get("Content-Length");
  if (length && Number(length) > JSON_LIMIT)
    throw new PolicyError("body_too_large", 413);
  const bytes = await boundedBytes(request.body, JSON_LIMIT);
  try {
    return record(
      JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)),
    );
  } catch (error) {
    if (error instanceof PolicyError) throw error;
    throw new PolicyError("invalid_json");
  }
}
function sameOrigin(request: Request, env: Env): void {
  if (
    request.headers.get("Origin") !== env.PUBLIC_ORIGIN ||
    new URL(request.url).origin !== env.PUBLIC_ORIGIN
  )
    throw new PolicyError("origin_denied", 403);
}
async function bearer(request: Request, expected: string): Promise<void> {
  const auth = request.headers.get("Authorization") ?? "";
  if (
    !/^[a-f0-9]{64}$/.test(expected ?? "") ||
    !auth.startsWith("Bearer ") ||
    auth.length > 1024 ||
    !secureEqual(await sha(auth.slice(7)), expected)
  )
    throw new PolicyError("unauthorized", 401);
}
async function audit(
  env: Env,
  event: string,
  requestId: string | null,
  keyId: string | null = null,
  assetId: string | null = null,
  receipt: string | null = null,
  evidence: string | null = null,
): Promise<void> {
  await env.DB.prepare(
    "INSERT INTO audit_events(id,request_id,key_id,event,asset_id,receipt,evidence,created_at) VALUES(?,?,?,?,?,?,?,?)",
  )
    .bind(id(), requestId, keyId, event, assetId, receipt, evidence, now())
    .run();
}
interface ApplicationRow {
  id: string;
  status: string;
  claim_hash: string;
  domain_challenge: string;
  organization_domain: string;
  domain_verified_at: string | null;
  aup_version: string;
  aup_hash: string;
  accepted_at: string;
  attestation_receipt: string;
  claimed_at: string | null;
}
async function application(
  env: Env,
  requestId: string,
  body: Record<string, unknown>,
): Promise<ApplicationRow> {
  const token = field(body, "claim_token", 40, 128);
  const row = await env.DB.prepare("SELECT * FROM access_requests WHERE id=?")
    .bind(requestId)
    .first<ApplicationRow>();
  if (!row || !secureEqual(await sha(token), row.claim_hash))
    throw new PolicyError("invalid_claim", 403);
  return row;
}
async function createApplication(
  request: Request,
  env: Env,
): Promise<Response> {
  const applicant = validateApplication(await bodyJson(request));
  const requestId = id(),
    token = base64url(crypto.getRandomValues(new Uint8Array(32))),
    timestamp = now();
  const challenge = `cadastre=${randomHex(32)}`;
  const aupHash = await sha(AUP_TEXT);
  const receipt = await sign(env, `att1.${requestId}.${Date.now()}.${aupHash}`);
  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO access_requests(id,legal_name,registration_number,registration_jurisdiction,organization_domain,work_email,applicant_name,use_case,uei,cage,claim_hash,domain_challenge,aup_version,aup_hash,aup_text,accepted_at,attestation_receipt,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
    ).bind(
      requestId,
      applicant.legal_name,
      applicant.registration_number,
      applicant.registration_jurisdiction,
      applicant.organization_domain,
      applicant.work_email,
      applicant.applicant_name,
      applicant.use_case,
      applicant.uei,
      applicant.cage,
      await sha(token),
      challenge,
      AUP_VERSION,
      aupHash,
      AUP_TEXT,
      timestamp,
      receipt,
      timestamp,
    ),
    env.DB.prepare(
      "INSERT INTO audit_events(id,request_id,event,created_at) VALUES(?,?,?,?)",
    ).bind(id(), requestId, "application_received", timestamp),
  ]);
  return json(
    {
      request_id: requestId,
      status: "pending_review",
      domain_challenge: {
        name: `_cadastre-verification.${applicant.organization_domain}`,
        value: challenge,
      },
      claim_token: token,
      attestation_receipt: receipt,
    },
    201,
  );
}
function hasDomainProof(
  dns: Record<string, unknown>,
  row: ApplicationRow,
): boolean {
  if (dns.Status !== 0 || !Array.isArray(dns.Answer)) return false;
  return dns.Answer.some((value) => {
    const answer = record(value);
    const expectedName = `_cadastre-verification.${row.organization_domain}`;
    if (
      answer.type !== 16 ||
      typeof answer.data !== "string" ||
      typeof answer.name !== "string"
    )
      return false;
    if (answer.name.toLowerCase().replace(/\.$/, "") !== expectedName)
      return false;
    const fragments = [
      ...answer.data.matchAll(/"([^"\\]*(?:\\.[^"\\]*)*)"/g),
    ].map((m) => m[1]);
    return fragments.length > 0 && fragments.join("") === row.domain_challenge;
  });
}
async function verifyDomain(env: Env, row: ApplicationRow): Promise<Response> {
  if (row.status === "rejected") throw new PolicyError("request_rejected", 403);
  const endpoint = new URL("https://cloudflare-dns.com/dns-query");
  endpoint.searchParams.set(
    "name",
    `_cadastre-verification.${row.organization_domain}`,
  );
  endpoint.searchParams.set("type", "TXT");
  let verified = false;
  try {
    const result = await fetch(endpoint, {
      headers: { Accept: "application/dns-json" },
      signal: AbortSignal.timeout(5000),
      redirect: "manual",
    });
    if (!result.ok) throw new PolicyError("dns_unavailable", 503);
    const dns = record(
      JSON.parse(
        new TextDecoder().decode(await boundedBytes(result.body, 65536)),
      ),
    );
    verified = hasDomainProof(dns, row);
  } catch (error) {
    if (error instanceof PolicyError) throw error;
    throw new PolicyError("dns_unavailable", 503);
  }
  if (!verified) throw new PolicyError("domain_proof_not_found", 409);
  await env.DB.prepare(
    "UPDATE access_requests SET domain_verified_at=? WHERE id=?",
  )
    .bind(now(), row.id)
    .run();
  await audit(env, "domain_verified", row.id);
  return json({
    request_id: row.id,
    domain_verified: true,
    status: row.status,
    approval_granted: false,
  });
}
async function claimKey(env: Env, row: ApplicationRow): Promise<Response> {
  if (
    row.status !== "approved" ||
    !row.domain_verified_at ||
    row.aup_version !== AUP_VERSION ||
    row.aup_hash !== (await sha(AUP_TEXT))
  )
    throw new PolicyError("approval_required", 403);
  if (row.claimed_at) throw new PolicyError("key_already_claimed", 409);
  const keyId = randomHex(12),
    timestamp = now(),
    expires = new Date(Date.now() + 30 * 86400 * 1000).toISOString();
  const token = `kl_live_${keyId}_${base64url(crypto.getRandomValues(new Uint8Array(32)))}`;
  const results = await env.DB.batch([
    env.DB.prepare(
      `INSERT OR IGNORE INTO api_keys(id,request_id,key_hash,created_at,expires_at) SELECT ?,id,?,?,? FROM access_requests WHERE id=? AND status='approved' AND domain_verified_at IS NOT NULL AND claimed_at IS NULL AND aup_version=? AND aup_hash=?`,
    ).bind(
      keyId,
      await sha(token),
      timestamp,
      expires,
      row.id,
      AUP_VERSION,
      await sha(AUP_TEXT),
    ),
    env.DB.prepare(
      "UPDATE access_requests SET claimed_at=? WHERE id=? AND EXISTS(SELECT 1 FROM api_keys WHERE id=? AND request_id=?)",
    ).bind(timestamp, row.id, keyId, row.id),
    env.DB.prepare(
      "INSERT INTO audit_events(id,request_id,key_id,event,created_at) SELECT ?,request_id,id,'key_claimed',? FROM api_keys WHERE id=? AND request_id=?",
    ).bind(id(), timestamp, keyId, row.id),
  ]);
  if (results[0].meta.changes !== 1)
    throw new PolicyError("key_already_claimed", 409);
  return json({ api_key: token, key_id: keyId, expires_at: expires });
}
function matchesSpecimen(asset: R2ObjectBody, entry: Specimen): boolean {
  const checksum = asset.checksums.sha256;
  return (
    asset.size <= OBJECT_LIMIT &&
    asset.httpMetadata?.contentType === "image/png" &&
    asset.customMetadata?.cadastreReferenceOnly === "true" &&
    asset.customMetadata?.sha256 === entry.asset_sha256 &&
    asset.customMetadata?.sourceSha256 === entry.source_sha256 &&
    !!checksum &&
    hex(checksum) === entry.asset_sha256
  );
}
async function specimens(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  const object = await env.VAULT.get("indexes/specimens.json");
  if (!object || object.size > 4 * 1024 * 1024) {
    await object?.body.cancel();
    throw new PolicyError("catalog_unavailable", 503);
  }
  const index = specimenIndex(
    JSON.parse(
      new TextDecoder().decode(
        await boundedBytes(object.body, 4 * 1024 * 1024),
      ),
    ),
  );
  if (path === "/v1/specimens") {
    const body =
      request.method === "HEAD"
        ? null
        : JSON.stringify({
            specimens: index.map(({ key: _key, ...entry }) => entry),
          });
    return new Response(body, {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=60",
      },
    });
  }
  const match =
    /^\/v1\/specimens\/([A-Z]{2}|US_FED)\/([A-Za-z0-9_-]{1,150})$/.exec(path);
  const entry =
    match &&
    index.find((item) => item.state === match[1] && item.id === match[2]);
  if (!entry) throw new PolicyError("not_found", 404);
  return specimenImage(request, env, entry);
}
async function specimenImage(
  request: Request,
  env: Env,
  entry: Specimen,
): Promise<Response> {
  const view = browserView(request, entry);
  const asset = await env.VAULT.get(entry.key);
  if (!asset || !matchesSpecimen(asset, entry)) {
    await asset?.body.cancel();
    throw new PolicyError(ASSET_UNAVAILABLE, 503);
  }
  if (view) return browserImage(request, env, entry, asset, view);
  if (request.method === "HEAD") await asset.body.cancel();
  return new Response(request.method === "HEAD" ? null : asset.body, {
    headers: {
      "Content-Type": "image/png",
      "Content-Length": String(asset.size),
      "Cache-Control": "public, max-age=300",
      "Content-Disposition": `${new URL(request.url).searchParams.get("download") === "1" ? "attachment" : "inline"}; filename="${entry.state}-${entry.id}${new URL(request.url).pathname.startsWith("/v1/id1-normalizations/") ? "-id1" : ""}.png"`,
      ETag: `"${entry.asset_sha256}"`,
    },
  });
}
type BrowserView = "thumbnail" | "display";
const TRANSFORM_VERSION = "webp-1";
const WEBP_TYPE = "image/webp";
const ASSET_UNAVAILABLE = "asset_unavailable";
const TRANSFORM_INPUT_LIMIT = 20 * 1024 * 1024;
function browserView(request: Request, entry: Specimen): BrowserView | null {
  const query = new URL(request.url).searchParams;
  if (!query.has("view") && !query.has("v")) return null;
  const view = query.get("view");
  if (
    query.size !== 2 ||
    query.getAll("view").length !== 1 ||
    query.getAll("v").length !== 1 ||
    (view !== "thumbnail" && view !== "display") ||
    query.get("v") !== entry.asset_sha256
  )
    throw new PolicyError("invalid_image_view");
  return view;
}
function transformInput(
  body: ReadableStream<Uint8Array>,
): ReadableStream<Uint8Array> {
  let size = 0;
  return body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        size += chunk.byteLength;
        if (size > TRANSFORM_INPUT_LIMIT)
          throw new PolicyError(ASSET_UNAVAILABLE, 503);
        controller.enqueue(chunk);
      },
    }),
  );
}
function browserHeaders(
  entry: Specimen,
  view: BrowserView,
): Record<string, string> {
  return {
    "Content-Type": WEBP_TYPE,
    "Cache-Control": "public, max-age=86400",
    "Content-Disposition": `inline; filename="${entry.state}-${entry.id}-${view}.webp"`,
    ETag: `"${entry.asset_sha256}-${view}-${TRANSFORM_VERSION}"`,
    "X-Cadastre-Asset-Sha256": entry.asset_sha256,
    "X-Cadastre-Source-Sha256": entry.source_sha256,
    "X-Cadastre-Reference-Only": "true",
  };
}
async function browserImage(
  request: Request,
  env: Env,
  entry: Specimen,
  asset: R2ObjectBody,
  view: BrowserView,
): Promise<Response> {
  if (asset.size > TRANSFORM_INPUT_LIMIT) {
    await asset.body.cancel();
    throw new PolicyError(ASSET_UNAVAILABLE, 503);
  }
  const cacheUrl = new URL(new URL(request.url).pathname, env.PUBLIC_ORIGIN);
  cacheUrl.search = new URLSearchParams({
    view,
    v: entry.asset_sha256,
    transform: TRANSFORM_VERSION,
  }).toString();
  const cacheKey = new Request(cacheUrl, { method: "GET" });
  const cache = await caches.open("cadastre-browser-images");
  const cached = await cache.match(cacheKey);
  if (cached) {
    await asset.body.cancel();
    if (request.method === "HEAD") await cached.body?.cancel();
    return new Response(request.method === "HEAD" ? null : cached.body, cached);
  }
  const input = transformInput(asset.body);
  try {
    const width = view === "thumbnail" ? 640 : 1600;
    const output = await env.IMAGES.input(input)
      .transform({ width, height: width, fit: "scale-down" })
      .output({
        format: WEBP_TYPE,
        quality: view === "thumbnail" ? 82 : 90,
      });
    const transformed = output.response();
    if (
      !transformed.ok ||
      transformed.headers.get("Content-Type") !== WEBP_TYPE
    ) {
      await transformed.body?.cancel();
      throw new PolicyError(ASSET_UNAVAILABLE, 503);
    }
    const response = new Response(transformed.body, {
      headers: browserHeaders(entry, view),
    });
    await cache.put(cacheKey, response.clone());
    if (request.method !== "HEAD") return response;
    await response.body?.cancel();
    return new Response(null, response);
  } catch {
    if (!input.locked) await input.cancel().catch(() => undefined);
    throw new PolicyError(ASSET_UNAVAILABLE, 503);
  }
}
async function publicIndex(
  env: Env,
  key: string,
  optional = false,
): Promise<unknown> {
  const object = await env.VAULT.get(key);
  if (!object && optional) return { specimens: [] };
  if (!object || object.size > 4 * 1024 * 1024) {
    await object?.body.cancel();
    throw new PolicyError("catalog_unavailable", 503);
  }
  try {
    const bytes = await boundedBytes(object.body, 4 * 1024 * 1024);
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new PolicyError("catalog_unavailable", 503);
  }
}
async function id1Normalizations(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  let index;
  try {
    const originals = specimenIndex(
      await publicIndex(env, "indexes/specimens.json"),
    );
    index = id1NormalizationIndex(
      await publicIndex(env, "indexes/id1-normalizations.json", true),
      originals,
    );
  } catch {
    throw new PolicyError("catalog_unavailable", 503);
  }
  if (path === "/v1/id1-normalizations")
    return new Response(
      request.method === "HEAD"
        ? null
        : JSON.stringify({
            specimens: index.map(({ key: _key, ...entry }) => entry),
          }),
      {
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "public, max-age=60",
        },
      },
    );
  const match =
    /^\/v1\/id1-normalizations\/([A-Z]{2})\/([A-Za-z0-9_-]{1,150})$/.exec(path);
  const entry =
    match &&
    index.find((item) => item.state === match[1] && item.id === match[2]);
  if (!entry) throw new PolicyError("not_found", 404);
  return specimenImage(request, env, entry);
}
async function reviewApplication(
  request: Request,
  env: Env,
  requestId: string,
  action: string,
): Promise<Response> {
  const body = await bodyJson(request);
  const reviewer = field(body, "reviewer", 3, 200),
    evidence = field(body, "entity_evidence", 10, 2000),
    authorization = field(body, "authorization_evidence", 10, 2000);
  const row = await env.DB.prepare(
    "SELECT id,status,domain_verified_at FROM access_requests WHERE id=?",
  )
    .bind(requestId)
    .first<{ id: string; status: string; domain_verified_at: string | null }>();
  if (!row) throw new PolicyError("not_found", 404);
  const approving = action === "approve";
  if (approving && (!row.domain_verified_at || row.status !== "pending_review"))
    throw new PolicyError("verified_pending_request_required", 409);
  const timestamp = now(),
    status = approving ? "approved" : "rejected",
    approvedAt = approving ? timestamp : null;
  const results = await env.DB.batch([
    env.DB.prepare(
      `UPDATE access_requests SET status=?,approved_at=?,reviewer=?,entity_evidence=?,authorization_evidence=? WHERE id=? AND (?!='approved' OR (status='pending_review' AND domain_verified_at IS NOT NULL))`,
    ).bind(
      status,
      approvedAt,
      reviewer,
      evidence,
      authorization,
      row.id,
      status,
    ),
    env.DB.prepare(
      "INSERT INTO audit_events(id,request_id,event,evidence,created_at) SELECT ?,id,?,?,? FROM access_requests WHERE id=? AND status=? AND reviewer=? AND approved_at IS ?",
    ).bind(
      id(),
      `request_${status}`,
      JSON.stringify({
        reviewer,
        entity_evidence: evidence,
        authorization_evidence: authorization,
      }),
      timestamp,
      row.id,
      status,
      reviewer,
      approvedAt,
    ),
  ]);
  if (results[0].meta.changes !== 1)
    throw new PolicyError("request_state_changed", 409);
  return json({ request_id: row.id, status });
}
async function revokeKey(
  request: Request,
  env: Env,
  keyId: string,
): Promise<Response> {
  const body = await bodyJson(request),
    reviewer = field(body, "reviewer", 3, 200),
    reason = field(body, "reason", 5, 1000);
  const row = await env.DB.prepare("SELECT request_id FROM api_keys WHERE id=?")
    .bind(keyId)
    .first<{ request_id: string }>();
  if (!row) throw new PolicyError("not_found", 404);
  await env.DB.batch([
    env.DB.prepare("UPDATE api_keys SET revoked_at=? WHERE id=?").bind(
      now(),
      keyId,
    ),
    env.DB.prepare(
      "INSERT INTO audit_events(id,request_id,key_id,event,evidence,created_at) VALUES(?,?,?,?,?,?)",
    ).bind(
      id(),
      row.request_id,
      keyId,
      "key_revoked",
      JSON.stringify({ reviewer, reason }),
      now(),
    ),
  ]);
  return json({ key_id: keyId, revoked: true });
}
async function admin(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  await bearer(request, env.CADASTRE_ADMIN_KEY_HASH);
  if (path === "/admin/access-requests" && request.method === "GET") {
    const rows = await env.DB.prepare(
      `SELECT id,legal_name,registration_number,registration_jurisdiction,organization_domain,work_email,applicant_name,use_case,uei,cage,domain_verified_at,aup_version,accepted_at,created_at FROM access_requests WHERE status='pending_review' ORDER BY created_at LIMIT 100`,
    ).all();
    return json({ requests: rows.results });
  }
  const match =
    /^\/admin\/access-requests\/([a-f0-9-]{36})\/(approve|reject)$/.exec(path);
  if (match && request.method === "POST")
    return reviewApplication(request, env, match[1], match[2]);
  const revoke = /^\/admin\/keys\/([a-f0-9]{24})\/revoke$/.exec(path);
  if (revoke && request.method === "POST")
    return revokeKey(request, env, revoke[1]);
  throw new PolicyError("not_found", 404);
}
function uploadParameters(request: Request, key: string) {
  const checksum = request.headers.get("x-content-sha256") ?? "";
  const length = Number(request.headers.get("Content-Length"));
  const body = request.body;
  if (!body || !Number.isInteger(length) || length < 1 || length > OBJECT_LIMIT)
    throw new PolicyError("bounded_content_length_required", 413);
  if (!/^[a-f0-9]{64}$/.test(checksum))
    throw new PolicyError("sha256_required");
  const contentType =
    request.headers.get("Content-Type") ?? "application/octet-stream";
  const reference =
    key.startsWith("specimens/") &&
    key.endsWith(".png") &&
    contentType === "image/png" &&
    request.headers.get("x-cadastre-reference-only") === "true";
  if (key.startsWith("specimens/") && !reference)
    throw new PolicyError("reference_only_png_required");
  const sourceSha = request.headers.get("x-cadastre-source-sha256") ?? "";
  if (reference && !/^[a-f0-9]{64}$/.test(sourceSha))
    throw new PolicyError("source_sha256_required");
  return { body, length, checksum, contentType, reference, sourceSha };
}
async function uploadObject(
  request: Request,
  env: Env,
  key: string,
): Promise<Response> {
  const { body, length, checksum, contentType, reference, sourceSha } =
    uploadParameters(request, key);
  const bounded = new FixedLengthStream(length);
  const input = reference ? validatePngHeader(body) : body;
  // R2 validates the expected checksum before committing the streamed object.
  const writes = await Promise.allSettled([
    input.pipeTo(bounded.writable),
    env.VAULT.put(key, bounded.readable, {
      sha256: checksum,
      httpMetadata: { contentType },
      customMetadata: {
        sha256: checksum,
        sourceSha256: sourceSha,
        cadastreReferenceOnly: reference ? "true" : "false",
      },
    }),
  ]);
  if (writes.some((result) => result.status === "rejected"))
    throw new PolicyError("object_integrity_failed", 400);
  return json({ key, sha256: checksum, stored: true }, 201);
}
async function internal(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  await bearer(request, env.CADASTRE_INGEST_KEY_HASH);
  const key = path.slice("/internal/objects/".length);
  if (!safeObjectKey(key)) throw new PolicyError("invalid_object_key");
  if (request.method === "GET") {
    const result = await env.VAULT.get(key);
    if (!result) throw new PolicyError("not_found", 404);
    return new Response(result.body, {
      headers: {
        "Content-Type":
          result.httpMetadata?.contentType ?? "application/octet-stream",
        "Cache-Control": "private, no-store",
        "X-Content-Sha256": result.customMetadata?.sha256 ?? "",
      },
    });
  }
  if (request.method !== "PUT")
    throw new PolicyError("method_not_allowed", 405);
  return uploadObject(request, env, key);
}
function headers(response: Response): Response {
  const result = new Response(response.body, response);
  result.headers.set("X-Content-Type-Options", "nosniff");
  result.headers.set("Referrer-Policy", "no-referrer");
  result.headers.set("X-Frame-Options", "DENY");
  result.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=()",
  );
  result.headers.set(
    "Strict-Transport-Security",
    "max-age=31536000; includeSubDomains",
  );
  // Astro supplies script hashes in its generated HTML meta CSP. This header adds
  // non-overridable boundaries without invalidating those per-page hashes.
  result.headers.set(
    "Content-Security-Policy",
    "frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'",
  );
  return result;
}
async function accessRoute(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  sameOrigin(request, env);
  if (path === "/v1/access-requests") return createApplication(request, env);
  const match =
    /^\/v1\/access-requests\/([a-f0-9-]{36})\/(verify-domain|status|claim-key)$/.exec(
      path,
    );
  if (!match) throw new PolicyError("not_found", 404);
  const row = await application(env, match[1], await bodyJson(request));
  if (match[2] === "verify-domain") return verifyDomain(env, row);
  if (match[2] === "claim-key") return claimKey(env, row);
  return json({
    request_id: row.id,
    status: row.status,
    domain_verified: !!row.domain_verified_at,
    key_claimed: !!row.claimed_at,
  });
}
async function apiRoute(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  let category = "public";
  if (path.startsWith("/internal/")) category = "ingest";
  if (path.startsWith("/admin/")) category = "admin";
  const fingerprint = await sha(
    `${category}:${request.headers.get("CF-Connecting-IP") ?? "local"}`,
  );
  const publicRead =
    ["GET", "HEAD"].includes(request.method) &&
    (path === "/v1/specimens" ||
      path.startsWith("/v1/specimens/") ||
      path === "/v1/id1-normalizations" ||
      path.startsWith("/v1/id1-normalizations/"));
  let limiter = env.RATE_LIMITER;
  if (category === "ingest") limiter = env.INGEST_LIMITER;
  if (publicRead) limiter = env.PUBLIC_READ_LIMITER;
  if (!(await limiter.limit({ key: fingerprint })).success)
    throw new PolicyError("rate_limited", 429);
  if (path === "/v1/policy" && request.method === "GET")
    return json({
      version: AUP_VERSION,
      text: AUP_TEXT,
      sha256: await sha(AUP_TEXT),
    });
  if (path.startsWith("/admin/")) return admin(request, env, path);
  if (path.startsWith("/internal/objects/"))
    return internal(request, env, path);
  if (request.method === "POST" && path.startsWith("/v1/access-requests"))
    return accessRoute(request, env, path);
  if (publicRead)
    return path.startsWith("/v1/id1-normalizations")
      ? id1Normalizations(request, env, path)
      : specimens(request, env, path);
  throw new PolicyError("not_found", 404);
}
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      const path = new URL(request.url).pathname;
      if (path === "/health") return headers(json({ ok: true }));
      if (/^\/(v1|admin|internal)(\/|$)/.test(path))
        return catalogCors(request, headers(await apiRoute(request, env, path)));
      if (!["GET", "HEAD"].includes(request.method))
        throw new PolicyError("method_not_allowed", 405);
      if (path === "/access" || path === "/access/")
        return headers(Response.redirect(`${env.PUBLIC_ORIGIN}/catalog`, 301));
      return headers(await env.ASSETS.fetch(request));
    } catch (error) {
      const failure =
        error instanceof PolicyError
          ? error
          : new PolicyError("service_unavailable", 503);
      return catalogCors(request, headers(json({ error: { code: failure.code } }, failure.status)));
    }
  },
} satisfies ExportedHandler<Env>;
