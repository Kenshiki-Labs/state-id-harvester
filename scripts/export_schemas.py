from __future__ import annotations

import argparse
import json
from pathlib import Path

from check_publication import Catalog, GeometryBundle
from pydantic import TypeAdapter

from state_id_harvester.catalog import Cohort
from state_id_harvester.knowledge import DocumentKnowledge
from state_id_harvester.knowledge_evidence import NativePdfPacket
from state_id_harvester.knowledge_public import PublicKnowledge
from state_id_harvester.knowledge_store import KnowledgeIndex, PreparedManifest
from state_id_harvester.models import BoundaryCandidate, Manifest, Review


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schemas = {
        "manifest": Manifest.model_json_schema(),
        "boundary-candidates": TypeAdapter(list[BoundaryCandidate]).json_schema(),
        "reviews": TypeAdapter(list[Review]).json_schema(),
        "cohorts": TypeAdapter(list[Cohort]).json_schema(),
        "public-catalog": Catalog.model_json_schema(),
        "public-cohorts": GeometryBundle.model_json_schema(),
        "document-knowledge": DocumentKnowledge.model_json_schema(),
        "public-knowledge": PublicKnowledge.model_json_schema(),
        "native-pdf-packet": NativePdfPacket.model_json_schema(),
        "knowledge-storage": PreparedManifest.model_json_schema(),
        "knowledge-index": KnowledgeIndex.model_json_schema(),
    }
    Path("schemas").mkdir(exist_ok=True)
    for name, schema in schemas.items():
        path = Path("schemas") / f"{name}.schema.json"
        data = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        if args.check:
            if not path.exists() or path.read_text() != data:
                raise SystemExit(f"Stale schema: {path}")
        else:
            path.write_text(data)


if __name__ == "__main__":
    main()
