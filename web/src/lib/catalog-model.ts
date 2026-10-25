export const JURISDICTIONS = [
  ["AL", "Alabama"],
  ["AK", "Alaska"],
  ["AZ", "Arizona"],
  ["AR", "Arkansas"],
  ["CA", "California"],
  ["CO", "Colorado"],
  ["CT", "Connecticut"],
  ["DE", "Delaware"],
  ["DC", "District of Columbia"],
  ["FL", "Florida"],
  ["GA", "Georgia"],
  ["HI", "Hawaii"],
  ["ID", "Idaho"],
  ["IL", "Illinois"],
  ["IN", "Indiana"],
  ["IA", "Iowa"],
  ["KS", "Kansas"],
  ["KY", "Kentucky"],
  ["LA", "Louisiana"],
  ["ME", "Maine"],
  ["MD", "Maryland"],
  ["MA", "Massachusetts"],
  ["MI", "Michigan"],
  ["MN", "Minnesota"],
  ["MS", "Mississippi"],
  ["MO", "Missouri"],
  ["MT", "Montana"],
  ["NE", "Nebraska"],
  ["NV", "Nevada"],
  ["NH", "New Hampshire"],
  ["NJ", "New Jersey"],
  ["NM", "New Mexico"],
  ["NY", "New York"],
  ["NC", "North Carolina"],
  ["ND", "North Dakota"],
  ["OH", "Ohio"],
  ["OK", "Oklahoma"],
  ["OR", "Oregon"],
  ["PA", "Pennsylvania"],
  ["RI", "Rhode Island"],
  ["SC", "South Carolina"],
  ["SD", "South Dakota"],
  ["TN", "Tennessee"],
  ["TX", "Texas"],
  ["UT", "Utah"],
  ["VT", "Vermont"],
  ["VA", "Virginia"],
  ["WA", "Washington"],
  ["WV", "West Virginia"],
  ["WI", "Wisconsin"],
  ["WY", "Wyoming"],
] as const;
export interface Source {
  title: string;
  url: string;
  hostname: string;
  relevance: "candidate" | "quarantined" | "unreviewed";
  sha256?: string;
}
export interface Jurisdiction {
  code: string;
  name: string;
  sources: Source[];
  relevantPdfs: number;
  nativeImages: number;
  renderedPages: number;
  proposals: number;
  acceptedCohorts: number;
}
export interface FederalCollection extends Jurisdiction {
  code: "US_FED";
  credentialFormat: "unclassified";
}
export type CatalogFilter = "all" | "sources" | "awaiting";
export const emptyJurisdiction = (
  code: string,
  name: string,
): Jurisdiction => ({
  code,
  name,
  sources: [],
  relevantPdfs: 0,
  nativeImages: 0,
  renderedPages: 0,
  proposals: 0,
  acceptedCohorts: 0,
});
export const blankCatalog = (): Jurisdiction[] =>
  JURISDICTIONS.map(([code, name]) => emptyJurisdiction(code, name));
export function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
const count = (value: unknown): number =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : 0;
function sourceRecord(value: unknown): Source | null {
  const source = object(value);
  if (typeof source.url !== "string") return null;
  try {
    const url = new URL(source.url);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return {
      title:
        typeof source.title === "string" && source.title.trim()
          ? source.title.slice(0, 1000)
          : url.hostname,
      url: url.href,
      hostname: url.hostname,
      relevance:
        source.relevance === "candidate" || source.relevance === "quarantined"
          ? source.relevance
          : "unreviewed",
      ...(typeof source.sha256 === "string" &&
      /^[a-f0-9]{64}$/i.test(source.sha256)
        ? { sha256: source.sha256 }
        : {}),
    };
  } catch {
    return null;
  }
}
function normalizeSources(value: unknown): Source[] {
  return Array.isArray(value)
    ? value
        .map(sourceRecord)
        .filter((source): source is Source => source !== null)
    : [];
}
function jurisdictionRecord(
  base: Jurisdiction,
  row: Record<string, unknown>,
): Jurisdiction {
  const counts = object(row.counts);
  return {
    ...base,
    sources: normalizeSources(row.sources),
    relevantPdfs: count(counts.relevant_sources),
    nativeImages: count(counts.embedded_images),
    renderedPages: count(counts.rendered_pages),
    proposals: count(counts.crop_candidates),
    acceptedCohorts: count(counts.accepted_cohorts),
  };
}
// The public index is an observation manifest. It never supplies runtime acceptance rules.
export function normalizeCatalog(value: unknown): Jurisdiction[] {
  const data = object(value);
  if (!Array.isArray(data.jurisdictions))
    throw new Error("Invalid source index");
  const entries = data.jurisdictions.map(object);
  return blankCatalog().map((base) => {
    const row = entries.find((entry) => entry.code === base.code);
    return row ? jurisdictionRecord(base, row) : base;
  });
}
export function normalizeFederal(value: unknown): FederalCollection | null {
  const data = object(value);
  if (data.federal === undefined || data.federal === null) return null;
  const federal = object(data.federal);
  if (federal.code !== "US_FED" || federal.credential_format !== "unclassified")
    throw new Error("Invalid federal source index");
  return {
    ...jurisdictionRecord(
      emptyJurisdiction("US_FED", "United States federal"),
      federal,
    ),
    code: "US_FED",
    credentialFormat: "unclassified",
  };
}
export function catalogFilter(value: string): CatalogFilter {
  return value === "sources" || value === "awaiting" ? value : "all";
}
export function filterCatalog(
  rows: Jurisdiction[],
  query: string,
  filter: CatalogFilter,
): Jurisdiction[] {
  const search = query.trim().toLowerCase();
  return rows.filter(
    (row) =>
      `${row.name} ${row.code}`.toLowerCase().includes(search) &&
      (filter === "all" ||
        (filter === "sources"
          ? row.sources.length > 0
          : row.sources.length === 0)),
  );
}
