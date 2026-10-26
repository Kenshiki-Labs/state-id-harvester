import { useState } from "react";
import { filterCatalog, type Jurisdiction } from "../lib/catalog-model";
export default function Directory({ rows }: Readonly<{ rows: Jurisdiction[] }>) {
  const [query, setQuery] = useState("");
  const visible = filterCatalog(rows, query, "all");
  return <div className="directory">
    <label className="directory-search"><span>Find a jurisdiction</span><input type="search" placeholder="Search by state name or abbreviation" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    <output className="directory-count">{visible.length} of 51 jurisdictions</output>
    <div className="directory-grid">{visible.map((row) => <a className="directory-card" key={row.code} href={`/catalog/${row.code.toLowerCase()}`}><span className="state-code">{row.code}</span><h2>{row.name}</h2><span>{row.sources.length} source publications</span><span className="directory-arrow" aria-hidden="true">↗</span></a>)}</div>
    {visible.length === 0 && <p className="reference-message">No jurisdictions match “{query}”. Try a state name or abbreviation.</p>}
  </div>;
}
