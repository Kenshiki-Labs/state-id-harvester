import SpecimenGallery from "./SpecimenGallery";
import type { GalleryState } from "../lib/specimens";
import type { FederalCollection } from "../lib/catalog-model";
import SourceTrail from "./SourceTrail";
export default function FederalCatalog({
  collection,
  gallery,
}: {
  readonly collection: FederalCollection | null;
  readonly gallery?: GalleryState;
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
      <h2 className="collection-heading">Collection overview</h2>
      <p className="detail-description">
        Federal source publications form a separate collection from the 51 state
        jurisdictions. These publications can cover several credential formats
        and normative standards, including PIV references. They remain
        unclassified and are not normalized as ID-1 card templates.
      </p>
      <p className="detail-description">
        The collection plan covers PIV, CAC, USID, Green Cards, EADs, passport
        books and cards, trusted-traveler cards, and TWIC. Indexed publications
        do not yet establish complete coverage of these families. See the source
        trail for the references actually collected.
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
      {gallery && <SpecimenGallery state="US_FED" name={collection.name} sources={collection.sources} gallery={gallery} />}
      <div className="detail-divider" />
      <h2 className="collection-heading">
        Federal source trail <span>↗</span>
      </h2>
      <SourceTrail sources={collection.sources} />
      <div className="review-note">
        <span aria-hidden="true">◇</span>
        <p>
          <strong>Different document families. Separate review.</strong> A
          source publication is not a credential template. Source page counts,
          rendered pages, and extracted images represent different stages of
          collection.
        </p>
      </div>
    </section>
  );
}
