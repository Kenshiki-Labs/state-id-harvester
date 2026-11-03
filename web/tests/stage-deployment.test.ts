import { describe, expect, it } from "vitest";
import { env } from "cloudflare:workers";
import worker from "../src/worker";
import { cadastreDeployment, PRODUCTION_CADASTRE, STAGE_CADASTRE, type CadastreEnv } from "../src/deployment";

const stage: CadastreEnv = {
  ...env,
  CADASTRE_DEPLOYMENT_ENVIRONMENT: "stage",
  PUBLIC_ORIGIN: STAGE_CADASTRE.origin,
  CADASTRE_ADMIN_KEY_HASH: "",
  CADASTRE_INGEST_KEY_HASH: "",
  CADASTRE_TRACE_KEY: "",
  RATE_LIMITER: { limit: async () => ({ success: true }) },
  PUBLIC_READ_LIMITER: { limit: async () => ({ success: true }) },
};

describe("Cadastre deployment isolation", () => {
  it("selects exactly one authority and preserves production defaults", () => {
    expect(cadastreDeployment({ PUBLIC_ORIGIN: PRODUCTION_CADASTRE.origin })).toBe(PRODUCTION_CADASTRE);
    expect(cadastreDeployment(stage)).toBe(STAGE_CADASTRE);
    expect(STAGE_CADASTRE.keyPrefix).not.toBe(PRODUCTION_CADASTRE.keyPrefix);
    expect(STAGE_CADASTRE.imageCache).not.toBe(PRODUCTION_CADASTRE.imageCache);
  });

  it.each([
    { CADASTRE_DEPLOYMENT_ENVIRONMENT: "unknown" },
    { PUBLIC_ORIGIN: PRODUCTION_CADASTRE.origin },
    { PUBLIC_ORIGIN: "https://attacker.invalid" },
    { CADASTRE_DEPLOYMENT_ENVIRONMENT: undefined },
  ])("rejects mixed or unknown configuration before routing: %j", async (change) => {
    const response = await worker.fetch(new Request(STAGE_CADASTRE.origin + "/health"), { ...stage, ...change });
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: { code: "deployment_profile_unavailable" } });
  });

  it("rejects cross-environment request origins in both directions", async () => {
    const production = { ...stage, PUBLIC_ORIGIN: PRODUCTION_CADASTRE.origin, CADASTRE_DEPLOYMENT_ENVIRONMENT: "production" };
    expect((await worker.fetch(new Request(PRODUCTION_CADASTRE.origin + "/health"), stage)).status).toBe(403);
    expect((await worker.fetch(new Request(STAGE_CADASTRE.origin + "/health"), production)).status).toBe(403);
    expect((await worker.fetch(new Request(STAGE_CADASTRE.origin + "/v1/policy"), stage)).status).toBe(200);
  });

  it("keeps bearer authorization on the Stage administrative path", async () => {
    const response = await worker.fetch(new Request(STAGE_CADASTRE.origin + "/admin/access-requests"), stage);
    expect(response.status).toBe(401);
  });

  it("grants public-read CORS only to the selected profile", async () => {
    for (const origin of [STAGE_CADASTRE.origin, PRODUCTION_CADASTRE.origin]) {
      const response = await worker.fetch(new Request(STAGE_CADASTRE.origin + "/v1/specimens", { headers: { Origin: origin } }), stage);
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(origin === STAGE_CADASTRE.origin ? origin : null);
      expect(response.headers.has("Access-Control-Allow-Credentials")).toBe(false);
    }
  });
});
