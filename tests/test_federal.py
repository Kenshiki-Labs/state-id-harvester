from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from state_id_harvester.cli import harvest_options, parser, selected_collections
from state_id_harvester.extract import extract
from state_id_harvester.library import coverage, federal_coverage
from state_id_harvester.models import Manifest, Options, Source
from state_id_harvester.paths import managed_path
from state_id_harvester.seeds import FEDERAL_CODE, STATE_DOMAINS, collection_pdf_seeds


def test_federal_is_separate_from_the_51_states_and_format_is_unclassified() -> None:
    args = parser().parse_args(["harvest", "--federal"])
    assert selected_collections(args) == [FEDERAL_CODE]
    assert harvest_options(args).detect_boundaries is False
    assert FEDERAL_CODE not in STATE_DOMAINS
    assert len(STATE_DOMAINS) == 51
    source = Source(
        discovery_jurisdiction=FEDERAL_CODE,
        url=collection_pdf_seeds(FEDERAL_CODE)[0],
        discovered_via="test",
    )
    assert source.credential_format == "unclassified"
    with pytest.raises(ValueError, match="cannot be normalized"):
        Source(
            discovery_jurisdiction=FEDERAL_CODE,
            url=source.url,
            discovered_via="test",
            credential_format="ID1",
        )
    with pytest.raises(SystemExit):
        parser().parse_args(["harvest", "--all", "--federal"])


def test_federal_extractor_blocks_id1_normalization_even_if_options_request_it(
    tmp_path: Path,
) -> None:
    from test_extraction import fixture_pdf

    original = fixture_pdf(tmp_path)
    download = original.model_copy(
        update={
            "source": Source(
                discovery_jurisdiction=FEDERAL_CODE,
                url=original.source.url,
                discovered_via="synthetic_test",
            )
        }
    )
    document = extract(
        download, str(tmp_path), Options(dpi=72, max_render_pages=2, detect_boundaries=True)
    )
    assert any(a.kind == "extracted_image" for a in document.assets)
    assert not any(a.kind == "card_candidate" for a in document.assets)
    topology = next(a for a in document.assets if a.path.endswith("topology_candidates.json"))
    assert json.loads((tmp_path / topology.path).read_text()) == []
    manifest = Manifest(
        generated_at="2026-10-25T00:00:00Z",
        run_id="federal-test",
        source_revision="test",
        requested_jurisdictions=[FEDERAL_CODE],
        options=Options(),
        documents=[document],
        reviews=[],
    )
    assert len(coverage(manifest, [])) == 51
    assert sum(r["source_documents"] for r in coverage(manifest, [])) == 0
    assert federal_coverage(manifest, [])["source_documents"] == 1


def test_public_federal_subsection_does_not_change_state_statistics() -> None:
    spec = importlib.util.spec_from_file_location(
        "federal_export_test", "scripts/build_public_catalog.py"
    )
    assert spec is not None and spec.loader is not None
    exporter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = exporter
    spec.loader.exec_module(exporter)
    private = {
        "generated_at": "2026-10-25T00:00:00Z",
        "run_id": "test",
        "documents": [
            {
                "title": "PIV normative specification",
                "page_count": 133,
                "relevance": "candidate",
                "assets": [],
                "download": {
                    "final_url": collection_pdf_seeds(FEDERAL_CODE)[0],
                    "sha256": "a" * 64,
                    "retrieved_at": "2026-10-25T00:00:00Z",
                    "publisher_host": "nvlpubs.nist.gov",
                    "publisher_jurisdiction": FEDERAL_CODE,
                    "source": {
                        "discovery_jurisdiction": FEDERAL_CODE,
                        "credential_format": "unclassified",
                    },
                },
            }
        ],
    }
    catalog = exporter.public_catalog({**private, "documents": []}, [], [], private)
    assert len(catalog["jurisdictions"]) == catalog["stats"]["jurisdictions"] == 51
    assert catalog["stats"]["sources"] == 0
    assert catalog["federal"]["counts"]["sources"] == 1
    assert catalog["federal"]["counts"]["accepted_cohorts"] == 0
    assert catalog["federal"]["credential_format"] == "unclassified"


def test_cli_path_boundary_rejects_outside_root_and_escaping_symlinks(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="managed temporary"):
        managed_path("/etc/passwd")
    link = tmp_path / "escape"
    link.symlink_to("/etc")
    with pytest.raises(ValueError, match="managed temporary"):
        managed_path(link / "passwd")
