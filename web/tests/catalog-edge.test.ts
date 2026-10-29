import { describe, expect, it, vi } from "vitest";
import { CADASTRE_EDGE_BASE, CADASTRE_BROWSER_ORIGIN, catalogApiUrl, isPublicCatalogPath } from "../src/core/edge-catalog";
import { catalogFetch } from "../src/lib/catalog-transport";
import { catalogCors } from "../src/catalog-cors";

describe("canonical public reference transport", () => {
  it.each(["/admin/access-requests", "/internal/objects/snapshots/raw", "/v1/access-requests", "/v1/specimens/WA/../private", "/v1/specimens/WA/a%2fb", "//attacker.invalid/v1/specimens", "https://cadastre.kenshikilabs.com/v1/specimens", "/v1/specimens?token=secret"])("refuses alternate operations and URL spellings: %s", (path) => {
    expect(isPublicCatalogPath(path)).toBe(false);
    expect(() => catalogApiUrl(path)).toThrow("Unknown public catalog route");
  });

  it("preserves caller cancellation, sends no cookies and never retries a refused redirect", async () => {
    const signal = new AbortController().signal;
    const dispatch = vi.fn().mockRejectedValue(new TypeError("redirect refused"));
    await expect(catalogFetch("/v1/specimens", signal, dispatch as typeof fetch)).rejects.toThrow("redirect refused");
    expect(dispatch).toHaveBeenCalledExactlyOnceWith(`${CADASTRE_EDGE_BASE}/v1/specimens`, {
      signal, credentials: "omit", redirect: "error",
    });
  });

  it("varies public catalog responses on Origin, with CORS only for the actual website", async () => {
    for (const origin of [CADASTRE_BROWSER_ORIGIN, "https://attacker.invalid", "null", null]) {
      const request = new Request("https://cadastre.kenshikilabs.com/v1/specimens", {
        headers: origin === null ? {} : { Origin: origin },
      });
      const response = catalogCors(request, Response.json({ specimens: [] }, { status: 200 }));
      expect(response.headers.get("Vary")).toBe("Origin");
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(origin === CADASTRE_BROWSER_ORIGIN ? origin : null);
      expect(response.headers.has("Access-Control-Allow-Credentials")).toBe(false);
      expect(await response.json()).toEqual({ specimens: [] });
    }
  });

  it.each(["/admin/access-requests", "/internal/objects/snapshots/raw", "/v1/access-requests"])("does not create CORS authority for %s", (path) => {
    const response = new Response("denied", { status: 401 });
    expect(catalogCors(new Request(`https://cadastre.kenshikilabs.com${path}`, { headers: { Origin: CADASTRE_BROWSER_ORIGIN } }), response)).toBe(response);
  });

  it("does not classify a catalog write or preflight as a public read", () => {
    for (const method of ["POST", "DELETE", "PUT", "OPTIONS"]) {
      const response = new Response("denied", { status: 405 });
      expect(catalogCors(new Request("https://cadastre.kenshikilabs.com/v1/specimens", { method, headers: { Origin: CADASTRE_BROWSER_ORIGIN } }), response)).toBe(response);
    }
  });
});
