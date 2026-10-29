import { catalogApiUrl } from "../core/edge-catalog";

/** Anonymous reads have one physical destination and never follow a redirect. */
export function catalogFetch(path: string, signal: AbortSignal, transport: typeof fetch = fetch): Promise<Response> {
  return transport(catalogApiUrl(path), { signal, credentials: "omit", redirect: "error" });
}
