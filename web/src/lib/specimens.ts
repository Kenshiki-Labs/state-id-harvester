import { useEffect, useState } from "react";
import { JURISDICTIONS, object } from "./catalog-model";

export interface PublicSpecimen {
  id: string;
  state: string;
  source_sha256: string;
  asset_sha256: string;
  review_status: "reference_only";
  normalization?: ID1Normalization;
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
export interface ID1Normalization extends Omit<PublicSpecimen, "normalization"> {
  original_reference_sha256: string;
  canonical_asset_sha256: string;
  width_px: number;
  height_px: number;
  boundary_basis: "visual_native_extent" | "visual_card_corners";
}
export function parseNormalizations(input: unknown): ID1Normalization[] {
  const base = parseSpecimens(input);
  const rows = object(input).specimens as unknown[];
  return base.map((item, index) => {
    const row = object(rows[index]);
    const dimensions = (row.width_px === 4280 && row.height_px === 2699) || (row.width_px === 2699 && row.height_px === 4280);
    if (item.state === "US_FED" || !hash(row.original_reference_sha256) || !hash(row.canonical_asset_sha256) || !dimensions || (row.boundary_basis !== "visual_native_extent" && row.boundary_basis !== "visual_card_corners")) throw new Error("Invalid normalization index");
    return { ...item, original_reference_sha256: row.original_reference_sha256, canonical_asset_sha256: row.canonical_asset_sha256, width_px: row.width_px as number, height_px: row.height_px as number, boundary_basis: row.boundary_basis };
  });
}
export function joinNormalizations(items: PublicSpecimen[], normalizations: ID1Normalization[]): PublicSpecimen[] {
  const index = new Map(normalizations.map((row) => [`${row.state}/${row.id}`, row]));
  return items.map(({ normalization: ignored, ...item }) => {
    const row = index.get(`${item.state}/${item.id}`);
    return row?.source_sha256 === item.source_sha256 && row.original_reference_sha256 === item.asset_sha256 ? { ...item, normalization: row } : item;
  });
}
export function normalizationUrl(item: PublicSpecimen): string {
  return `/v1/id1-normalizations/${encodeURIComponent(item.state)}/${encodeURIComponent(item.id)}`;
}
export async function loadNormalizations(signal: AbortSignal, transport: typeof fetch = fetch): Promise<ID1Normalization[]> {
  const response = await transport("/v1/id1-normalizations", { signal, credentials: "omit" });
  if (!response.ok) throw new Error("Normalization index unavailable");
  return parseNormalizations(await response.json());
}
export interface GalleryState { items: PublicSpecimen[]; loading: boolean; error: boolean; retry: () => void; normalizationStatus?: "loading" | "ready" | "unavailable" }
export function useSpecimens(): GalleryState {
  const [items, setItems] = useState<PublicSpecimen[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [normalizations, setNormalizations] = useState<ID1Normalization[]>([]);
  const [normalizationStatus, setNormalizationStatus] = useState<"loading" | "ready" | "unavailable">("loading");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    setNormalizations([]);
    setNormalizationStatus("loading");
    loadNormalizations(controller.signal).then((next) => {
      if (!controller.signal.aborted) { setNormalizations(next); setNormalizationStatus("ready"); }
    }).catch(() => {
      if (!controller.signal.aborted) setNormalizationStatus("unavailable");
    });
    loadSpecimens(controller.signal).then((next) => {
      if (!controller.signal.aborted) { setItems(next); setLoading(false); }
    }).catch(() => {
      if (!controller.signal.aborted) { setError(true); setLoading(false); }
    });
    return () => controller.abort();
  }, [attempt]);
  return { items: joinNormalizations(items, normalizations), normalizationStatus, loading, error, retry: () => setAttempt((value) => value + 1) };
}
