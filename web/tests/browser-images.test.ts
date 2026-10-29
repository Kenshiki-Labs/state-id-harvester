import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { env } from "cloudflare:workers";
import worker from "../src/worker";

const origin = "https://cadastre.kenshikilabs.com";
const png = Uint8Array.from(
  atob(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVNQAAAAASUVORK5CYII=",
  ),
  (c) => c.charCodeAt(0),
);
const entry = {
  id: "browser_card",
  state: "IL",
  key: "specimens/IL/browser.png",
  source_sha256: "a".repeat(64),
  asset_sha256: "",
  review_status: "reference_only",
};
let sequence = 0;
const allowed = { limit: async () => ({ success: true }) };
const testEnv = { ...env, PUBLIC_READ_LIMITER: allowed, RATE_LIMITER: allowed };
const path = () => `/v1/specimens/IL/${entry.id}`;
const mockedBytes = new TextEncoder().encode("MOCK_WEBP_BINDING_OUTPUT");
const url = (view = "thumbnail") =>
  `${path()}?view=${view}&v=${entry.asset_sha256}`;
const call = (query = url(), method = "GET", bindings = testEnv) =>
  worker.fetch(new Request(origin + query, { method }), bindings);
async function seed() {
  await env.VAULT.put("indexes/specimens.json", JSON.stringify([entry]));
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
function mockImages(
  options: { failure?: boolean; contentType?: string; status?: number } = {},
) {
  let received: ReadableStream<Uint8Array>;
  const output = vi.fn(async () => {
    await new Response(received).arrayBuffer();
    if (options.failure) throw new Error("Images unavailable");
    return {
      response: () =>
        new Response("MOCK_WEBP_BINDING_OUTPUT", {
          status: options.status ?? 200,
          headers: { "Content-Type": options.contentType ?? "image/webp" },
        }),
      contentType: () => "image/webp",
      image: () => new Blob(["MOCK_WEBP_BINDING_OUTPUT"]).stream(),
    };
  });
  const transform = vi.fn(() => transformer);
  const transformer: ImageTransformer = {
    transform,
    output,
    draw: () => transformer,
  };
  const input = vi.fn((body: ReadableStream<Uint8Array>) => {
    received = body;
    return transformer;
  });
  const images = new Proxy(env.IMAGES, {
    get(target, property, receiver) {
      if (property === "input") return input;
      return Reflect.get(target, property, receiver);
    },
  });
  return { input, transform, output, bindings: { ...testEnv, IMAGES: images } };
}
beforeAll(async () => {
  entry.asset_sha256 = [
    ...new Uint8Array(await crypto.subtle.digest("SHA-256", png)),
  ]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
});
beforeEach(async () => {
  entry.id = `browser_card_${++sequence}`;
  await seed();
});

describe("bounded browser image transformations", () => {
  it("preserves verified PNG bytes with CORS and an attachment filename for a cross-origin download", async () => {
    const response = await worker.fetch(new Request(`${origin}${path()}?download=1`, {
      headers: { Origin: origin },
    }), testEnv);
    expect(response.status).toBe(200);
    expect(response.headers.get("Access-Control-Allow-Origin")).toBe(origin);
    expect(response.headers.has("Access-Control-Allow-Credentials")).toBe(false);
    expect(response.headers.get("Content-Disposition")).toBe(`attachment; filename="IL-${entry.id}.png"`);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(png);
    const ordinary = await call(path());
    expect(ordinary.headers.get("Content-Disposition")).toBe(`inline; filename="IL-${entry.id}.png"`);
    await ordinary.body?.cancel();
  });

  it("keeps failed reference reads observable through the same narrow CORS policy", async () => {
    const response = await worker.fetch(new Request(`${origin}/v1/specimens/IL/not_indexed`, {
      headers: { Origin: origin },
    }), testEnv);
    expect(response.status).toBe(404);
    expect(response.headers.get("Access-Control-Allow-Origin")).toBe(origin);
    expect(await response.json()).toEqual({ error: { code: "not_found" } });
  });
  it.each([
    ["thumbnail", 640, 82],
    ["display", 1600, 90],
  ] as const)(
    "uses the fixed %s profile, streams verified R2 bytes and caches WebP",
    async (view, width, quality) => {
      const mock = mockImages();
      const response = await call(url(view), "GET", mock.bindings);
      expect(response.status).toBe(200);
      expect(response.headers.get("Content-Type")).toBe("image/webp");
      expect(response.headers.get("Cache-Control")).toBe(
        "public, max-age=86400",
      );
      expect(response.headers.get("X-Cadastre-Asset-Sha256")).toBe(
        entry.asset_sha256,
      );
      expect(response.headers.get("X-Cadastre-Source-Sha256")).toBe(
        entry.source_sha256,
      );
      expect(response.headers.get("X-Cadastre-Reference-Only")).toBe("true");
      expect(new Uint8Array(await response.arrayBuffer())).toEqual(mockedBytes);
      expect(mock.transform).toHaveBeenCalledExactlyOnceWith({
        width,
        height: width,
        fit: "scale-down",
      });
      expect(mock.output).toHaveBeenCalledExactlyOnceWith({
        format: "image/webp",
        quality,
      });
      const cached = await call(url(view), "GET", mock.bindings);
      expect(new Uint8Array(await cached.arrayBuffer())).toEqual(mockedBytes);
      expect(mock.input).toHaveBeenCalledOnce();
      const head = await call(url(view), "HEAD", mock.bindings);
      expect(head.status).toBe(200);
      expect(head.headers.get("Content-Type")).toBe("image/webp");
      expect(await head.text()).toBe("");
      expect(mock.input).toHaveBeenCalledOnce();
    },
  );
  it("creates a cacheable transform for HEAD misses without returning a body", async () => {
    const mock = mockImages();
    const head = await call(url(), "HEAD", mock.bindings);
    expect(head.status).toBe(200);
    expect(await head.text()).toBe("");
    expect(mock.input).toHaveBeenCalledOnce();
    const get = await call(url(), "GET", mock.bindings);
    expect(new Uint8Array(await get.arrayBuffer())).toEqual(mockedBytes);
    expect(mock.input).toHaveBeenCalledOnce();
  });
  it.each([
    "view=thumbnail",
    "v=HASH",
    "view=invalid&v=HASH",
    "view=thumbnail&v=stale",
    "view=thumbnail&view=display&v=HASH",
    "view=thumbnail&v=HASH&v=HASH",
    "view=thumbnail&v=HASH&width=9999",
    "view=thumbnail&v=HASH&url=https://evil.invalid",
  ])(
    "rejects stale hashes, arbitrary sources and noncanonical query %s",
    async (query) => {
      const mock = mockImages();
      const response = await call(
        `${path()}?${query.replaceAll("HASH", entry.asset_sha256)}`,
        "GET",
        mock.bindings,
      );
      expect(response.status).toBe(400);
      expect(mock.input).not.toHaveBeenCalled();
    },
  );
  it("keeps the original PNG bytes and metadata unchanged", async () => {
    const mock = mockImages();
    const original = await call(path(), "GET", mock.bindings);
    expect(original.status).toBe(200);
    expect(original.headers.get("Content-Type")).toBe("image/png");
    expect(original.headers.get("ETag")).toBe(`"${entry.asset_sha256}"`);
    expect(new Uint8Array(await original.arrayBuffer())).toEqual(png);
    const head = await call(path(), "HEAD", mock.bindings);
    expect(await head.text()).toBe("");
    expect(mock.input).not.toHaveBeenCalled();
  });
  it.each([{ failure: true }, { contentType: "image/png" }, { status: 503 }])(
    "fails closed without a heavy PNG fallback when the binding fails %j",
    async (options) => {
      const mock = mockImages(options);
      const response = await call(url(), "GET", mock.bindings);
      expect(response.status).toBe(503);
      expect(response.headers.get("Content-Type")).toContain(
        "application/json",
      );
      expect(await response.text()).not.toContain("MOCK_WEBP");
    },
  );
  it("requires a valid current source object even after a WebP is cached", async () => {
    const mock = mockImages();
    await (await call(url(), "GET", mock.bindings)).arrayBuffer();
    await env.VAULT.delete(entry.key);
    expect((await call(url(), "GET", mock.bindings)).status).toBe(503);
    await seed();
    await env.VAULT.put(entry.key, png, {
      sha256: entry.asset_sha256,
      httpMetadata: { contentType: "image/png" },
      customMetadata: {
        cadastreReferenceOnly: "true",
        sha256: entry.asset_sha256,
        sourceSha256: "f".repeat(64),
      },
    });
    expect((await call(url(), "GET", mock.bindings)).status).toBe(503);
    await env.VAULT.put("indexes/specimens.json", "null");
    expect(
      (await call(url(), "GET", mock.bindings)).status,
    ).toBeGreaterThanOrEqual(400);
    expect(mock.input).toHaveBeenCalledOnce();
  });
  it("validates normalized lineage before consulting cached browser bytes", async () => {
    const mock = mockImages();
    const normalized = {
      ...entry,
      key: `specimens/id1/${"d".repeat(64)}/${entry.asset_sha256}.png`,
      original_reference_sha256: entry.asset_sha256,
      canonical_asset_sha256: "c".repeat(64),
      width_px: 4280,
      height_px: 2699,
      boundary_basis: "visual_native_extent",
    };
    const asset = await env.VAULT.get(entry.key);
    await env.VAULT.put(normalized.key, asset!.body, {
      sha256: entry.asset_sha256,
      httpMetadata: asset!.httpMetadata,
      customMetadata: asset!.customMetadata,
    });
    await env.VAULT.put(
      "indexes/id1-normalizations.json",
      JSON.stringify({ specimens: [normalized] }),
    );
    const query = url().replace("/v1/specimens/", "/v1/id1-normalizations/");
    expect((await call(query, "GET", mock.bindings)).status).toBe(200);
    await env.VAULT.put(
      "indexes/specimens.json",
      JSON.stringify([{ ...entry, asset_sha256: "f".repeat(64) }]),
    );
    expect((await call(query, "GET", mock.bindings)).status).toBe(503);
    expect(mock.input).toHaveBeenCalledOnce();
  });
  it("rejects metadata-declared inputs larger than the binding limit", async () => {
    const mock = mockImages();
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const originalGet = env.VAULT.get.bind(env.VAULT);
    const stored = await originalGet(entry.key);
    await stored!.body.cancel();
    const get = vi.spyOn(env.VAULT, "get");
    get.mockImplementation((async (key: string) =>
      key === entry.key
        ? { ...stored, size: 20 * 1024 * 1024 + 1, body }
        : originalGet(key)) as typeof env.VAULT.get);
    try {
      expect((await call(url(), "GET", mock.bindings)).status).toBe(503);
      expect(cancel).toHaveBeenCalledOnce();
      expect(mock.input).not.toHaveBeenCalled();
    } finally {
      get.mockRestore();
    }
  });
  it("cancels a lying source stream when its bytes exceed 20 MiB", async () => {
    const mock = mockImages();
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(20 * 1024 * 1024 + 1));
      },
      cancel,
    });
    const originalGet = env.VAULT.get.bind(env.VAULT);
    const stored = await originalGet(entry.key);
    await stored!.body.cancel();
    const get = vi.spyOn(env.VAULT, "get");
    get.mockImplementation((async (key: string) =>
      key === entry.key
        ? { ...stored, body }
        : originalGet(key)) as typeof env.VAULT.get);
    try {
      expect((await call(url(), "GET", mock.bindings)).status).toBe(503);
      expect(cancel).toHaveBeenCalledOnce();
    } finally {
      get.mockRestore();
    }
  });
  it("canonicalizes parameter order without merging distinct profiles", async () => {
    const mock = mockImages();
    await (await call(url(), "GET", mock.bindings)).arrayBuffer();
    await (
      await call(
        `${path()}?v=${entry.asset_sha256}&view=thumbnail`,
        "GET",
        mock.bindings,
      )
    ).arrayBuffer();
    expect(mock.input).toHaveBeenCalledOnce();
    await (await call(url("display"), "GET", mock.bindings)).arrayBuffer();
    expect(mock.input).toHaveBeenCalledTimes(2);
  });
});
