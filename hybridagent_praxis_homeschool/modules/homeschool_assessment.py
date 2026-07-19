"""Annual assessment, test-administrator, and evaluator data-room workflow."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from typing import Callable

from .homeschool_jurisdictions import get_homeschool_profile, profile_for_route
from .homeschool_portfolio import PortfolioLedger
from .homeschool_validation import iso_date, valid_sha256

MAX_EVALUATOR_ROOM_TTL_SECONDS = 14 * 24 * 60 * 60


def _valid_time(value: object) -> bool:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not isfinite(value) or value <= 0):
        return False
    try:
        datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return False
    return True

ASSESSMENT_METHODS: dict[str, tuple[str, ...]] = {
    "FL": ("certified_teacher_portfolio", "nationally_normed_test", "state_assessment",
           "licensed_psychologist", "district_parent_agreed_tool"),
    "GA": ("nationally_normed_test",),
    "SC": ("statewide_test", "association_defined"),
    "TN": ("state_or_standardized_test", "church_related_school_defined"),
    "VA": ("nationally_normed_test", "evaluator_letter", "other_equivalent_evidence"),
    "WV": ("nationally_normed_test", "state_test", "certified_teacher_portfolio",
           "county_parent_agreed_assessment"),
    "MD": ("portfolio_review", "supervising_nonpublic_review"),
    "PA": ("nationally_normed_test", "qualified_evaluator"),
    "OH": ("not_required_by_current_home_education_route",),
    "NJ": ("not_required_by_state_framework",),
    "NY": ("nationally_normed_test", "written_narrative", "state_test"),
    "CT": ("recommended_parent_selected_assessment",),
    "MA": ("district_approved_assessment_method",),
}


@dataclass(frozen=True)
class ParentAssessmentAttestation:
    attestation_id: str
    parent_id: str
    learner_id: str
    state: str
    route: str
    method: str
    source_verified_on: str
    confirmed_at: float
    plan_hash: str
    attestation_hash: str


def assessment_attestation_hash(attestation: ParentAssessmentAttestation) -> str:
    payload = json.dumps({
        "attestation_id": attestation.attestation_id,
        "parent_id": attestation.parent_id,
        "learner_id": attestation.learner_id,
        "state": attestation.state,
        "route": attestation.route,
        "method": attestation.method,
        "source_verified_on": attestation.source_verified_on,
        "confirmed_at": attestation.confirmed_at,
        "plan_hash": attestation.plan_hash,
    }, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class AssessmentPlan:
    assessment_id: str
    learner_id: str
    state: str
    route: str
    grade: int
    school_year: str
    method: str
    administrator_id: str = ""
    administrator_qualification: str = ""
    parent_selected: bool = False
    scheduled_at: float = 0.0
    route_confirmed_by_parent: bool = False
    school_year_start: str = ""
    school_year_end: str = ""
    parent_attestation: ParentAssessmentAttestation | None = None


def assessment_plan_hash(plan: AssessmentPlan) -> str:
    payload = {
        "assessment_id": plan.assessment_id,
        "learner_id": plan.learner_id,
        "state": plan.state,
        "route": plan.route,
        "grade": plan.grade,
        "school_year": plan.school_year,
        "method": plan.method,
        "administrator_id": plan.administrator_id,
        "administrator_qualification": plan.administrator_qualification,
        "parent_selected": plan.parent_selected,
        "scheduled_at": plan.scheduled_at,
        "route_confirmed_by_parent": plan.route_confirmed_by_parent,
        "school_year_start": plan.school_year_start,
        "school_year_end": plan.school_year_end,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class AssessmentDecision:
    required: bool
    allowed: bool
    accepted_methods: tuple[str, ...]
    findings: tuple[str, ...]


@dataclass(frozen=True)
class AssessmentResult:
    assessment_id: str
    learner_id: str
    school_year: str
    result_hash: str
    received_at: float
    source: str
    parent_attested: bool
    interpretation: str = ""
    result_manifest_hash: str = ""
    parent_attestation: ParentAssessmentResultAttestation | None = None


@dataclass(frozen=True)
class ParentAssessmentResultAttestation:
    attestation_id: str
    parent_id: str
    assessment_id: str
    learner_id: str
    school_year: str
    result_manifest_hash: str
    confirmed_at: float
    attestation_hash: str


def assessment_result_manifest_hash(result: AssessmentResult) -> str:
    payload = {
        "assessment_id": result.assessment_id,
        "learner_id": result.learner_id,
        "school_year": result.school_year,
        "result_hash": result.result_hash,
        "received_at": result.received_at,
        "source": result.source,
        "interpretation": result.interpretation,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def assessment_result_attestation_hash(
        attestation: ParentAssessmentResultAttestation) -> str:
    payload = json.dumps({
        "attestation_id": attestation.attestation_id,
        "parent_id": attestation.parent_id,
        "assessment_id": attestation.assessment_id,
        "learner_id": attestation.learner_id,
        "school_year": attestation.school_year,
        "result_manifest_hash": attestation.result_manifest_hash,
        "confirmed_at": attestation.confirmed_at,
    }, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class EvaluatorRoom:
    room_id: str
    learner_id: str
    evaluator_id: str
    artifact_ids: tuple[str, ...]
    expires_at: float
    created_by_parent: str
    created_at: float
    revoked: bool = False
    revoked_at: float = 0.0


def accepted_methods(state: str, route: str = "") -> tuple[str, ...]:
    code = state.strip().upper()
    profile = get_homeschool_profile(code)
    normalized = route.strip().lower()
    if profile is None or (normalized and normalized not in profile.routes):
        return ()
    if code == "TN":
        if normalized == "church_related_school":
            return ("church_related_school_defined",)
        if normalized == "independent_home_school":
            return ("state_or_standardized_test",)
    if code == "SC":
        if normalized == "option1_district":
            return ("statewide_test",)
        if normalized in {"option2_scaihs", "option3_association"}:
            return ("association_defined",)
    if code == "MD":
        if normalized == "local_supervision":
            return ("portfolio_review",)
        if normalized == "nonpublic_supervision":
            return ("supervising_nonpublic_review",)
    if code == "VA" and normalized == "religious_exemption":
        return ()
    if code == "FL" and normalized == "private_school_umbrella":
        return ()
    if code == "FL" and normalized == "pep_scholarship":
        return ("nationally_normed_test", "state_assessment")
    if code == "PA" and normalized == "private_tutor":
        return ()
    if code == "WV" and normalized in {"hope_individualized", "learning_pod"}:
        return ()
    return ASSESSMENT_METHODS.get(code, ())


def evaluate_assessment(
        plan: AssessmentPlan, *, evaluated_at: float | None = None) -> AssessmentDecision:
    state_profile = get_homeschool_profile(plan.state)
    if state_profile is None:
        return AssessmentDecision(False, False, (), ("Unsupported state.",))
    findings: list[str] = []
    blocking: list[str] = []
    trusted_now = time.time() if evaluated_at is None else evaluated_at
    if not _valid_time(trusted_now):
        blocking.append("Assessment evaluation requires a valid trusted timestamp.")
    if plan.route not in state_profile.routes:
        blocking.append("Assessment route is not registered for the state.")
    profile = profile_for_route(plan.state, plan.route) or state_profile
    methods = accepted_methods(profile.state, plan.route)
    if not plan.assessment_id or not plan.learner_id or not plan.school_year.strip():
        blocking.append("Assessment, learner, and school-year identities are required.")
    valid_grade = isinstance(plan.grade, int) and not isinstance(plan.grade, bool) and 0 <= plan.grade <= 12
    if not valid_grade:
        blocking.append("Grade must be an integer in [0, 12].")
    grade_trigger = bool(valid_grade and profile.assessment_grades
                         and plan.grade in profile.assessment_grades)
    required = profile.assessment_frequency_years == 1 or grade_trigger
    if plan.parent_selected is not True:
        blocking.append("The accountable parent must select the assessment method.")
    if plan.route_confirmed_by_parent is not True:
        blocking.append("The accountable parent must confirm the legal route.")
    not_applicable = not required and not methods
    effective_methods = ("not_applicable",) if not_applicable else methods
    if plan.method not in effective_methods:
        blocking.append("Assessment method is not registered for the state/route.")
    administrator_methods = {
        "certified_teacher_portfolio", "nationally_normed_test", "licensed_psychologist",
        "qualified_evaluator", "written_narrative", "state_or_standardized_test",
        "statewide_test", "district_approved_assessment_method",
    }
    if plan.method in administrator_methods:
        if not plan.administrator_id or not plan.administrator_qualification:
            blocking.append("A named administrator/evaluator and qualification are required.")
    school_start: date | None
    school_end: date | None
    try:
        school_start = iso_date(plan.school_year_start, "school_year_start")
        school_end = iso_date(plan.school_year_end, "school_year_end")
        if school_end < school_start:
            blocking.append("School-year end must not precede its start.")
    except ValueError as exc:
        blocking.append(str(exc))
        school_start = school_end = None
    if not not_applicable and not _valid_time(plan.scheduled_at):
        blocking.append("Scheduled assessment time must be finite and positive.")
    elif not not_applicable and school_start is not None and school_end is not None:
        scheduled_date = datetime.fromtimestamp(plan.scheduled_at, tz=timezone.utc).date()
        if not school_start <= scheduled_date <= school_end:
            blocking.append("Scheduled assessment must fall inside the school year.")
    attestation = plan.parent_attestation
    if attestation is None:
        blocking.append("An immutable accountable-parent assessment attestation is required.")
    else:
        if not all((attestation.attestation_id.strip(), attestation.parent_id.strip())):
            blocking.append("Assessment attestation and parent identities are required.")
        if (attestation.learner_id != plan.learner_id
                or attestation.state != profile.state
                or attestation.route != plan.route
                or attestation.method != plan.method
                or attestation.source_verified_on != profile.verified_on):
            blocking.append("Assessment attestation is not bound to this learner, route, method, and source version.")
        if (not _valid_time(attestation.confirmed_at)
                or (not not_applicable and attestation.confirmed_at > plan.scheduled_at)):
            blocking.append("Assessment attestation time must precede any scheduled assessment.")
        if _valid_time(trusted_now) and attestation.confirmed_at > trusted_now:
            blocking.append("Assessment attestation cannot be in the future relative to trusted time.")
        if (not valid_sha256(attestation.plan_hash)
                or attestation.plan_hash != assessment_plan_hash(plan)
                or not valid_sha256(attestation.attestation_hash)
                or attestation.attestation_hash != assessment_attestation_hash(attestation)):
            blocking.append("Assessment attestation hash is not bound to the selected plan.")
    findings.extend(blocking)
    if profile.confidence != "primary_source":
        findings.append("Current primary text must be re-verified before parent submission.")
    return AssessmentDecision(required, not blocking, effective_methods, tuple(findings))


class AssessmentResultLedger:
    def __init__(self) -> None:
        self._records: dict[str, AssessmentResult] = {}
        self._report_hashes: set[str] = set()

    def import_result(self, plan: AssessmentPlan, result: AssessmentResult, *,
                      imported_at: float, report_content: bytes) -> AssessmentResult:
        decision = evaluate_assessment(plan, evaluated_at=imported_at)
        if not decision.allowed:
            raise ValueError("assessment plan is not ready")
        if not decision.required or plan.method == "not_applicable":
            raise ValueError("a no-assessment route cannot receive an assessment result")
        if result.assessment_id in self._records:
            raise ValueError("assessment result identity is immutable")
        if (result.assessment_id != plan.assessment_id
                or result.learner_id != plan.learner_id
                or result.school_year != plan.school_year):
            raise ValueError("result is not bound to the assessment plan")
        if not report_content:
            raise ValueError("assessment report content must be nonempty")
        actual_hash = "sha256:" + hashlib.sha256(report_content).hexdigest()
        if (not valid_sha256(result.result_hash) or result.result_hash != actual_hash
                or not result.source.strip()):
            raise ValueError("result provenance and sha256 hash are required")
        if result.result_hash in self._report_hashes:
            raise ValueError("assessment report content is already imported")
        if (not _valid_time(result.received_at) or not _valid_time(imported_at)
                or result.received_at < plan.scheduled_at or result.received_at > imported_at):
            raise ValueError("valid received timestamp required")
        school_end = iso_date(plan.school_year_end, "school_year_end")
        received_date = datetime.fromtimestamp(result.received_at, tz=timezone.utc).date()
        if received_date > school_end + timedelta(days=90):
            raise ValueError("assessment result falls outside the school-year result window")
        manifest_hash = assessment_result_manifest_hash(result)
        attestation = result.parent_attestation
        plan_parent = plan.parent_attestation.parent_id if plan.parent_attestation else ""
        if (result.parent_attested is not True or attestation is None
                or not attestation.attestation_id.strip()
                or attestation.parent_id != plan_parent
                or attestation.assessment_id != result.assessment_id
                or attestation.learner_id != result.learner_id
                or attestation.school_year != result.school_year
                or result.result_manifest_hash != manifest_hash
                or attestation.result_manifest_hash != manifest_hash
                or not _valid_time(attestation.confirmed_at)
                or not result.received_at <= attestation.confirmed_at <= imported_at
                or not valid_sha256(attestation.attestation_hash)
                or attestation.attestation_hash != assessment_result_attestation_hash(attestation)):
            raise ValueError("a bound accountable-parent result attestation is required")
        self._records[result.assessment_id] = result
        self._report_hashes.add(result.result_hash)
        return result

    def get(self, assessment_id: str) -> AssessmentResult:
        try:
            return self._records[assessment_id]
        except KeyError as exc:
            raise KeyError("unknown assessment result") from exc


def import_result(plan: AssessmentPlan, result: AssessmentResult, *, imported_at: float,
                  report_content: bytes, ledger: AssessmentResultLedger) -> AssessmentResult:
    return ledger.import_result(
        plan, result, imported_at=imported_at, report_content=report_content,
    )


class EvaluatorRoomLedger:
    def __init__(self, portfolio: PortfolioLedger, *,
                 clock: Callable[[], float] = time.time) -> None:
        self._portfolio = portfolio
        self._clock = clock
        self._rooms: dict[str, EvaluatorRoom] = {}

    def create(self, *, room_id: str, learner_id: str, evaluator_id: str,
               artifact_ids: tuple[str, ...], expires_at: float,
               created_by_parent: str) -> EvaluatorRoom:
        room_id = room_id.strip()
        learner_id = learner_id.strip()
        evaluator_id = evaluator_id.strip()
        artifact_ids = tuple(item.strip() for item in artifact_ids)
        created_by_parent = created_by_parent.strip()
        if room_id in self._rooms:
            raise ValueError("evaluator room identity is immutable")
        if not all((room_id, learner_id, evaluator_id, created_by_parent)):
            raise ValueError("room, learner, evaluator, and parent identities are required")
        if (not artifact_ids or any(not item for item in artifact_ids)
                or len(set(artifact_ids)) != len(artifact_ids)):
            raise ValueError("a unique parent-selected artifact set is required")
        now = self._clock()
        if (not _valid_time(expires_at) or not _valid_time(now)
                or expires_at <= now
                or expires_at - now > MAX_EVALUATOR_ROOM_TTL_SECONDS):
            raise ValueError("evaluator room requires a bounded future expiry")
        for artifact_id in artifact_ids:
            if self._portfolio.get(artifact_id).learner_id != learner_id:
                raise PermissionError("evaluator-room artifact belongs to another learner")
        requested_artifacts = set(artifact_ids)
        if any(
            not existing.revoked and existing.expires_at > now
            and existing.evaluator_id == evaluator_id
            and existing.learner_id == learner_id
            and requested_artifacts.intersection(existing.artifact_ids)
            for existing in self._rooms.values()
        ):
            raise ValueError("an overlapping active evaluator-room permission already exists")
        room = EvaluatorRoom(
            room_id, learner_id, evaluator_id, artifact_ids, float(expires_at),
            created_by_parent, float(now),
        )
        self._rooms[room.room_id] = room
        return room

    def authorize(self, room_id: str, *, evaluator_id: str, learner_id: str,
                  artifact_id: str) -> bool:
        try:
            room = self._rooms[room_id]
        except KeyError:
            return False
        now = self._clock()
        return (
            room.revoked is False and evaluator_id.strip() == room.evaluator_id
            and learner_id.strip() == room.learner_id and artifact_id.strip() in room.artifact_ids
            and _valid_time(now) and room.created_at <= now < room.expires_at
        )

    def revoke(self, room_id: str, *, parent_id: str) -> EvaluatorRoom:
        try:
            room = self._rooms[room_id]
        except KeyError as exc:
            raise KeyError("unknown evaluator room") from exc
        if room.revoked:
            raise ValueError("evaluator room is already revoked")
        if parent_id.strip() != room.created_by_parent:
            raise PermissionError("only the authorizing parent may revoke the room")
        now = self._clock()
        if not _valid_time(now) or not room.created_at <= now < room.expires_at:
            raise ValueError("revocation time is outside the room lifecycle")
        revoked = replace(room, revoked=True, revoked_at=float(now))
        self._rooms[room_id] = revoked
        return revoked
