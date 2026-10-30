import { PolicyError } from "./core/policy";

export type CadastreEnv = Omit<Env, "PUBLIC_ORIGIN" | "CADASTRE_DEPLOYMENT_ENVIRONMENT"> & {
  PUBLIC_ORIGIN: string;
  CADASTRE_DEPLOYMENT_ENVIRONMENT?: string;
  // Secret presence is checked by the existing route-specific authorization gates.
  CADASTRE_ADMIN_KEY_HASH: string;
  CADASTRE_INGEST_KEY_HASH: string;
  CADASTRE_TRACE_KEY: string;
};

export const PRODUCTION_CADASTRE = Object.freeze({
  name: "production",
  origin: "https://cadastre.kenshikilabs.com",
  keyPrefix: "kl_live_",
  imageCache: "cadastre-browser-images",
});

export const STAGE_CADASTRE = Object.freeze({
  name: "stage",
  origin: "https://cadastre-stage.kenshikilabs.com",
  keyPrefix: "kl_stage_",
  imageCache: "cadastre-stage-browser-images",
});

export type CadastreDeployment = typeof PRODUCTION_CADASTRE | typeof STAGE_CADASTRE;

export function cadastreDeployment(
  env: Pick<CadastreEnv, "CADASTRE_DEPLOYMENT_ENVIRONMENT" | "PUBLIC_ORIGIN">,
): CadastreDeployment {
  const name = env.CADASTRE_DEPLOYMENT_ENVIRONMENT;
  const profile = name === "stage" ? STAGE_CADASTRE
    : name === undefined || name === "production" ? PRODUCTION_CADASTRE : null;
  if (!profile || env.PUBLIC_ORIGIN !== profile.origin)
    throw new PolicyError("deployment_profile_unavailable", 503);
  return profile;
}
