import { useState } from "react";
import type { Source } from "../lib/catalog-model";
import { specimenUrl, type GalleryState, type PublicSpecimen } from "../lib/specimens";

function ReferenceCard({ item, source, number, name }: Readonly<{ item: PublicSpecimen; source?: Source; number: number; name: string }>) {
  const [failed, setFailed] = useState(false);
  const url = specimenUrl(item);
  return <figure className="reference-card">
    <a className="reference-image-link" href={url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${name} reference image ${number} at full size (new tab)`}>
      {failed ? <span className="reference-image-failure">Image unavailable. Open the original image to try again.</span> : <img src={url} alt={`${name} source reference ${number}; research specimen, review pending`} loading="lazy" decoding="async" onError={() => setFailed(true)} />}
      <span className="reference-open">View full size <span aria-hidden="true">↗</span></span>
    </a>
    <figcaption><strong>Reference {String(number).padStart(2, "0")}</strong><span className="reference-status">Review pending</span>
      <details className="reference-provenance"><summary>Image provenance</summary>
        {source ? <p><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title} ↗</a><br/><span>{source.hostname}</span></p> : <p>Source publication fingerprint retained. A matching citation is not available in this source index.</p>}
        <dl><dt>Collection</dt><dd>{item.state}</dd><dt>Reference ID</dt><dd>{item.id}</dd><dt>Source SHA-256</dt><dd>{item.source_sha256}</dd><dt>Image SHA-256</dt><dd>{item.asset_sha256}</dd></dl>
      </details>
    </figcaption>
  </figure>;
}
export default function SpecimenGallery({ state, name, sources, gallery }: Readonly<{ state: string; name: string; sources: Source[]; gallery: GalleryState }>) {
  const items = gallery.items.filter((item) => item.state === state);
  return <section className="reference-gallery" aria-label={`${name} reference images`} aria-busy={gallery.loading}>
    <div className="reference-gallery-heading"><h2>Reference images</h2>{!gallery.loading && !gallery.error && <span>{items.length} available</span>}</div>
    {gallery.loading ? <p role="status" className="reference-message">Loading reference images…</p> : gallery.error ? <div className="reference-message" role="alert"><p>Reference images could not be loaded. This does not establish a coverage gap.</p><button className="text-link" type="button" onClick={gallery.retry}>Try again ↻</button></div> : items.length === 0 ? <p className="reference-message">No reference images are published for this collection yet. See the source trail for available documents.</p> : <><p className="reference-caption">Open any image at full size. These source references may include annotations, partial images or publication pages; they are not accepted verification templates.</p><div className="reference-grid">{items.map((item, index) => <ReferenceCard key={`${item.state}/${item.id}`} item={item} number={index + 1} name={name} source={sources.find((source) => source.sha256 === item.source_sha256)} />)}</div></>}
  </section>;
}
