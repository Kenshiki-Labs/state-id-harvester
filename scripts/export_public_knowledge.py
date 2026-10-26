"""Export selected grounded PDF records to the public knowledge viewer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from state_id_harvester.knowledge_evidence import load_grounded_pdf_knowledge
from state_id_harvester.knowledge_public import PublicKnowledge, project_document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", nargs="+", type=Path)
    parser.add_argument("--native-packets", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("web/public/data/catalog.json"))
    parser.add_argument("--output", type=Path, default=Path("web/public/data/knowledge.json"))
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    collections: dict[str, set[str]] = {}
    rows = catalog["jurisdictions"] + ([catalog["federal"]] if catalog.get("federal") else [])
    for row in rows:
        for source in row["sources"]:
            collections.setdefault(source["sha256"], set()).add(row["name"])
    documents = []
    for path in sorted(args.records):
        packet = args.native_packets / f"{path.stem}.json"
        record = load_grounded_pdf_knowledge(path.read_bytes(), packet.read_bytes())
        collection = ", ".join(sorted(collections.get(record.source.source_sha256, {"Unassigned"})))
        documents.append(project_document(record, collection))
    payload = PublicKnowledge(documents=tuple(documents))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload.model_dump_json(indent=2) + "\n")
    count = sum(d.statement_count for d in documents)
    print(f"Exported {len(documents)} documents / {count} statements")


if __name__ == "__main__":
    main()
