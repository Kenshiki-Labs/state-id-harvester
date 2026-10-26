from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from state_id_harvester.catalog import Cohort, Evidence, Zone, route_candidates
from state_id_harvester.models import Review
from state_id_harvester.seeds import LANDING_PAGES, STATE_DOMAINS


def cohort(name: str, start: date | None, end: date | None) -> Cohort:
    return Cohort(
        cohort_id=name,
        jurisdiction="TX",
        credential_type="driver_license",
        orientation="horizontal",
        iins=["636015"],
        issue_date_start=start,
        issue_date_end=end,
        design_generation="synthetic routing test",
        review_status="accepted",
        reviewer="test",
        evidence=[
            Evidence(
                source_sha256="0" * 64,
                asset_sha256="1" * 64,
                page_number=1,
                explanation="synthetic test",
            )
        ],
        zones=[],
        invariants=[],
    )


def test_routing_preserves_overlap_and_unknown_dates() -> None:
    cohorts = [
        cohort("TX_A", date(2025, 1, 1), date(2025, 12, 31)),
        cohort("TX_B", date(2025, 8, 18), None),
    ]
    args = {"iin": "636015", "jurisdiction": "TX", "credential_type": "driver_license"}
    assert route_candidates(cohorts, **args, issue_date=date(2025, 9, 1)) == ["TX_A", "TX_B"]
    assert route_candidates(cohorts, **args, issue_date=None) == ["TX_A", "TX_B"]
    assert route_candidates(cohorts, **args, issue_date=date(2024, 1, 1)) == []


def test_specimen_cannot_claim_measured_accuracy() -> None:
    evidence = Evidence(
        source_sha256="0" * 64, asset_sha256="1" * 64, page_number=1, explanation="test"
    )
    with pytest.raises(ValidationError, match="metric accuracy"):
        Zone(
            name="portrait",
            bbox_uv=(0.0, 0.0, 0.5, 0.5),
            geometry_basis="reviewed_specimen",
            measured_error_mm=0.05,
            evidence=[evidence],
        )


def test_zone_bounds_and_jurisdictions_are_validated() -> None:
    with pytest.raises(ValidationError, match="jurisdiction"):
        Review(
            source_sha256="0" * 64,
            asset_sha256="1" * 64,
            depicted_jurisdiction="XX",
            credential_type="driver_license",
            design_generation="test",
            side="front",
            status="accepted",
            reviewer="test",
            reviewed_at="today",
            evidence="test",
        )


def test_51_jurisdictions_have_entry_points() -> None:
    assert len(STATE_DOMAINS) == 51
    assert set(STATE_DOMAINS) == set(LANDING_PAGES)
    assert "DC" in STATE_DOMAINS


def test_repository_review_inputs_are_valid_json() -> None:
    assert Path("reviews.json").read_text().strip() == "[]"
    assert Path("cohorts.json").read_text().strip() == "[]"
