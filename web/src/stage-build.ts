import { PolicyError } from "./core/policy";

// Only the isolated Stage archive is stamped by the guarded release executor.
export const STAGE_BUILD = "dev";

export function stageBuildResponse(build: string = STAGE_BUILD): Response {
  if (build.length !== 32 || !/^[a-f0-9]+$/.test(build))
    throw new PolicyError("stage_build_unavailable", 503);
  return Response.json({ build }, { headers: { "Cache-Control": "private, no-store" } });
}
