import { CADASTRE_BROWSER_ORIGIN, isPublicCatalogPath } from "./core/edge-catalog";

/** Only the public catalog receives CORS. Other backend authorization is unchanged. */
export function catalogCors(request: Request, response: Response): Response {
  if (!["GET", "HEAD"].includes(request.method) ||
    !isPublicCatalogPath(new URL(request.url).pathname)) return response;
  const result = new Response(response.body, response);
  result.headers.append("Vary", "Origin");
  if (request.headers.get("Origin") === CADASTRE_BROWSER_ORIGIN)
    result.headers.set("Access-Control-Allow-Origin", CADASTRE_BROWSER_ORIGIN);
  return result;
}
