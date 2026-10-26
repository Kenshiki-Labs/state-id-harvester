import { useEffect, useState } from "react";
import { JURISDICTIONS, object } from "./catalog-model";

export interface PublicSpecimen {
  id: string;
  state: string;
  source_sha256: string;
  asset_sha256: string;
  review_status: "reference_only";
}
const collections = new Set<string>([...JURISDICTIONS.map(([code]) => code), "US_FED"]);
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
export function parseSpecimens(input: unknown): PublicSpecimen[] {
  const list = object(input).specimens;
  if (!Array.isArray(list) || list.length > 10000) throw new Error("Invalid image index");
  const identities = new Set<string>();
  return list.map((value) => {
    const row = object(value);
    if (typeof row.id !== "string" || !/^[a-zA-Z0-9_-]{1,150}$/.test(row.id) || typeof row.state !== "string" || !collections.has(row.state) || !hash(row.source_sha256) || !hash(row.asset_sha256) || row.review_status !== "reference_only") throw new Error("Invalid image index");
    const identity = `${row.state}/${row.id}`;
    if (identities.has(identity)) throw new Error("Invalid image index");
    identities.add(identity);
    return { id: row.id, state: row.state, source_sha256: row.source_sha256, asset_sha256: row.asset_sha256, review_status: row.review_status };
  });
}
export function specimenUrl(item: PublicSpecimen): string {
  return `/v1/specimens/${encodeURIComponent(item.state)}/${encodeURIComponent(item.id)}`;
}
export async function loadSpecimens(signal: AbortSignal, transport: typeof fetch = fetch) {
  const response = await transport("/v1/specimens", { signal, credentials: "omit" });
  if (!response.ok) throw new Error("Image index unavailable");
  return parseSpecimens(await response.json());
}
export interface GalleryState { items: PublicSpecimen[]; loading: boolean; error: boolean; retry: () => void }
export function useSpecimens(): GalleryState {
  const [items, setItems] = useState<PublicSpecimen[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    loadSpecimens(controller.signal).then((next) => {
      if (!controller.signal.aborted) { setItems(next); setLoading(false); }
    }).catch(() => {
      if (!controller.signal.aborted) { setError(true); setLoading(false); }
    });
    return () => controller.abort();
  }, [attempt]);
  return { items, loading, error, retry: () => setAttempt((value) => value + 1) };
}
