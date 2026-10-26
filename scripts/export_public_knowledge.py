"""Export selected grounded PDF records to the public knowledge viewer."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from state_id_harvester.knowledge_evidence import load_grounded_pdf_knowledge
from state_id_harvester.knowledge_public import PublicKnowledge, PublicReference, project_document


def managed_record(path: Path, root: Path) -> Path:
    """Admit only named extraction records in this workspace's managed private tree."""
    workspace = root.resolve(strict=True)
    allowed = workspace / "output" / "knowledge"
    candidate = path if path.is_absolute() else workspace / path
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(allowed) or not re.fullmatch(
        r"[a-f0-9]{64}\.json", candidate.name
    ):
        raise ValueError("Record must be a digest-named file inside output/knowledge")
    if not resolved.is_file() or any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise ValueError("Managed records cannot be symlinks or non-files")
    return resolved


def managed_workspace_path(root: Path, relative: str) -> Path:
    """Keep fixed input and publication paths inside the repository, without symlinks."""
    candidate = root / relative
    if any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise ValueError("Managed publication paths cannot contain symlinks")
    if not candidate.resolve().is_relative_to(root):
        raise ValueError("Managed path escapes workspace")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", nargs="+", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    catalog_path = managed_workspace_path(root, "web/public/data/catalog.json")
    output = managed_workspace_path(root, "web/public/data/knowledge.json")
    catalog = json.loads(catalog_path.read_text())
    index_path = managed_workspace_path(root, "output/knowledge/public-specimens.json")
    pages_path = managed_workspace_path(root, "output/knowledge/reference-pages.json")
    pages = json.loads(pages_path.read_text())
    normalized_path = managed_workspace_path(root, "output/knowledge/public-normalizations.json")
    normalized = {
        (item["state"], item["id"]) for item in json.loads(normalized_path.read_text())["specimens"]
    }
    references: dict[str, list[PublicReference]] = defaultdict(list)
    for item in json.loads(index_path.read_text())["specimens"]:
        reference = PublicReference.model_validate_json(
            json.dumps(
                {
                    **{key: item[key] for key in ("id", "state", "source_sha256", "asset_sha256")},
                    "source_page": pages.get(f"{item['state']}/{item['id']}"),
                }
            )
        )
        references[reference.source_sha256].append(reference)
    collections: dict[str, set[str]] = {}
    rows = catalog["jurisdictions"] + ([catalog["federal"]] if catalog.get("federal") else [])
    for row in rows:
        for source in row["sources"]:
            collections.setdefault(source["sha256"], set()).add(row["name"])
    documents = []
    for argument in sorted(args.records):
        path = managed_record(argument, root)
        packet = managed_workspace_path(
            root, f"output/domain-classification/native-text/{path.stem}.json"
        )
        record = load_grounded_pdf_knowledge(path.read_bytes(), packet.read_bytes())
        collection = ", ".join(sorted(collections.get(record.source.source_sha256, {"Unassigned"})))
        source_references = references.get(record.source.source_sha256, ())
        ranked = sorted(
            source_references,
            key=lambda ref: (
                (ref.state, ref.id) not in normalized,
                -sum(
                    1
                    for evidence in record.evidence
                    if getattr(evidence, "page_number", None) == ref.source_page
                ),
                ref.id,
            ),
        )
        documents.append(project_document(record, collection, tuple(ranked)))
    payload = PublicKnowledge(documents=tuple(documents))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload.model_dump_json(indent=2) + "\n")
    count = sum(d.statement_count for d in documents)
    print(f"Exported {len(documents)} documents / {count} statements")


if __name__ == "__main__":
    main()
