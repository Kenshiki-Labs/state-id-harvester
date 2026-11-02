import { describe, expect, it } from "vitest";
import { env } from "cloudflare:workers";
import worker from "../src/worker";
import { stageBuildResponse } from "../src/stage-build";
import { STAGE_CADASTRE, PRODUCTION_CADASTRE, type CadastreEnv } from "../src/deployment";

const stage: CadastreEnv = {
  ...env,
  CADASTRE_DEPLOYMENT_ENVIRONMENT: "stage",
  PUBLIC_ORIGIN: STAGE_CADASTRE.origin,
  CADASTRE_ADMIN_KEY_HASH: "",
  CADASTRE_INGEST_KEY_HASH: "",
  CADASTRE_TRACE_KEY: "",
};

describe("private Stage build evidence", () => {
  it("returns only a stamped opaque token, without caching", async () => {
    const response = stageBuildResponse("a".repeat(32));
    expect(await response.json()).toEqual({ build: "a".repeat(32) });
    expect(response.headers.get("Cache-Control")).toBe("private, no-store");
  });
  it.each(["dev", "", "a".repeat(40), "g".repeat(32), "a".repeat(31) + "\n"])(
    "refuses invalid/unstamped token %j", token => {
      expect(() => stageBuildResponse(token)).toThrow("stage_build_unavailable");
    });
  it("does not claim an unstamped source checkout is live", async () => {
    const response = await worker.fetch(new Request(STAGE_CADASTRE.origin + "/__build"), stage);
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: { code: "stage_build_unavailable" } });
  });
  it("requires GET and the selected Stage origin", async () => {
    expect((await worker.fetch(new Request(STAGE_CADASTRE.origin + "/__build", { method: "POST" }), stage)).status).toBe(405);
    expect((await worker.fetch(new Request(PRODUCTION_CADASTRE.origin + "/__build"), stage)).status).toBe(403);
  });
  it("preserves production asset routing at the same path", async () => {
    let calls = 0;
    const production = { ...stage, PUBLIC_ORIGIN: PRODUCTION_CADASTRE.origin,
      CADASTRE_DEPLOYMENT_ENVIRONMENT: "production",
      ASSETS: { fetch: async () => { calls++; return new Response("existing-asset", { status: 404 }); } } as Fetcher,
    };
    const response = await worker.fetch(new Request(PRODUCTION_CADASTRE.origin + "/__build"), production);
    expect(calls).toBe(1);
    expect(response.status).toBe(404);
    expect(await response.text()).toBe("existing-asset");
  });
});
