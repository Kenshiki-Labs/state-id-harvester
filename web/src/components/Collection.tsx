import { useSpecimens } from "../lib/specimens";
import type { Jurisdiction, FederalCollection } from "../lib/catalog-model";
import CatalogDetail from "./CatalogDetail";
import FederalCatalog from "./FederalCatalog";
export default function Collection({ detail, federal }: Readonly<{ detail: Jurisdiction; federal?: FederalCollection }>) {
  const gallery = useSpecimens();
  if (federal) return <FederalCatalog collection={federal} gallery={gallery} />;
  return <CatalogDetail detail={detail} gallery={gallery} unavailable={false} />;
}
