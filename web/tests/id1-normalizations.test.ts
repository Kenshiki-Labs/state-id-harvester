import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { env } from "cloudflare:workers";
import worker from "../src/worker";
import { id1NormalizationIndex } from "../src/core/id1-normalizations";
import { specimenIndex } from "../src/core/policy";

const origin = "https://cadastre.kenshikilabs.com";
const png = Uint8Array.from(
  atob(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVNQAAAAASUVORK5CYII=",
  ),
  (c) => c.charCodeAt(0),
);
const parent = {
  id: "native_card",
  state: "IL",
  key: "specimens/IL/original.png",
  source_sha256: "a".repeat(64),
  asset_sha256: "b".repeat(64),
  review_status: "reference_only" as const,
};
const normalized = {
  ...parent,
  key: "",
  asset_sha256: "",
  original_reference_sha256: parent.asset_sha256,
  canonical_asset_sha256: "c".repeat(64),
  width_px: 4280,
  height_px: 2699,
  boundary_basis: "visual_native_extent" as const,
};
const testEnv = {
  ...env,
  RATE_LIMITER: { limit: async () => ({ success: false }) },
  PUBLIC_READ_LIMITER: { limit: async () => ({ success: true }) },
};
const call = (
  path = "/v1/id1-normalizations",
  method = "GET",
  bindings = testEnv,
) => worker.fetch(new Request(origin + path, { method }), bindings);
const imagePath = "/v1/id1-normalizations/IL/native_card";
async function seedIndex(entries: unknown = [normalized]) {
  await env.VAULT.put(
    "indexes/id1-normalizations.json",
    JSON.stringify({ specimens: entries }),
  );
}
async function seedAsset(
  patch: Record<string, string> = {},
  contentType = "image/png",
  checksum = true,
) {
  await env.VAULT.put(normalized.key, png, {
    ...(checksum ? { sha256: normalized.asset_sha256 } : {}),
    httpMetadata: { contentType },
    customMetadata: {
      cadastreReferenceOnly: "true",
      sha256: normalized.asset_sha256,
      sourceSha256: normalized.source_sha256,
      ...patch,
    },
  });
}
beforeAll(async () => {
  normalized.asset_sha256 = [
    ...new Uint8Array(await crypto.subtle.digest("SHA-256", png)),
  ]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  normalized.key = `specimens/id1/${"d".repeat(64)}/${normalized.asset_sha256}.png`;
});
beforeEach(async () => {
  await env.VAULT.put("indexes/specimens.json", JSON.stringify([parent]));
  await seedIndex();
  await seedAsset();
});

describe("ID-1 derivative allowlist", () => {
  it("retains verified lineage and geometry while stripping private extras", () => {
    const input = {
      specimens: [
        {
          ...normalized,
          private_note: "secret",
          local_path: "/private/card.png",
        },
      ],
    };
    expect(id1NormalizationIndex(input, specimenIndex([parent]))).toEqual([
      normalized,
    ]);
    const vertical = {
      ...normalized,
      width_px: 2699,
      height_px: 4280,
      boundary_basis: "visual_card_corners",
    };
    expect(
      id1NormalizationIndex({ specimens: [vertical] }, specimenIndex([parent])),
    ).toEqual([vertical]);
  });
  it.each([
    { state: "US_FED" },
    { state: "ZZ" },
    { state: "il" },
    { id: "unknown" },
    { id: "../native_card" },
    { source_sha256: "d".repeat(64) },
    { original_reference_sha256: "d".repeat(64) },
    { canonical_asset_sha256: "invalid" },
    { width_px: 4281 },
    { height_px: 2700 },
    { width_px: "4280" },
    { boundary_basis: "assumed" },
    { review_status: "approved" },
    { key: "snapshots/private.png" },
    { key: "specimens/id1/../private.png" },
    { key: "specimens/id1/%2e%2e/private.png" },
    { key: "specimens/IL/original.png" },
    { key: `specimens/id1/${"d".repeat(64)}/${"e".repeat(64)}.png` },
    { asset_sha256: "g".repeat(64) },
  ])("rejects invalid or unbound derivative %j", (patch) => {
    expect(() =>
      id1NormalizationIndex(
        { specimens: [{ ...normalized, ...patch }] },
        specimenIndex([parent]),
      ),
    ).toThrow();
  });
  it("rejects missing parents, duplicates, absent fields and oversized indexes", () => {
    expect(() =>
      id1NormalizationIndex({ specimens: [normalized] }, []),
    ).toThrow();
    expect(() =>
      id1NormalizationIndex(
        { specimens: [normalized, normalized] },
        specimenIndex([parent]),
      ),
    ).toThrow();
    for (const value of [
      null,
      [],
      { specimens: null },
      { specimens: new Array(10001).fill(normalized) },
    ])
      expect(() =>
        id1NormalizationIndex(value, specimenIndex([parent])),
      ).toThrow();
    expect(() =>
      id1NormalizationIndex(
        {
          specimens: [{ ...normalized, original_reference_sha256: undefined }],
        },
        specimenIndex([parent]),
      ),
    ).toThrow();
  });
});

describe("public ID-1 derivatives", () => {
  it("lists only canonical public fields and supports anonymous GET/HEAD PNG streaming", async () => {
    await seedIndex([
      { ...normalized, private_note: "SECRET", local_path: "/private/image" },
    ]);
    const listing = await call();
    const { key: _key, ...publicEntry } = normalized;
    expect(listing.status).toBe(200);
    expect(listing.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(await listing.json()).toEqual({ specimens: [publicEntry] });
    const head = await call(undefined, "HEAD");
    expect(head.status).toBe(200);
    expect(await head.text()).toBe("");
    const image = await call(imagePath);
    expect(image.status).toBe(200);
    expect(image.headers.get("Content-Type")).toBe("image/png");
    expect(image.headers.get("Content-Length")).toBe(String(png.length));
    expect(image.headers.get("Cache-Control")).toBe("public, max-age=300");
    expect(image.headers.get("ETag")).toBe(`"${normalized.asset_sha256}"`);
    expect(new Uint8Array(await image.arrayBuffer())).toEqual(png);
    const imageHead = await call(imagePath, "HEAD");
    expect(imageHead.status).toBe(200);
    expect(imageHead.headers.get("Content-Length")).toBe(String(png.length));
    expect(await imageHead.text()).toBe("");
  });
  it("allows a missing optional index without losing original references", async () => {
    await env.VAULT.delete("indexes/id1-normalizations.json");
    expect(await (await call()).json()).toEqual({ specimens: [] });
    expect((await call(imagePath)).status).toBe(404);
    expect((await call("/v1/specimens")).status).toBe(200);
  });
  it.each([
    "not JSON",
    "null",
    JSON.stringify({
      specimens: [{ ...normalized, original_reference_sha256: "f".repeat(64) }],
    }),
  ])("fails closed for corrupted or forged index %s", async (value) => {
    await env.VAULT.put("indexes/id1-normalizations.json", value);
    expect((await call()).status).toBe(503);
    expect((await call(imagePath)).status).toBe(503);
  });
  it("requires a current matching original parent on every request", async () => {
    await env.VAULT.put(
      "indexes/specimens.json",
      JSON.stringify([{ ...parent, source_sha256: "f".repeat(64) }]),
    );
    expect((await call(imagePath)).status).toBe(503);
    await env.VAULT.delete("indexes/specimens.json");
    expect((await call()).status).toBe(503);
    await env.VAULT.put("indexes/specimens.json", "null");
    expect((await call()).status).toBe(503);
  });
  it.each([
    { cadastreReferenceOnly: "false" },
    { sha256: "f".repeat(64) },
    { sourceSha256: "f".repeat(64) },
  ])("requires verified derivative object metadata %j", async (patch) => {
    await seedAsset(patch);
    expect((await call(imagePath)).status).toBe(503);
  });
  it("rejects missing objects, missing checksums and incorrect media types", async () => {
    await env.VAULT.delete(normalized.key);
    expect((await call(imagePath)).status).toBe(503);
    await seedAsset({}, "application/octet-stream");
    expect((await call(imagePath)).status).toBe(503);
    await seedAsset({}, "image/png", false);
    expect((await call(imagePath)).status).toBe(503);
  });
  it("rejects forged matching index and metadata when the stored checksum differs", async () => {
    const forged = "f".repeat(64);
    const key = `specimens/id1/${"d".repeat(64)}/${forged}.png`;
    await seedIndex([{ ...normalized, key, asset_sha256: forged }]);
    await env.VAULT.put(key, png, {
      sha256: normalized.asset_sha256,
      httpMetadata: { contentType: "image/png" },
      customMetadata: {
        cadastreReferenceOnly: "true",
        sha256: forged,
        sourceSha256: normalized.source_sha256,
      },
    });
    expect((await call(imagePath)).status).toBe(503);
  });
  it("does not depend on private credentials or D1 and leaves internal objects protected", async () => {
    const publicOnly = {
      ...testEnv,
      CADASTRE_TRACE_KEY: "",
      CADASTRE_ADMIN_KEY_HASH: "",
      CADASTRE_INGEST_KEY_HASH: "",
      DB: new Proxy(env.DB, {
        get() {
          throw new Error("Private D1 accessed");
        },
      }),
      RATE_LIMITER: { limit: async () => ({ success: true }) },
    };
    const readable = await call(imagePath, "GET", publicOnly);
    expect(readable.status).toBe(200);
    await readable.arrayBuffer();
    for (const path of [
      `/internal/objects/${normalized.key}`,
      "/admin/access-requests",
    ])
      expect((await call(path, "GET", publicOnly)).status).toBe(401);
  });
  it.each([
    "/v1/id1-normalizations/US_FED/native_card",
    "/v1/id1-normalizations/ZZ/native_card",
    "/v1/id1-normalizations/IL/unindexed",
    "/v1/id1-normalizations/IL/%2e%2e/private",
    "/v1/id1-normalizations/IL/..%2fprivate",
    "/v1/id1-normalizations/IL/native_card.png",
    "/v1/id1-normalizations/il/native_card",
  ])("does not expose unindexed or encoded object paths: %s", async (path) => {
    expect((await call(path)).status).toBe(404);
  });
  it.each(["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])(
    "does not allow public writes (%s)",
    async (method) => {
      const put = vi.spyOn(env.VAULT, "put");
      try {
        const writableLimit = {
          ...testEnv,
          RATE_LIMITER: { limit: async () => ({ success: true }) },
        };
        expect((await call(imagePath, method, writableLimit)).status).toBe(404);
        expect(put).not.toHaveBeenCalled();
      } finally {
        put.mockRestore();
      }
    },
  );
  it("enforces the public limiter before reading either index", async () => {
    const get = vi.spyOn(env.VAULT, "get");
    try {
      const denied = {
        ...testEnv,
        PUBLIC_READ_LIMITER: { limit: async () => ({ success: false }) },
      };
      expect((await call(imagePath, "GET", denied)).status).toBe(429);
      expect(get).not.toHaveBeenCalled();
    } finally {
      get.mockRestore();
    }
  });
  it("cancels an oversized index stream before exposing any private content", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const originalGet = env.VAULT.get.bind(env.VAULT);
    const get = vi.spyOn(env.VAULT, "get");
    get.mockImplementation((async (key: string) =>
      key === "indexes/id1-normalizations.json"
        ? { size: 4 * 1024 * 1024 + 1, body }
        : originalGet(key)) as typeof env.VAULT.get);
    try {
      expect((await call()).status).toBe(503);
      expect(cancel).toHaveBeenCalledOnce();
    } finally {
      get.mockRestore();
    }
  });
  it("bounds a lying index stream and cancels it when streamed bytes exceed the limit", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(4 * 1024 * 1024 + 1));
      },
      cancel,
    });
    const originalGet = env.VAULT.get.bind(env.VAULT);
    const get = vi.spyOn(env.VAULT, "get");
    get.mockImplementation((async (key: string) =>
      key === "indexes/id1-normalizations.json"
        ? { size: 16, body }
        : originalGet(key)) as typeof env.VAULT.get);
    try {
      const response = await call();
      expect(response.status).toBe(503);
      expect(await response.text()).not.toContain("specimens/id1");
      expect(cancel).toHaveBeenCalledOnce();
    } finally {
      get.mockRestore();
    }
  });
});
