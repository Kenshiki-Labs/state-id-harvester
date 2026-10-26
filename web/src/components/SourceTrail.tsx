import type { Source } from "../lib/catalog-model";
const relevanceLabels = {
  candidate: "Relevance candidate",
  quarantined: "Quarantined",
  unreviewed: "Unreviewed",
};
function SourceList({ sources }: Readonly<{ sources: readonly Source[] }>) {
  return (
    <ul className="source-links">
      {sources.map((source, index) => (
        <li key={`${source.url}-${source.sha256 ?? source.title}`}>
          <a href={source.url} target="_blank" rel="noopener noreferrer">
            <span className="source-index">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span>
              <strong>{source.title}</strong>
              <small>
                {source.hostname} · {relevanceLabels[source.relevance]}
              </small>
            </span>
            <span aria-hidden="true">↗</span>
          </a>
          {(source.sha256 || source.retrievedAt || source.pageCount) && (
            <details>
              <summary>Source provenance</summary>
              <dl className="source-provenance">
                {source.pageCount !== undefined && source.pageCount > 0 && (
                  <>
                    <dt>Source pages</dt>
                    <dd>{source.pageCount}</dd>
                  </>
                )}
                {source.retrievedAt && (
                  <>
                    <dt>Retrieved</dt>
                    <dd>
                      <time dateTime={source.retrievedAt}>
                        {new Date(source.retrievedAt).toLocaleDateString(
                          "en-GB",
                          {
                            timeZone: "UTC",
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          },
                        )}
                      </time>
                    </dd>
                  </>
                )}
                {source.publisherJurisdiction && (
                  <>
                    <dt>Publisher jurisdiction</dt>
                    <dd>{source.publisherJurisdiction}</dd>
                  </>
                )}
                {source.sha256 && (
                  <>
                    <dt>SHA-256</dt>
                    <dd>
                      <code>{source.sha256}</code>
                    </dd>
                  </>
                )}
              </dl>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function SourceTrail({
  sources,
}: Readonly<{ sources: readonly Source[] }>) {
  if (!sources.length)
    return (
      <div className="empty-source">
        <span aria-hidden="true">＋</span>
        <p>
          A source record starts with an attributable public document, never a
          generated card.
        </p>
      </div>
    );
  const relevant = sources.filter(
    (source) => source.relevance !== "quarantined",
  );
  const quarantined = sources.filter(
    (source) => source.relevance === "quarantined",
  );
  return (
    <>
      {relevant.length > 0 && <SourceList sources={relevant} />}
      {quarantined.length > 0 && (
        <details className="quarantined-sources">
          <summary>Quarantined documents · {quarantined.length}</summary>
          <p>
            These files remain in the discovery ledger. Automatic triage did not
            establish their relevance to credential reference work.
          </p>
          <SourceList sources={quarantined} />
        </details>
      )}
    </>
  );
}
