"""Evidence-backed homeschool transcript, GPA, and diploma provenance."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from .homeschool_jurisdictions import get_homeschool_profile
from .homeschool_validation import valid_sha256

CourseLevel = Literal["standard", "honors", "ap", "dual_enrollment"]
COURSE_LEVELS = frozenset({"standard", "honors", "ap", "dual_enrollment"})


@dataclass(frozen=True)
class TranscriptPolicy:
    policy_id: str
    issuer_name: str
    credit_definition: str
    grade_scale: str
    honors_bonus: Decimal = Decimal("0.5")
    ap_dual_bonus: Decimal = Decimal("1.0")
    required_credits: Decimal = Decimal("1.0")


@dataclass(frozen=True)
class CourseRecord:
    course_id: str
    learner_id: str
    title: str
    school_year: str
    credits: Decimal
    grade_points: Decimal
    level: CourseLevel
    evidence_ids: tuple[str, ...]
    description: str
    parent_finalized: bool
    external_provider: str = ""
    external_record_hash: str = ""


@dataclass(frozen=True)
class TranscriptEvidence:
    evidence_id: str
    learner_id: str
    school_year: str
    evidence_type: str
    content_hash: str
    credit_bearing: bool = True


class TranscriptEvidenceLedger:
    def __init__(self) -> None:
        self._records: dict[str, TranscriptEvidence] = {}
        self._credit_content_ids: dict[str, str] = {}

    def append(self, evidence: TranscriptEvidence, *, content: bytes) -> TranscriptEvidence:
        if evidence.evidence_id in self._records:
            raise ValueError("transcript evidence identity is immutable")
        if not all((evidence.evidence_id.strip(), evidence.learner_id.strip(),
                    evidence.school_year.strip(), evidence.evidence_type.strip())):
            raise ValueError("evidence identity, learner, school year, and type are required")
        if evidence.credit_bearing is not True and evidence.credit_bearing is not False:
            raise ValueError("credit_bearing must be a literal boolean")
        if not content:
            raise ValueError("transcript evidence content must be nonempty")
        actual_hash = "sha256:" + hashlib.sha256(content).hexdigest()
        if not valid_sha256(evidence.content_hash) or evidence.content_hash != actual_hash:
            raise ValueError("transcript evidence hash must match the ingested content")
        if evidence.credit_bearing and evidence.content_hash in self._credit_content_ids:
            raise ValueError("credit-bearing transcript evidence content is already recorded")
        self._records[evidence.evidence_id] = evidence
        if evidence.credit_bearing:
            self._credit_content_ids[evidence.content_hash] = evidence.evidence_id
        return evidence

    def get(self, evidence_id: str) -> TranscriptEvidence:
        try:
            return self._records[evidence_id]
        except KeyError as exc:
            raise KeyError("unknown transcript evidence") from exc


@dataclass(frozen=True)
class Transcript:
    transcript_id: str
    learner_id: str
    state: str
    issuer_name: str
    policy_id: str
    policy_hash: str
    courses: tuple[CourseRecord, ...]
    evidence_manifest: tuple[TranscriptEvidence, ...]
    total_credits: Decimal
    unweighted_gpa: Decimal
    weighted_gpa: Decimal
    provenance_note: str
    parent_approved: bool
    record_hash: str


@dataclass(frozen=True)
class DiplomaPacket:
    diploma_id: str
    learner_id: str
    state: str
    issuer_name: str
    transcript_id: str
    transcript_hash: str
    policy_id: str
    completion_attested_by_parent: bool
    policy_hash: str = ""
    claims_state_issued: bool = False
    claims_accredited: bool = False


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must not be boolean")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be decimal") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _canonical_hash(payload: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def transcript_policy_hash(policy: TranscriptPolicy) -> str:
    payload = {
        "schema": "praxis.transcript-policy.v1",
        "policy_id": policy.policy_id,
        "issuer_name": policy.issuer_name,
        "credit_definition": policy.credit_definition,
        "grade_scale": policy.grade_scale,
        "honors_bonus": str(policy.honors_bonus),
        "ap_dual_bonus": str(policy.ap_dual_bonus),
        "required_credits": str(policy.required_credits),
    }
    return _canonical_hash(payload)


def validate_course(course: CourseRecord) -> tuple[str, ...]:
    findings: list[str] = []
    if not course.course_id or not course.learner_id or not course.title.strip():
        findings.append("Course, learner, and title are required.")
    if not course.school_year.strip():
        findings.append("Course school year is required.")
    if course.level not in COURSE_LEVELS:
        findings.append("Course level must be standard, honors, ap, or dual_enrollment.")
    credits = _decimal(course.credits, "credits")
    points = _decimal(course.grade_points, "grade_points")
    if credits <= 0 or credits > Decimal(10):
        findings.append("Credits must be in (0, 10].")
    if points < 0 or points > 4:
        findings.append("Unweighted grade points must be in [0, 4].")
    if (not course.evidence_ids or any(not item.strip() for item in course.evidence_ids)
            or len(set(course.evidence_ids)) != len(course.evidence_ids)):
        findings.append("A transcript course requires evidence.")
    if not course.description.strip():
        findings.append("A transcript course requires a course description.")
    if course.parent_finalized is not True:
        findings.append("The accountable parent must finalize the course record.")
    if course.level == "dual_enrollment" and (
            not course.external_provider.strip() or not valid_sha256(course.external_record_hash)):
        findings.append("Dual-enrollment credit requires provider and official record hash.")
    if bool(course.external_provider.strip()) != bool(course.external_record_hash):
        findings.append("External provider and official record hash must be supplied together.")
    if course.external_record_hash and not valid_sha256(course.external_record_hash):
        findings.append("External official record hash must be canonical SHA-256.")
    return tuple(findings)


def _course_payload(course: CourseRecord) -> dict[str, object]:
    return {
        "course_id": course.course_id,
        "learner_id": course.learner_id,
        "title": course.title,
        "school_year": course.school_year,
        "credits": str(course.credits),
        "grade_points": str(course.grade_points),
        "level": course.level,
        "evidence_ids": list(course.evidence_ids),
        "description": course.description,
        "parent_finalized": course.parent_finalized,
        "external_provider": course.external_provider,
        "external_record_hash": course.external_record_hash,
    }


def _evidence_payload(evidence: TranscriptEvidence) -> dict[str, object]:
    return {
        "evidence_id": evidence.evidence_id,
        "learner_id": evidence.learner_id,
        "school_year": evidence.school_year,
        "evidence_type": evidence.evidence_type,
        "content_hash": evidence.content_hash,
        "credit_bearing": evidence.credit_bearing,
    }


def _calculate_totals(courses: tuple[CourseRecord, ...], policy: TranscriptPolicy) -> tuple[Decimal, Decimal, Decimal]:
    total = sum((_decimal(course.credits, "credits") for course in courses), Decimal(0))
    if total <= 0:
        raise ValueError("transcript requires positive total credits")
    unweighted_total = sum(
        (_decimal(course.credits, "credits") * _decimal(course.grade_points, "grade_points")
         for course in courses), Decimal(0))
    weighted_total = Decimal(0)
    for course in courses:
        bonus = Decimal(0)
        if course.level == "honors":
            bonus = _decimal(policy.honors_bonus, "honors_bonus")
        elif course.level in {"ap", "dual_enrollment"}:
            bonus = _decimal(policy.ap_dual_bonus, "ap_dual_bonus")
        weighted_total += _decimal(course.credits, "credits") * (
            _decimal(course.grade_points, "grade_points") + bonus)
    quant = Decimal("0.001")
    return (
        total.quantize(quant, rounding=ROUND_HALF_UP),
        (unweighted_total / total).quantize(quant, rounding=ROUND_HALF_UP),
        (weighted_total / total).quantize(quant, rounding=ROUND_HALF_UP),
    )


def _transcript_payload(*, transcript_id: str, learner_id: str, state: str,
                        issuer_name: str, policy_id: str, policy_hash: str,
                        courses: tuple[CourseRecord, ...],
                        evidence_manifest: tuple[TranscriptEvidence, ...]) -> dict[str, object]:
    return {
        "schema": "praxis.transcript.v1",
        "transcript_id": transcript_id,
        "learner_id": learner_id,
        "state": state,
        "issuer_name": issuer_name,
        "policy_id": policy_id,
        "policy_hash": policy_hash,
        "courses": [_course_payload(course) for course in courses],
        "evidence_manifest": [_evidence_payload(item) for item in evidence_manifest],
    }


def _validate_policy(policy: TranscriptPolicy) -> None:
    if not all((policy.policy_id.strip(), policy.issuer_name.strip(),
                policy.credit_definition.strip(), policy.grade_scale.strip())):
        raise ValueError("policy identity, issuer, credit definition, and grade scale are required")
    honors_bonus = _decimal(policy.honors_bonus, "honors_bonus")
    ap_dual_bonus = _decimal(policy.ap_dual_bonus, "ap_dual_bonus")
    required_credits = _decimal(policy.required_credits, "required_credits")
    if not Decimal(0) <= honors_bonus <= Decimal(2):
        raise ValueError("honors_bonus must be in [0, 2]")
    if not Decimal(0) <= ap_dual_bonus <= Decimal(2):
        raise ValueError("ap_dual_bonus must be in [0, 2]")
    if required_credits <= 0:
        raise ValueError("required_credits must be positive")


def _resolve_courses(*, learner_id: str, courses: tuple[CourseRecord, ...],
                     evidence_ledger: TranscriptEvidenceLedger) -> tuple[TranscriptEvidence, ...]:
    if not courses:
        raise ValueError("transcript requires at least one course")
    if len({course.course_id for course in courses}) != len(courses):
        raise ValueError("course IDs must be unique")
    canonical_courses: set[tuple[str, str]] = set()
    used_evidence: set[str] = set()
    resolved: dict[str, TranscriptEvidence] = {}
    for course in courses:
        if course.learner_id != learner_id:
            raise ValueError("course belongs to a different learner")
        findings = validate_course(course)
        if findings:
            raise ValueError("; ".join(findings))
        canonical = (" ".join(course.title.lower().split()), course.school_year)
        if canonical in canonical_courses:
            raise ValueError("canonical course identity is duplicated")
        canonical_courses.add(canonical)
        if used_evidence.intersection(course.evidence_ids):
            raise ValueError("transcript evidence cannot be credited to multiple courses")
        for evidence_id in course.evidence_ids:
            evidence = evidence_ledger.get(evidence_id)
            if evidence.learner_id != learner_id or evidence.school_year != course.school_year:
                raise ValueError("course evidence belongs to another learner or school year")
            if evidence.credit_bearing is not True:
                raise ValueError("course credit requires learner-produced credit-bearing evidence")
            resolved[evidence_id] = evidence
        if (course.external_record_hash
                and not any(resolved[evidence_id].content_hash == course.external_record_hash
                            for evidence_id in course.evidence_ids)):
            raise ValueError("external official record hash does not resolve through course evidence")
        used_evidence.update(course.evidence_ids)
    return tuple(resolved[evidence_id] for evidence_id in sorted(resolved))


def build_transcript(*, transcript_id: str, learner_id: str, state: str,
                     policy: TranscriptPolicy, courses: tuple[CourseRecord, ...],
                     parent_approved: bool,
                     evidence_ledger: TranscriptEvidenceLedger) -> Transcript:
    if not transcript_id.strip() or not learner_id.strip():
        raise ValueError("transcript and learner identities are required")
    _validate_policy(policy)
    state_code = state.strip().upper()
    if get_homeschool_profile(state_code) is None:
        raise ValueError("state must be a supported homeschool jurisdiction")
    if parent_approved is not True:
        raise PermissionError("parent approval is required to issue a transcript")
    evidence_manifest = _resolve_courses(
        learner_id=learner_id, courses=courses, evidence_ledger=evidence_ledger,
    )
    total, unweighted, weighted = _calculate_totals(courses, policy)
    policy_hash = transcript_policy_hash(policy)
    record_hash = _canonical_hash(_transcript_payload(
        transcript_id=transcript_id, learner_id=learner_id, state=state_code,
        issuer_name=policy.issuer_name, policy_id=policy.policy_id,
        policy_hash=policy_hash, courses=courses, evidence_manifest=evidence_manifest,
    ))
    return Transcript(
        transcript_id=transcript_id, learner_id=learner_id, state=state_code,
        issuer_name=policy.issuer_name, policy_id=policy.policy_id,
        policy_hash=policy_hash, courses=courses, evidence_manifest=evidence_manifest,
        total_credits=total, unweighted_gpa=unweighted, weighted_gpa=weighted,
        provenance_note=(
            "Parent-issued homeschool record; verify recipient and jurisdiction requirements."
        ),
        parent_approved=True, record_hash=record_hash,
    )


def validate_diploma(packet: DiplomaPacket, *, transcript: Transcript,
                     policy: TranscriptPolicy) -> tuple[str, ...]:
    findings: list[str] = []
    if not all((packet.diploma_id, packet.learner_id, packet.issuer_name,
                packet.transcript_id, packet.transcript_hash, packet.policy_id,
                packet.policy_hash)):
        findings.append("Diploma identity, learner, issuer, transcript, and policy are required.")
    if packet.completion_attested_by_parent is not True:
        findings.append("Parent completion attestation is required.")
    packet_state = packet.state.strip().upper()
    if packet.state != packet_state or get_homeschool_profile(packet_state) is None:
        findings.append("Diploma state must be a canonical supported homeschool jurisdiction.")
    if packet.claims_state_issued:
        findings.append("Praxis may not label a parent-issued diploma as state-issued.")
    if packet.claims_accredited:
        findings.append("Praxis may not claim accreditation without an actual accredited issuer record.")
    try:
        _validate_policy(policy)
        recomputed_total, recomputed_unweighted, recomputed_weighted = _calculate_totals(
            transcript.courses, policy,
        )
        evidence_by_id = {item.evidence_id: item for item in transcript.evidence_manifest}
        if len(evidence_by_id) != len(transcript.evidence_manifest):
            raise ValueError("transcript evidence manifest contains duplicate identities")
        if not transcript.courses:
            raise ValueError("transcript requires at least one course")
        if len({course.course_id for course in transcript.courses}) != len(transcript.courses):
            raise ValueError("course IDs must be unique")
        canonical_courses: set[tuple[str, str]] = set()
        used_evidence: set[str] = set()
        used_credit_content: set[str] = set()
        for course in transcript.courses:
            if course.learner_id != transcript.learner_id:
                raise ValueError("course belongs to a different learner")
            course_findings = validate_course(course)
            if course_findings:
                raise ValueError("; ".join(course_findings))
            canonical = (" ".join(course.title.lower().split()), course.school_year)
            if canonical in canonical_courses:
                raise ValueError("canonical course identity is duplicated")
            canonical_courses.add(canonical)
            if used_evidence.intersection(course.evidence_ids):
                raise ValueError("transcript evidence cannot be credited to multiple courses")
            for evidence_id in course.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if (evidence is None or evidence.learner_id != transcript.learner_id
                        or evidence.school_year != course.school_year
                        or not valid_sha256(evidence.content_hash)
                        or evidence.credit_bearing is not True):
                    raise ValueError("transcript evidence manifest does not resolve course evidence")
                if evidence.content_hash in used_credit_content:
                    raise ValueError(
                        "credit-bearing transcript evidence content cannot be recorded twice"
                    )
                used_credit_content.add(evidence.content_hash)
            used_evidence.update(course.evidence_ids)
            if (course.external_record_hash
                    and not any(evidence_by_id[evidence_id].content_hash == course.external_record_hash
                                for evidence_id in course.evidence_ids)):
                raise ValueError("external official record hash is unresolved")
        if set(evidence_by_id) != used_evidence:
            raise ValueError("transcript evidence manifest contains unreferenced entries")
        expected_hash = _canonical_hash(_transcript_payload(
            transcript_id=transcript.transcript_id, learner_id=transcript.learner_id,
            state=transcript.state, issuer_name=transcript.issuer_name,
            policy_id=transcript.policy_id, policy_hash=transcript.policy_hash,
            courses=transcript.courses, evidence_manifest=transcript.evidence_manifest,
        ))
    except (KeyError, ValueError) as exc:
        findings.append(f"Transcript manifest cannot be verified: {exc}")
        expected_hash = ""
        recomputed_total = recomputed_unweighted = recomputed_weighted = Decimal(-1)
    current_policy_hash = transcript_policy_hash(policy)
    if (packet.transcript_id != transcript.transcript_id
            or packet.transcript_hash != transcript.record_hash
            or packet.learner_id != transcript.learner_id
            or packet_state != transcript.state
            or packet.issuer_name != transcript.issuer_name
            or packet.policy_id != transcript.policy_id
            or packet.policy_hash != transcript.policy_hash
            or policy.policy_id != transcript.policy_id
            or policy.issuer_name != transcript.issuer_name
            or transcript.policy_hash != current_policy_hash
            or transcript.record_hash != expected_hash
            or transcript.total_credits != recomputed_total
            or transcript.unweighted_gpa != recomputed_unweighted
            or transcript.weighted_gpa != recomputed_weighted
            or transcript.parent_approved is not True):
        findings.append("Diploma is not bound to the recomputed approved transcript and policy.")
    if recomputed_total < _decimal(policy.required_credits, "required_credits"):
        findings.append("Transcript does not satisfy the parent-approved graduation credit threshold.")
    return tuple(findings)
