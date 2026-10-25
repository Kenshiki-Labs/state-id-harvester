import type { FederalCollection } from "../lib/catalog-model";
import SourceTrail from "./SourceTrail";
export default function FederalCatalog({
  collection,
}: {
  readonly collection: FederalCollection | null;
}) {
  if (!collection) return null;
  return (
    <section
      className="state-detail"
      aria-label="Separate federal source collection"
    >
      <div className="detail-topline">
        <span className="eyebrow">SEPARATE COLLECTION / {collection.code}</span>
        <span className="small-status">
          <i />
          {collection.sources.length ? "Sources indexed" : "Discovery pending"}
        </span>
      </div>
      <h3>{collection.name}</h3>
      <p className="detail-description">
        Federal source publications form a separate collection from the 51 state
        jurisdictions. These publications can cover several credential formats
        and normative standards, including PIV references. They remain
        unclassified and are not normalized as ID-1 card templates.
      </p>
      <div className="detail-numbers">
        <div>
          <strong>{collection.sources.length}</strong>
          <span>Source PDFs</span>
        </div>
        <div>
          <strong>{collection.renderedPages}</strong>
          <span>Rendered pages</span>
        </div>
        <div>
          <strong>{collection.acceptedCohorts}</strong>
          <span>Accepted cohorts</span>
        </div>
      </div>
      <div className="detail-divider" />
      <h4>
        Federal source trail <span>↗</span>
      </h4>
      <SourceTrail sources={collection.sources} />
      <div className="review-note">
        <span aria-hidden="true">◇</span>
        <p>
          <strong>Different document families. Separate review.</strong>A source
          publication is not a credential template. Source page counts, rendered
          pages, and extracted images represent different stages of collection.
        </p>
      </div>
    </section>
  );
}
