import type { useCatalog } from "../lib/catalog";
type CatalogController = ReturnType<typeof useCatalog>;
export default function CatalogRows({
  catalog,
}: {
  readonly catalog: CatalogController;
}) {
  if (catalog.loading)
    return <output className="catalog-message">Loading source index…</output>;
  if (catalog.error)
    return (
      <p className="catalog-message" role="alert">
        The source index could not load.{" "}
        <a href="/data/catalog.json">Open the catalog directly.</a>
      </p>
    );
  return (
    <>
      <div className="state-list">
        {catalog.visible.map((row) => (
          <button
            className={`state-row ${catalog.selected === row.code ? "is-selected" : ""}`}
            key={row.code}
            aria-pressed={catalog.selected === row.code}
            onClick={() => catalog.setSelected(row.code)}
          >
            <span className="state-code">{row.code}</span>
            <span className="state-name">{row.name}</span>
            <span className="source-number">{row.sources.length || "—"}</span>
            <span className="state-arrow" aria-hidden="true">
              ↗
            </span>
          </button>
        ))}
      </div>
      {catalog.visible.length === 0 && (
        <p className="catalog-message">
          No jurisdictions match “{catalog.query}”.
        </p>
      )}
      <p className="list-footnote" aria-live="polite">
        {catalog.visible.length} of 51 jurisdictions · discovery jurisdiction
      </p>
    </>
  );
}
