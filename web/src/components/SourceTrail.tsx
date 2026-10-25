import type { Source } from "../lib/catalog-model";
const relevanceLabels = {
  candidate: "Relevance candidate",
  quarantined: "Quarantined",
  unreviewed: "Unreviewed",
};
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
          {source.sha256 && (
            <details>
              <summary>SHA-256 fingerprint</summary>
              <code>{source.sha256}</code>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}
