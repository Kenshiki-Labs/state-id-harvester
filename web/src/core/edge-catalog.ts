/** Public reference reads only. No administrative, ingestion or identity operations. */
export const CADASTRE_EDGE_BASE = "https://gateway.kenshikilabs.com/services/cadastre";
export const CADASTRE_BROWSER_ORIGIN = "https://cadastre.kenshikilabs.com";

export function isPublicCatalogPath(path: string): boolean {
  return /^\/v1\/(?:specimens|id1-normalizations)(?:\/(?:[A-Z]{2}|US_FED)\/[A-Za-z0-9_-]{1,150})?$/.test(path);
}

export function catalogApiUrl(path: string): string {
  if (!isPublicCatalogPath(path)) throw new Error("Unknown public catalog route");
  return `${CADASTRE_EDGE_BASE}${path}`;
}
