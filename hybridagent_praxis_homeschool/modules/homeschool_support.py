"""Parent-authored learner support plan and public-service inquiry guardrails."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from .homeschool_jurisdictions import get_homeschool_profile
from .homeschool_validation import valid_sha256

SUPPORT_SOURCES = frozenset({
    "parent_observation", "clinician_document", "qualified_evaluator", "school_record",
})
REENTRY_PLACEMENT_WARNING = (
    "The receiving school controls placement and credit acceptance; this packet does not guarantee either."
)


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
class SupportStrategy:
    need: str
    accommodation: str
    source: str = "parent_observation"
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SupportEvidence:
    evidence_id: str
    learner_id: str
    source: str
    content_hash: str
    household_id: str


class SupportEvidenceLedger:
    def __init__(self, *, household_id: str,
                 authorized_parent_ids: tuple[str, ...]) -> None:
        if not household_id.strip():
            raise ValueError("support evidence household identity is required")
        parents = frozenset(item.strip() for item in authorized_parent_ids)
        if not parents or "" in parents or len(parents) != len(authorized_parent_ids):
            raise ValueError("support evidence requires unique authorized-parent identities")
        self._household_id = household_id.strip()
        self._authorized_parent_ids = parents
        self._records: dict[str, SupportEvidence] = {}

    def authorizes_parent(self, parent_id: str) -> bool:
        return parent_id.strip() in self._authorized_parent_ids

    @property
    def household_id(self) -> str:
        return self._household_id

    def append(self, evidence: SupportEvidence, *, content: bytes) -> SupportEvidence:
        if evidence.evidence_id in self._records:
            raise ValueError("support evidence identity is immutable")
        if not content:
            raise ValueError("support evidence content must be nonempty")
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if (not evidence.evidence_id.strip() or not evidence.learner_id.strip()
                or evidence.household_id.strip() != self._household_id
                or evidence.source not in SUPPORT_SOURCES
                or evidence.content_hash != actual):
            raise ValueError("support evidence requires bound learner, source, and content")
        self._records[evidence.evidence_id] = evidence
        return evidence

    def get(self, evidence_id: str) -> SupportEvidence:
        try:
            return self._records[evidence_id]
        except KeyError as exc:
            raise KeyError("unknown support evidence") from exc


@dataclass(frozen=True)
class ParentSupportAttestation:
    attestation_id: str
    parent_id: str
    learner_id: str
    confirmed_at: float
    plan_content_hash: str
    attestation_hash: str


def support_attestation_hash(attestation: ParentSupportAttestation) -> str:
    payload = json.dumps({
        "attestation_id": attestation.attestation_id,
        "parent_id": attestation.parent_id,
        "learner_id": attestation.learner_id,
        "confirmed_at": attestation.confirmed_at,
        "plan_content_hash": attestation.plan_content_hash,
    }, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class HomeschoolSupportPlan:
    plan_id: str
    learner_id: str
    authored_by_parent: str
    strategies: tuple[SupportStrategy, ...]
    diagnosis_claimed_by_praxis: bool = False
    labeled_as_iep: bool = False
    therapy_schedule_private: bool = True
    parent_attestation: ParentSupportAttestation | None = None


def support_plan_hash(plan: HomeschoolSupportPlan) -> str:
    payload = json.dumps({
        "plan_id": plan.plan_id,
        "learner_id": plan.learner_id,
        "authored_by_parent": plan.authored_by_parent,
        "strategies": [
            {
                "need": item.need,
                "accommodation": item.accommodation,
                "source": item.source,
                "evidence_ids": list(item.evidence_ids),
            }
            for item in plan.strategies
        ],
        "therapy_schedule_private": plan.therapy_schedule_private,
        "diagnosis_claimed_by_praxis": plan.diagnosis_claimed_by_praxis,
        "labeled_as_iep": plan.labeled_as_iep,
    }, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()

@dataclass(frozen=True)
class SupportDecision:
    allowed: bool
    findings: tuple[str, ...]


def validate_support_plan(plan: HomeschoolSupportPlan, *,
                          evidence_ledger: SupportEvidenceLedger | None = None,
                          validated_at: float | None = None) -> SupportDecision:
    findings: list[str] = []
    if not plan.plan_id or not plan.learner_id or not plan.authored_by_parent:
        findings.append("Plan, learner, and parent identity are required.")
    if evidence_ledger is not None and not evidence_ledger.authorizes_parent(
            plan.authored_by_parent):
        findings.append("Support plan author is not an authorized household parent.")
    if not plan.strategies:
        findings.append("At least one parent-selected support strategy is required.")
    if plan.diagnosis_claimed_by_praxis:
        findings.append("Praxis may not diagnose a learner.")
    if plan.labeled_as_iep:
        findings.append("A parent homeschool support plan is not an IEP or district determination.")
    if plan.therapy_schedule_private is not True:
        findings.append("Therapy and medical schedules must remain in the restricted health record.")
    if not _valid_time(validated_at):
        findings.append("Support-plan validation requires a trusted representable timestamp.")
    attestation = plan.parent_attestation
    if (attestation is None or not attestation.attestation_id.strip()
            or attestation.parent_id != plan.authored_by_parent
            or attestation.learner_id != plan.learner_id
            or not _valid_time(attestation.confirmed_at)
            or not _valid_time(validated_at)
            or validated_at is None
            or attestation.confirmed_at > validated_at
            or attestation.plan_content_hash != support_plan_hash(plan)
            or not valid_sha256(attestation.attestation_hash)
            or attestation.attestation_hash != support_attestation_hash(attestation)):
        findings.append("A bound accountable-parent support-plan attestation is required.")
    for strategy in plan.strategies:
        if not strategy.need.strip() or not strategy.accommodation.strip():
            findings.append("Support needs and accommodations must be nonempty.")
        if (any(not item.strip() for item in strategy.evidence_ids)
                or len(set(strategy.evidence_ids)) != len(strategy.evidence_ids)):
            findings.append("Support evidence IDs must be unique and nonempty.")
        if strategy.source not in SUPPORT_SOURCES:
            findings.append("Support strategy source is not an approved observation/document source.")
        if strategy.source == "clinician_document" and not strategy.evidence_ids:
            findings.append("Clinician-sourced support requires referenced clinician documentation.")
        for evidence_id in strategy.evidence_ids:
            if evidence_ledger is None:
                findings.append("Support evidence must resolve through the household evidence ledger.")
                break
            try:
                evidence = evidence_ledger.get(evidence_id)
            except KeyError:
                findings.append("Support evidence reference is unknown.")
                continue
            if evidence.learner_id != plan.learner_id or evidence.source != strategy.source:
                findings.append("Support evidence belongs to another learner or source class.")
    return SupportDecision(not findings, tuple(findings))


@dataclass(frozen=True)
class ServiceInquiryDraft:
    inquiry_id: str
    learner_id: str
    state: str
    request_type: str
    parent_id: str
    evidence_ids: tuple[str, ...]
    claims_guaranteed_services: bool = False
    status: str = "draft_parent_review"
    household_id: str = ""


def evaluate_service_inquiry(
        draft: ServiceInquiryDraft, *,
        evidence_ledger: SupportEvidenceLedger | None = None) -> SupportDecision:
    findings: list[str] = []
    if not draft.inquiry_id or not draft.learner_id or not draft.parent_id:
        findings.append("Inquiry, learner, and parent identity are required.")
    if not draft.household_id.strip():
        findings.append("Inquiry household identity is required.")
    if evidence_ledger is None:
        findings.append("Service inquiry requires trusted household and parent authorization.")
    else:
        if evidence_ledger.household_id != draft.household_id:
            findings.append("Service inquiry authorization belongs to another household.")
        if not evidence_ledger.authorizes_parent(draft.parent_id):
            findings.append("Service inquiry requires an authorized household parent.")
    if (draft.state != draft.state.strip().upper()
            or get_homeschool_profile(draft.state) is None):
        findings.append("Inquiry state must be a canonical supported homeschool state.")
    if draft.status != "draft_parent_review":
        findings.append("New inquiries must begin in draft_parent_review state.")
    if draft.request_type not in {"child_find_information", "evaluation_request",
                                  "service_availability", "reentry_support"}:
        findings.append("Unsupported inquiry type.")
    if draft.claims_guaranteed_services:
        findings.append("Praxis cannot guarantee IDEA, 504, FAPE, evaluation, or service eligibility.")
    if not draft.evidence_ids and draft.request_type == "evaluation_request":
        findings.append("Parent should select supporting evidence for an evaluation request.")
    if (any(not item.strip() for item in draft.evidence_ids)
            or len(set(draft.evidence_ids)) != len(draft.evidence_ids)):
        findings.append("Inquiry evidence IDs must be unique and nonempty.")
    for evidence_id in draft.evidence_ids:
        if evidence_ledger is None:
            findings.append("Inquiry evidence must resolve through the household evidence ledger.")
            break
        try:
            evidence = evidence_ledger.get(evidence_id)
        except KeyError:
            findings.append("Inquiry evidence reference is unknown.")
            continue
        if (evidence.learner_id != draft.learner_id
                or evidence.household_id != draft.household_id):
            findings.append("Inquiry evidence belongs to another learner or household.")
    return SupportDecision(not findings, tuple(findings))


def release_service_inquiry(_: ServiceInquiryDraft) -> None:
    """External release is intentionally absent from the domain module."""
    raise PermissionError("Service inquiries are SEND-held and must be sent by the parent through a governed tool.")


@dataclass(frozen=True)
class ReentryPacket:
    learner_id: str
    state: str
    portfolio_ids: tuple[str, ...]
    assessment_ids: tuple[str, ...]
    transcript_id: str
    parent_approved: bool
    placement_warning: str = REENTRY_PLACEMENT_WARNING


@dataclass(frozen=True)
class ReentryEvidenceRecord:
    record_type: str
    record_id: str
    learner_id: str


class ReentryEvidenceLedger:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ReentryEvidenceRecord] = {}

    def append(self, record: ReentryEvidenceRecord) -> ReentryEvidenceRecord:
        key = (record.record_type, record.record_id)
        if key in self._records:
            raise ValueError("re-entry evidence identity is immutable")
        if (record.record_type not in {"portfolio", "assessment", "transcript"}
                or not record.record_id.strip() or not record.learner_id.strip()):
            raise ValueError("re-entry evidence requires type, identity, and learner")
        self._records[key] = record
        return record

    def get(self, record_type: str, record_id: str) -> ReentryEvidenceRecord:
        try:
            return self._records[(record_type, record_id)]
        except KeyError as exc:
            raise KeyError("unknown re-entry evidence") from exc


def validate_reentry_packet(
        packet: ReentryPacket, *,
        evidence_ledger: ReentryEvidenceLedger | None = None) -> SupportDecision:
    findings: list[str] = []
    if packet.parent_approved is not True:
        findings.append("Parent approval is required before sharing a re-entry packet.")
    if not packet.learner_id.strip():
        findings.append("Re-entry learner identity is required.")
    state = packet.state.strip().upper()
    if packet.state != state or get_homeschool_profile(state) is None:
        findings.append("Re-entry state must be a canonical supported homeschool state.")
    if not packet.portfolio_ids and not packet.assessment_ids and not packet.transcript_id:
        findings.append("The re-entry packet contains no education evidence.")
    references = packet.portfolio_ids + packet.assessment_ids
    if any(not item.strip() for item in references) or len(set(references)) != len(references):
        findings.append("Re-entry evidence IDs must be unique and nonempty.")
    if packet.transcript_id and not packet.transcript_id.strip():
        findings.append("Transcript identity must be nonempty when present.")
    typed_references = (
        tuple(("portfolio", item) for item in packet.portfolio_ids)
        + tuple(("assessment", item) for item in packet.assessment_ids)
        + ((("transcript", packet.transcript_id),) if packet.transcript_id.strip() else ())
    )
    for record_type, record_id in typed_references:
        if evidence_ledger is None:
            findings.append("Re-entry evidence must resolve through the education record ledger.")
            break
        try:
            record = evidence_ledger.get(record_type, record_id)
        except KeyError:
            findings.append("Re-entry evidence reference is unknown.")
            continue
        if record.learner_id != packet.learner_id:
            findings.append("Re-entry evidence belongs to another learner.")
    if packet.placement_warning != REENTRY_PLACEMENT_WARNING:
        findings.append("The canonical placement and credit disclaimer is required.")
    return SupportDecision(not findings, tuple(findings))
