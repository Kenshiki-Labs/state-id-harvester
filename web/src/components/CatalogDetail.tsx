import SpecimenGallery from "./SpecimenGallery";
import type { GalleryState } from "../lib/specimens";
import type { Jurisdiction } from "../lib/catalog-model";
import SourceTrail from "./SourceTrail";
export default function CatalogDetail({
  detail,
  unavailable,
  gallery,
}: Readonly<{
  detail: Jurisdiction;
  unavailable: boolean;
  gallery?: GalleryState;
}>) {
  if (unavailable)
    return (
      <section
        className="state-detail"
        aria-label="Source details"
        aria-live="polite"
      >
        <p className="eyebrow">SOURCE RECORD</p>
        <h3>Evidence before inference.</h3>
        <p className="detail-description">
          Source records and counts will appear when the public index is
          available. An unavailable index does not establish a coverage gap.
        </p>
      </section>
    );
  if (!detail.code)
    return (
      <section
        className="state-detail"
        aria-label="Source details"
        aria-live="polite"
      >
        <p className="eyebrow">SOURCE RECORD</p>
        <h3>No matching jurisdiction.</h3>
        <p className="detail-description">
          Clear your search or change the filter to choose a jurisdiction.
        </p>
      </section>
    );
  return (
    <section
      className="state-detail"
      aria-label={`${detail.name} source details`}
      aria-live="polite"
    >
      <div className="detail-topline">
        <span className="eyebrow">SOURCE RECORD / {detail.code}</span>
        <span className="small-status">
          <i />
          {detail.sources.length ? "Sources indexed" : "Discovery pending"}
        </span>
      </div>
      <h3>{detail.name}</h3>
      <p className="detail-description">
        {detail.sources.length
          ? "Public documents discovered for this jurisdiction. Publishing jurisdiction, relevance, depicted credentials, and design generations require separate review."
          : "This jurisdiction is in the collection plan. No source documents are currently indexed here."}
      </p>
      <div className="detail-numbers">
        <div>
          <strong>{detail.sources.length}</strong>
          <span>Source PDFs</span>
        </div>
        <div>
          <strong>{detail.relevantPdfs}</strong>
          <span>Relevance candidates</span>
        </div>
        <div>
          <strong>{detail.acceptedCohorts}</strong>
          <span>Accepted cohorts</span>
        </div>
      </div>
      {gallery && <SpecimenGallery state={detail.code} name={detail.name} sources={detail.sources} gallery={gallery} />}
      <div className="detail-divider" />
      <h4>
        Source trail <span>↗</span>
      </h4>
      <SourceTrail sources={detail.sources} />
      <div className="review-note">
        <span aria-hidden="true">◇</span>
        <p>
          <strong>Research material. Review pending.</strong> An extracted image
          is not an accepted template, a physical measurement, or an
          authenticity verdict.
        </p>
      </div>
    </section>
  );
}
