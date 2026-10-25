import { useEffect, useMemo, useState } from "react";
import {
  blankCatalog,
  emptyJurisdiction,
  normalizeFederal,
  type FederalCollection,
  filterCatalog,
  normalizeCatalog,
  type CatalogFilter,
  type Jurisdiction,
} from "./catalog-model";
export type { CatalogFilter } from "./catalog-model";
export function useCatalog() {
  const [rows, setRows] = useState<Jurisdiction[]>(blankCatalog);
  const [federal, setFederal] = useState<FederalCollection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<CatalogFilter>("all");
  const [selected, setSelected] = useState("TX");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/data/catalog.json", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Catalog unavailable");
        return response.json();
      })
      .then((data) => {
        const nextRows = normalizeCatalog(data);
        const nextFederal = normalizeFederal(data);
        setRows(nextRows);
        setFederal(nextFederal);
        setLoading(false);
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setError(true);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, []);
  const visible = useMemo(
    () => filterCatalog(rows, query, filter),
    [rows, query, filter],
  );
  return {
    rows,
    federal,
    visible,
    loading,
    error,
    query,
    setQuery,
    filter,
    setFilter,
    selected,
    setSelected,
    detail:
      rows.find((row) => row.code === selected) ??
      emptyJurisdiction("TX", "Texas"),
  };
}
