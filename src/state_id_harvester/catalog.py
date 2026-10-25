"""Reviewed topology/cohort interchange. No barcode value is treated as authentic."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter, field_validator, model_validator

from .models import Manifest, Record
from .seeds import STATE_DOMAINS
from .storage import atomic_json


class Evidence(Record):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    asset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_number: int = Field(ge=1)
    explanation: str = Field(min_length=1)


class Zone(Record):
    name: str = Field(min_length=1)
    bbox_uv: tuple[float, float, float, float]
    geometry_basis: Literal["reviewed_specimen", "physical_calibration"]
    measured_error_mm: float | None = Field(default=None, gt=0)
    evidence: list[Evidence] = Field(min_length=1)

    @field_validator("bbox_uv")
    @classmethod
    def normalized(
        cls, value: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = value
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("Zone must be a nonempty unit-square rectangle")
        return value

    @model_validator(mode="after")
    def measurement_requires_calibration(self) -> Zone:
        if self.measured_error_mm is not None and self.geometry_basis != "physical_calibration":
            raise ValueError("Specimen normalization cannot establish measured metric accuracy")
        return self


class Invariant(Record):
    name: str
    description: str
    observation_modality: Literal[
        "visible", "tilt", "transmitted_light", "uv", "tactile", "barcode"
    ]
    evidence: list[Evidence] = Field(min_length=1)
    # Collection publishes sourced observations, not unvalidated rejection thresholds.
    decision_use: Literal["observation_only"] = "observation_only"


class Cohort(Record):
    cohort_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    jurisdiction: str
    credential_type: Literal["driver_license", "identification_card", "learner_permit"]
    orientation: Literal["horizontal", "vertical"]
    iins: list[str]
    issue_date_start: date | None = None
    issue_date_end: date | None = None
    design_generation: str = Field(min_length=1)
    review_status: Literal["accepted"]
    reviewer: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    zones: list[Zone]
    invariants: list[Invariant]

    @field_validator("jurisdiction")
    @classmethod
    def jurisdiction_exists(cls, value: str) -> str:
        if value not in STATE_DOMAINS:
            raise ValueError("Unknown jurisdiction")
        return value

    @field_validator("iins")
    @classmethod
    def valid_iins(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"\d{6}", item) for item in value):
            raise ValueError("IIN must contain six digits")
        return value

    @model_validator(mode="after")
    def ordered_dates(self) -> Cohort:
        if (
            self.issue_date_start
            and self.issue_date_end
            and self.issue_date_start > self.issue_date_end
        ):
            raise ValueError("Cohort issue-date window is inverted")
        return self


def export_catalog(manifest: Manifest, cohorts_path: Path, destination: Path) -> None:
    cohorts = TypeAdapter(list[Cohort]).validate_json(cohorts_path.read_text())
    documents = {d.download.sha256: d for d in manifest.documents}
    accepted = {
        (r.source_sha256, r.asset_sha256): r for r in manifest.reviews if r.status == "accepted"
    }
    seen: set[str] = set()
    for cohort in cohorts:
        if cohort.cohort_id in seen:
            raise ValueError("Duplicate cohort identifier")
        seen.add(cohort.cohort_id)
        evidences = cohort.evidence + [e for z in cohort.zones for e in z.evidence]
        evidences.extend(e for invariant in cohort.invariants for e in invariant.evidence)
        for evidence in evidences:
            document = documents.get(evidence.source_sha256)
            if document is None or evidence.page_number > document.page_count:
                raise ValueError("Cohort evidence does not resolve to a retained source page")
            review = accepted.get((evidence.source_sha256, evidence.asset_sha256))
            if review is None:
                raise ValueError("Cohort evidence requires an accepted, hash-bound visual review")
            if (
                review.depicted_jurisdiction != cohort.jurisdiction
                or review.credential_type != cohort.credential_type
                or review.design_generation != cohort.design_generation
            ):
                raise ValueError("Cohort identity conflicts with its accepted visual review")
            if not any(
                a.sha256 == evidence.asset_sha256 and a.page_number == evidence.page_number
                for a in document.assets
            ):
                raise ValueError("Cohort evidence page does not match the accepted visual asset")
    atomic_json(
        destination,
        {
            "schema_version": 1,
            "library_run_id": manifest.run_id,
            "coordinate_convention": (
                "ID-1 unit square; nominal 85.60 x 53.98 mm; rotate for portrait"
            ),
            "routing": "candidate_set; overlapping or unknown date windows remain ambiguous",
            "barcode_trust": "untrusted_claims",
            "jurisdictions": {
                state: {"accepted_cohorts": sum(c.jurisdiction == state for c in cohorts)}
                for state in sorted(STATE_DOMAINS)
            },
            "cohorts": [c.model_dump(mode="json") for c in cohorts],
        },
    )


def route_candidates(
    cohorts: list[Cohort],
    *,
    iin: str | None,
    jurisdiction: str | None,
    credential_type: str | None,
    issue_date: date | None,
) -> list[str]:
    """Inputs must be independently parsed. DAJ is an address, never the issuer argument."""
    return [
        c.cohort_id
        for c in cohorts
        if (iin is None or not c.iins or iin in c.iins)
        and (jurisdiction is None or c.jurisdiction == jurisdiction)
        and (credential_type is None or c.credential_type == credential_type)
        and (issue_date is None or c.issue_date_start is None or issue_date >= c.issue_date_start)
        and (issue_date is None or c.issue_date_end is None or issue_date <= c.issue_date_end)
    ]
