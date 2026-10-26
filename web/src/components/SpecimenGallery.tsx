import { useState } from "react";
import ImageViewer from "./ImageViewer";
import type { Source } from "../lib/catalog-model";
import { normalizationUrl, specimenUrl, type GalleryState, type PublicSpecimen } from "../lib/specimens";

function ReferenceCard({ item, source, number, name, onOpen }: Readonly<{ item: PublicSpecimen; source?: Source; number: number; name: string; onOpen: () => void }>) {
  const [failedUrls, setFailedUrls] = useState<string[]>([]);
  const failed = failedUrls.includes(specimenUrl(item));
  const normalizedFailed = failedUrls.includes(normalizationUrl(item));
  const normalized = Boolean(item.normalization) && !normalizedFailed;
  const url = normalized ? normalizationUrl(item) : specimenUrl(item);
  const normalization = normalized ? item.normalization : undefined;
  return <figure className="reference-card">
    <button className="reference-image-link" type="button" onClick={(event) => { event.currentTarget.focus({ preventScroll: true }); onOpen(); }} aria-haspopup="dialog" aria-label={`View ${name} reference image ${number}`}>
      {failed ? <span className="reference-image-failure">Image unavailable. Open the viewer to try again.</span> : <img src={url} alt={`${name} source reference ${number}; research specimen, review pending`} loading="lazy" decoding="async" onError={() => setFailedUrls((previous) => previous.includes(url) ? previous : [...previous, url])} />}
      <span className="reference-open">View image <span aria-hidden="true">⤢</span></span>
    </button>
    <figcaption><strong>Reference {String(number).padStart(2, "0")}</strong><span className="reference-status">{normalized ? "ID-1 normalized · review pending" : normalizedFailed ? "Original · ID-1 image unavailable" : item.state === "US_FED" ? "Original · review pending" : "Original · ID-1 pending"}</span>
      <details className="reference-provenance"><summary>Image provenance</summary>
        {source ? <p><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title} ↗</a><br/><span>{source.hostname}</span></p> : <p>Source publication fingerprint retained. A matching citation is not available in this source index.</p>}
        <dl><dt>Collection</dt><dd>{item.state}</dd><dt>Reference ID</dt><dd>{item.id}</dd><dt>Source SHA-256</dt><dd>{item.source_sha256}</dd><dt>Image SHA-256</dt><dd>{normalization?.asset_sha256 ?? item.asset_sha256}</dd>{normalization && <><dt>Original image SHA-256</dt><dd>{item.asset_sha256}</dd><dt>Geometry basis</dt><dd>{normalization.boundary_basis === "visual_native_extent" ? "Native image extent (approximate)" : "Visually identified card corners"}</dd><dt>Canonical card grid</dt><dd>{normalization.width_px} × {normalization.height_px} px</dd></>}</dl>
      </details>
    </figcaption>
  </figure>;
}
function GalleryContent({ gallery, items, name, sources, onOpen }: Readonly<{ gallery: GalleryState; items: PublicSpecimen[]; name: string; sources: Source[]; onOpen: (index: number) => void }>) {
  if (gallery.loading) return <output className="reference-message">Loading reference images…</output>;
  if (gallery.error) return <div className="reference-message" role="alert"><p>Reference images could not be loaded. This does not establish a coverage gap.</p><button className="text-link" type="button" onClick={gallery.retry}>Try again ↻</button></div>;
  if (items.length === 0) return <p className="reference-message">No reference images are published for this collection yet. See the source trail for available documents.</p>;
  return <>{gallery.normalizationStatus === "unavailable" && <p className="reference-message">ID-1 normalization index unavailable. Original references remain available.</p>}<p className="reference-caption">Select an image to inspect it in the viewer. These source references may include annotations, partial images or publication pages; they are not accepted verification templates.</p><div className="reference-grid">{items.map((item, index) => <ReferenceCard key={`${item.state}/${item.id}`} item={item} number={index + 1} name={name} onOpen={() => onOpen(index)} source={sources.find((source) => source.sha256 === item.source_sha256)} />)}</div></>;
}
export default function SpecimenGallery({ state, name, sources, gallery }: Readonly<{ state: string; name: string; sources: Source[]; gallery: GalleryState }>) {
  const [selected, setSelected] = useState<number | null>(null);
  const items = gallery.items.filter((item) => item.state === state);
  return <section className="reference-gallery" aria-label={`${name} reference images`} aria-busy={gallery.loading}>
    <div className="reference-gallery-heading"><h2>Reference images</h2>{!gallery.loading && !gallery.error && <span>{items.length} available</span>}</div>
    <GalleryContent gallery={gallery} items={items} name={name} sources={sources} onOpen={setSelected} />
    {selected !== null && !gallery.loading && !gallery.error && items[selected] && <ImageViewer items={items} index={selected} name={name} onNavigate={setSelected} onClose={() => setSelected(null)} />}
  </section>;
}
