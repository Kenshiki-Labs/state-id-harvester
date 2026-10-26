import { PolicyError, record, specimenIndex, type Specimen } from "./policy";

export interface Id1Normalization extends Specimen {
  original_reference_sha256: string;
  canonical_asset_sha256: string;
  width_px: number;
  height_px: number;
  boundary_basis: "visual_native_extent" | "visual_card_corners";
}

const HASH = /^[a-f0-9]{64}$/;
function validGeometry(entry: Record<string, unknown>): boolean {
  return (
    ((entry.width_px === 4280 && entry.height_px === 2699) ||
      (entry.width_px === 2699 && entry.height_px === 4280)) &&
    (entry.boundary_basis === "visual_native_extent" ||
      entry.boundary_basis === "visual_card_corners")
  );
}

/** Geometry derivatives must retain an exact, immutable original-reference parent. */
export function id1NormalizationIndex(
  input: unknown,
  originals: Specimen[],
): Id1Normalization[] {
  const list = record(input).specimens;
  // The original parser enforces bounded counts, known collections and unique ids.
  const entries = specimenIndex({ specimens: list });
  const parents = new Map(
    originals.map((entry) => [`${entry.state}/${entry.id}`, entry]),
  );
  return entries.map((entry, position) => {
    const raw = record((list as unknown[])[position]);
    const parent = parents.get(`${entry.state}/${entry.id}`);
    const canonicalHash = raw.canonical_asset_sha256;
    if (
      entry.state === "US_FED" ||
      entry.source_sha256 !== parent?.source_sha256 ||
      raw.original_reference_sha256 !== parent.asset_sha256 ||
      typeof canonicalHash !== "string" ||
      !HASH.test(canonicalHash) ||
      !validGeometry(raw) ||
      !new RegExp(
        String.raw`^specimens/id1/[a-f0-9]{64}/${entry.asset_sha256}\.png$`,
      ).test(entry.key)
    )
      throw new PolicyError("invalid_id1_normalization_index", 503);
    return {
      ...entry,
      original_reference_sha256: parent.asset_sha256,
      canonical_asset_sha256: canonicalHash,
      width_px: raw.width_px as number,
      height_px: raw.height_px as number,
      boundary_basis: raw.boundary_basis as Id1Normalization["boundary_basis"],
    };
  });
}
