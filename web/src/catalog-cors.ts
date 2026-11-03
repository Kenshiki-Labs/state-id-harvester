import { CADASTRE_BROWSER_ORIGIN, isPublicCatalogPath } from "./core/edge-catalog";
import type { CadastreDeployment } from "./deployment";

/** Only the public catalog receives CORS. Other backend authorization is unchanged. */
export function catalogCors(request: Request, response: Response, profile?: CadastreDeployment): Response {
  if (!["GET", "HEAD"].includes(request.method) ||
    !isPublicCatalogPath(new URL(request.url).pathname)) return response;
  const result = new Response(response.body, response);
  result.headers.append("Vary", "Origin");
  const origin = profile?.origin ?? CADASTRE_BROWSER_ORIGIN;
  if (request.headers.get("Origin") === origin)
    result.headers.set("Access-Control-Allow-Origin", origin);
  return result;
}
