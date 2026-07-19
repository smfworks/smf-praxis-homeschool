"""Evidence-backed homeschool portfolio and annual archive construction."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from math import isfinite

from .homeschool_jurisdictions import HomeschoolProfile
from .homeschool_validation import iso_date, valid_sha256


@dataclass(frozen=True)
class ParentArtifactAttestation:
    attestation_id: str
    parent_id: str
    learner_id: str
    artifact_id: str
    content_hash: str
    confirmed_on: str
    artifact_manifest_hash: str
    attestation_hash: str


def artifact_attestation_hash(attestation: ParentArtifactAttestation) -> str:
    payload = json.dumps({
        "attestation_id": attestation.attestation_id,
        "parent_id": attestation.parent_id,
        "learner_id": attestation.learner_id,
        "artifact_id": attestation.artifact_id,
        "content_hash": attestation.content_hash,
        "confirmed_on": attestation.confirmed_on,
        "artifact_manifest_hash": attestation.artifact_manifest_hash,
    }, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PortfolioArtifact:
    artifact_id: str
    learner_id: str
    created_date: str
    title: str
    subjects: tuple[str, ...]
    artifact_type: str
    content_hash: str
    source: str
    instructional_hours: float = 0.0
    metadata: tuple[tuple[str, str], ...] = ()
    parent_attested: bool = False
    parent_attestation: ParentArtifactAttestation | None = None


def portfolio_artifact_manifest_hash(artifact: PortfolioArtifact) -> str:
    payload = {
        "artifact_id": artifact.artifact_id,
        "learner_id": artifact.learner_id,
        "created_date": artifact.created_date,
        "title": artifact.title,
        "subjects": list(artifact.subjects),
        "artifact_type": artifact.artifact_type,
        "content_hash": artifact.content_hash,
        "source": artifact.source,
        "instructional_hours": str(artifact.instructional_hours),
        "metadata": [list(item) for item in artifact.metadata],
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class PortfolioReport:
    learner_id: str
    artifact_count: int
    covered_subjects: tuple[str, ...]
    missing_subjects: tuple[str, ...]
    total_hours: float
    complete: bool
    findings: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioExport:
    learner_id: str
    state: str
    generated_on: str
    source_verified_on: str
    retention_years: int
    artifact_manifest: tuple[dict[str, object], ...]
    parent_attested: bool
    evaluator_ready: bool


class PortfolioLedger:
    def __init__(self, *, today: date | None = None) -> None:
        self._today = today or date.today()
        self._artifacts: dict[str, PortfolioArtifact] = {}
        self._content_owners: dict[tuple[str, str], str] = {}

    def append(self, artifact: PortfolioArtifact, *, content: bytes) -> PortfolioArtifact:
        if artifact.artifact_id in self._artifacts:
            raise ValueError("portfolio artifact IDs are immutable and unique")
        if (not artifact.artifact_id or not artifact.learner_id or not artifact.title.strip()
                or not artifact.artifact_type.strip() or not artifact.source.strip()):
            raise ValueError("artifact identity, learner, title, type, and source are required")
        created = iso_date(artifact.created_date, "created_date")
        if created > self._today:
            raise ValueError("portfolio evidence cannot be dated in the future")
        if not artifact.subjects or any(not s.strip() for s in artifact.subjects):
            raise ValueError("at least one nonempty subject is required")
        if (any(not isinstance(item, tuple) or len(item) != 2
                or any(not isinstance(value, str) for value in item)
                or not item[0].strip() for item in artifact.metadata)
                or len({item[0] for item in artifact.metadata}) != len(artifact.metadata)):
            raise ValueError("artifact metadata must use unique nonempty string keys")
        if not content:
            raise ValueError("portfolio evidence content must be nonempty")
        actual_hash = "sha256:" + hashlib.sha256(content).hexdigest()
        if not valid_sha256(artifact.content_hash) or artifact.content_hash != actual_hash:
            raise ValueError("artifact hash must be canonical sha256:<64 lowercase hex>")
        if isinstance(artifact.instructional_hours, bool) or not isinstance(
                artifact.instructional_hours, (int, float)):
            raise ValueError("instructional_hours must be numeric")
        if (not isfinite(artifact.instructional_hours)
                or not 0 <= artifact.instructional_hours <= 24):
            raise ValueError("instructional_hours must be finite and in [0, 24] per artifact")
        if artifact.parent_attested is not True:
            raise ValueError("parent attestation required before evidence enters the portfolio")
        attestation = artifact.parent_attestation
        if (attestation is None or not attestation.attestation_id.strip()
                or not attestation.parent_id.strip()
                or attestation.learner_id != artifact.learner_id
                or attestation.artifact_id != artifact.artifact_id
                or attestation.content_hash != artifact.content_hash
                or attestation.artifact_manifest_hash != portfolio_artifact_manifest_hash(artifact)
                or not created <= iso_date(attestation.confirmed_on, "confirmed_on") <= self._today
                or attestation.attestation_hash != artifact_attestation_hash(attestation)):
            raise ValueError("artifact requires a parent attestation bound to its learner and content")
        content_key = (artifact.learner_id, artifact.content_hash)
        if content_key in self._content_owners:
            raise ValueError("portfolio content hash is already recorded for this learner")
        self._artifacts[artifact.artifact_id] = artifact
        self._content_owners[content_key] = artifact.artifact_id
        return artifact

    def get(self, artifact_id: str) -> PortfolioArtifact:
        try:
            return self._artifacts[artifact_id]
        except KeyError as exc:
            raise KeyError("unknown portfolio artifact") from exc

    def for_learner(self, learner_id: str) -> tuple[PortfolioArtifact, ...]:
        return tuple(a for a in self._artifacts.values() if a.learner_id == learner_id)

    @staticmethod
    def _report(learner_id: str, profile: HomeschoolProfile,
                artifacts: tuple[PortfolioArtifact, ...]) -> PortfolioReport:
        covered = tuple(sorted({s.strip().lower() for a in artifacts for s in a.subjects}))
        missing = tuple(s for s in profile.required_subjects if s not in covered)
        hours = round(sum(float(a.instructional_hours) for a in artifacts), 4)
        findings: list[str] = []
        if profile.portfolio_required and not artifacts:
            findings.append("The selected route requires a portfolio but no evidence is present.")
        if missing:
            findings.append("Required subject evidence is missing: " + ", ".join(missing))
        if profile.portfolio_required and not any(a.artifact_type in {"work_sample", "test", "project", "writing"}
                                                  for a in artifacts):
            findings.append("No representative learner work sample is present.")
        return PortfolioReport(learner_id, len(artifacts), covered, missing, hours,
                               not findings, tuple(findings))

    def _for_period(self, learner_id: str, *, period_start: str,
                    period_end: str) -> tuple[PortfolioArtifact, ...]:
        start = iso_date(period_start, "period_start")
        end = iso_date(period_end, "period_end")
        if end < start:
            raise ValueError("period_end must not precede period_start")
        return tuple(
            artifact for artifact in self.for_learner(learner_id)
            if start <= iso_date(artifact.created_date, "created_date") <= end
        )

    def report(self, learner_id: str, profile: HomeschoolProfile, *,
               period_start: str, period_end: str) -> PortfolioReport:
        return self._report(
            learner_id, profile,
            self._for_period(learner_id, period_start=period_start, period_end=period_end),
        )

    def export(self, learner_id: str, profile: HomeschoolProfile, *,
               approved_by_parent: bool, period_start: str, period_end: str,
               selected_ids: tuple[str, ...] = ()) -> PortfolioExport:
        if approved_by_parent is not True:
            raise PermissionError("portfolio export requires parent approval")
        artifacts = self._for_period(
            learner_id, period_start=period_start, period_end=period_end,
        )
        if selected_ids:
            if len(set(selected_ids)) != len(selected_ids):
                raise ValueError("selected portfolio artifact IDs must be unique")
            selected = set(selected_ids)
            unknown = selected - {a.artifact_id for a in artifacts}
            if unknown:
                raise ValueError("selected portfolio artifact does not belong to learner")
            artifacts = tuple(a for a in artifacts if a.artifact_id in selected)
        manifest_rows: list[dict[str, object]] = []
        for artifact in artifacts:
            manifest_rows.append({
                "artifact_id": artifact.artifact_id,
                "created_date": artifact.created_date,
                "title": artifact.title,
                "subjects": artifact.subjects,
                "artifact_type": artifact.artifact_type,
                "content_hash": artifact.content_hash,
                "source": artifact.source,
                # Deliberately exclude arbitrary file metadata/EXIF/GPS.
            })
        manifest = tuple(manifest_rows)
        report = self._report(learner_id, profile, artifacts)
        return PortfolioExport(
            learner_id, profile.state, date.today().isoformat(), profile.verified_on,
            profile.portfolio_retention_years, manifest, True,
            bool(manifest) and (report.complete or not profile.portfolio_required),
        )
