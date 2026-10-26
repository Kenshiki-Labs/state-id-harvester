import { useSpecimens } from "../lib/specimens";
import { useCatalog } from "../lib/catalog";
import { catalogFilter } from "../lib/catalog-model";
import CatalogRows from "./CatalogRows";
import FederalCatalog from "./FederalCatalog";
import CatalogDetail from "./CatalogDetail";
export default function Catalog() {
  const catalog = useCatalog();
  const gallery = useSpecimens();
  const detail = catalog.detail;
  return (
    <div className="catalog-browser">
      <div className="catalog-toolbar">
        <label className="search-field">
          <svg
            data-cadastre-diagram="independent"
            aria-hidden="true"
            viewBox="0 0 24 24"
          >
            <circle cx="10.5" cy="10.5" r="6.5" />
            <path d="m16 16 5 5" />
          </svg>
          <span className="sr-only">Search jurisdictions</span>
          <input
            type="search"
            placeholder="Find a state or jurisdiction"
            value={catalog.query}
            onChange={(event) => catalog.setQuery(event.target.value)}
          />
          <kbd aria-hidden="true">51</kbd>
        </label>
        <label className="filter-field">
          <span className="sr-only">Filter jurisdictions</span>
          <select
            value={catalog.filter}
            onChange={(event) =>
              catalog.setFilter(catalogFilter(event.target.value))
            }
          >
            <option value="all">All jurisdictions</option>
            <option value="sources">Sources indexed</option>
            <option value="awaiting">Awaiting sources</option>
          </select>
        </label>
      </div>
      <div className="catalog-workspace">
        <fieldset className="jurisdiction-list">
          <legend className="sr-only">Jurisdiction catalog</legend>
          <div className="list-heading">
            <span>Jurisdiction</span>
            <span>Public sources</span>
          </div>
          <CatalogRows catalog={catalog} />
        </fieldset>
        <CatalogDetail
          detail={detail}
          gallery={gallery}
          unavailable={catalog.loading || catalog.error}
        />
      </div>
      <FederalCatalog collection={catalog.error ? null : catalog.federal} gallery={gallery} />
    </div>
  );
}
