"""Parent-authorized collaboration for tutors, co-ops, umbrellas, evaluators."""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import isfinite
from typing import Callable, Literal

CollaboratorRole = Literal["co_parent", "tutor", "co_op_instructor", "evaluator", "umbrella_admin"]

ROLE_SCOPES: dict[CollaboratorRole, frozenset[str]] = {
    "co_parent": frozenset({"learning_plan", "portfolio", "progress", "compliance", "transcript"}),
    "tutor": frozenset({"assigned_course", "assignment", "feedback", "selected_work_sample"}),
    "co_op_instructor": frozenset({"assigned_course", "roster", "assignment", "feedback", "selected_work_sample"}),
    "evaluator": frozenset({"selected_work_sample", "attendance_summary", "progress_summary", "assessment_context"}),
    "umbrella_admin": frozenset({"required_filing_fields", "attendance_summary", "progress_summary", "selected_work_sample"}),
}
FORBIDDEN_SCOPES = frozenset({"custody", "health_vault", "financial", "sibling_records", "child_ai_full_history"})
MAX_GRANT_TTL_SECONDS: dict[CollaboratorRole, int] = {
    "co_parent": 90 * 24 * 60 * 60,
    "tutor": 30 * 24 * 60 * 60,
    "co_op_instructor": 30 * 24 * 60 * 60,
    "evaluator": 14 * 24 * 60 * 60,
    "umbrella_admin": 90 * 24 * 60 * 60,
}


def _valid_time(value: object) -> bool:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not isfinite(value) or value <= 0):
        return False
    try:
        datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class CollaborationGrant:
    grant_id: str
    collaborator_id: str
    role: CollaboratorRole
    learner_ids: tuple[str, ...]
    course_ids: tuple[str, ...]
    scopes: tuple[str, ...]
    created_by_parent: str
    created_at: float
    expires_at: float
    revoked: bool = False
    revoked_at: float = 0.0


@dataclass(frozen=True)
class CollaborationDecision:
    allowed: bool
    findings: tuple[str, ...]


class CollaborationLedger:
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._grants: dict[str, CollaborationGrant] = {}

    def create(self, grant: CollaborationGrant) -> CollaborationGrant:
        now = self._clock()
        if (not _valid_time(now) or not _valid_time(grant.created_at)
                or abs(grant.created_at - now) > 300):
            raise ValueError("grant creation time is not fresh relative to the trusted service clock")
        grant = replace(
            grant,
            grant_id=grant.grant_id.strip(),
            collaborator_id=grant.collaborator_id.strip(),
            learner_ids=tuple(item.strip() for item in grant.learner_ids),
            course_ids=tuple(item.strip() for item in grant.course_ids),
            scopes=tuple(item.strip().lower() for item in grant.scopes),
            created_by_parent=grant.created_by_parent.strip(),
            created_at=float(now),
        )
        if grant.grant_id in self._grants:
            raise ValueError("collaboration grant identity is immutable")
        findings = validate_grant(grant, now=now)
        if not findings.allowed:
            raise ValueError("; ".join(findings.findings))
        semantic_key = self._semantic_key(grant)
        if any(
            not existing.revoked and existing.expires_at > now
            and self._semantic_key(existing) == semantic_key
            for existing in self._grants.values()
        ):
            raise ValueError("an equivalent active collaboration grant already exists")
        if any(
            not existing.revoked and existing.expires_at > now
            and self._overlaps(grant, existing)
            for existing in self._grants.values()
        ):
            raise ValueError("an overlapping active collaboration permission already exists")
        self._grants[grant.grant_id] = grant
        return grant

    def revoke(self, grant_id: str, *, parent_id: str) -> CollaborationGrant:
        grant = self._require(grant_id)
        if grant.revoked:
            raise ValueError("grant is already revoked")
        if parent_id.strip() != grant.created_by_parent:
            raise PermissionError("only the authorizing parent may revoke this grant")
        revoked_at = self._clock()
        if (not _valid_time(revoked_at) or revoked_at < grant.created_at
                or revoked_at >= grant.expires_at):
            raise ValueError("valid revocation timestamp required")
        updated = replace(grant, revoked=True, revoked_at=float(revoked_at))
        self._grants[grant_id] = updated
        return updated

    def authorize(self, grant_id: str, *, collaborator_id: str, learner_id: str,
                  scope: str, course_id: str = "") -> CollaborationDecision:
        grant = self._require(grant_id)
        findings: list[str] = []
        now = self._clock()
        if grant.revoked:
            findings.append("Grant is revoked.")
        if collaborator_id.strip() != grant.collaborator_id:
            findings.append("Collaborator identity does not match the grant.")
        if learner_id.strip() not in grant.learner_ids:
            findings.append("Learner is outside the grant.")
        normalized_scope = scope.strip().lower()
        if normalized_scope not in grant.scopes or normalized_scope not in ROLE_SCOPES[grant.role]:
            findings.append("Scope is outside the role and grant.")
        if normalized_scope in FORBIDDEN_SCOPES:
            findings.append("Restricted household data cannot be delegated.")
        if not _valid_time(now) or now < grant.created_at or now >= grant.expires_at:
            findings.append("Grant is expired.")
        if grant.course_ids and course_id.strip() not in grant.course_ids:
            findings.append("Course is outside the grant.")
        return CollaborationDecision(not findings, tuple(findings))

    def _require(self, grant_id: str) -> CollaborationGrant:
        try:
            return self._grants[grant_id]
        except KeyError as exc:
            raise KeyError("unknown collaboration grant") from exc

    @staticmethod
    def _semantic_key(grant: CollaborationGrant) -> tuple[object, ...]:
        return (
            grant.collaborator_id, grant.role, tuple(sorted(grant.learner_ids)),
            tuple(sorted(grant.course_ids)), tuple(sorted(grant.scopes)),
        )

    @staticmethod
    def _overlaps(left: CollaborationGrant, right: CollaborationGrant) -> bool:
        if left.collaborator_id != right.collaborator_id:
            return False
        if not set(left.learner_ids).intersection(right.learner_ids):
            return False
        if not set(left.scopes).intersection(right.scopes):
            return False
        return (
            not left.course_ids or not right.course_ids
            or bool(set(left.course_ids).intersection(right.course_ids))
        )


def validate_grant(grant: CollaborationGrant, *, now: float | None = None) -> CollaborationDecision:
    findings: list[str] = []
    learner_ids = tuple(item.strip() for item in grant.learner_ids)
    course_ids = tuple(item.strip() for item in grant.course_ids)
    scopes = tuple(item.strip().lower() for item in grant.scopes)
    if not all((grant.grant_id.strip(), grant.collaborator_id.strip(),
                grant.created_by_parent.strip())):
        findings.append("Grant, collaborator, and parent identities are required.")
    if (not learner_ids or any(not item for item in learner_ids)
            or len(set(learner_ids)) != len(learner_ids)):
        findings.append("A unique learner scope is required.")
    if (any(not item for item in course_ids)
            or len(set(course_ids)) != len(course_ids)):
        findings.append("Course IDs must be unique and nonempty.")
    if (not scopes or any(not item for item in scopes)
            or len(set(scopes)) != len(scopes)):
        findings.append("A unique scope set is required.")
    invalid = set(scopes) - ROLE_SCOPES.get(grant.role, frozenset())
    if invalid:
        findings.append("Role does not permit scopes: " + ", ".join(sorted(invalid)))
    if set(scopes) & FORBIDDEN_SCOPES:
        findings.append("Restricted household data cannot be delegated.")
    if (not _valid_time(grant.created_at) or not _valid_time(grant.expires_at)
            or grant.expires_at <= grant.created_at):
        findings.append("Grant expiry must be finite and later than creation.")
    elif grant.expires_at - grant.created_at > MAX_GRANT_TTL_SECONDS.get(grant.role, 0):
        findings.append("Grant lifetime exceeds the role-specific maximum and requires renewal.")
    if now is not None and (not _valid_time(now) or abs(grant.created_at - now) > 300):
        findings.append("Grant creation time is not fresh relative to the trusted service clock.")
    if grant.revoked or grant.revoked_at != 0.0:
        findings.append("New grants must begin active with no revocation state.")
    if grant.role in {"tutor", "co_op_instructor"} and not course_ids:
        findings.append("Tutor/co-op grants must name at least one course.")
    return CollaborationDecision(not findings, tuple(findings))
