"""Household-owned child-data privacy and scoped disclosure controls.

This is not the school-system FERPA operator wrapper.  The accountable parent owns
and mediates household records; FERPA is surfaced only when a covered school or
its service provider participates.  External disclosure always remains held.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Literal

ActorRole = Literal["parent", "co_parent", "learner", "tutor", "co_op_instructor",
                    "evaluator", "umbrella_admin", "district_contact", "system"]
DataClass = Literal["household_identity", "learner_education", "compliance",
                    "portfolio", "health_disability", "values_preferences",
                    "financial", "child_ai_interactions"]
Purpose = Literal["education_delivery", "parent_oversight", "evaluation",
                  "compliance_review", "service_inquiry", "funding_claim",
                  "advertising", "model_training", "profiling", "public_release"]

PROHIBITED_PURPOSES = frozenset({"advertising", "model_training", "profiling", "public_release"})
EXTERNAL_ROLES = frozenset({"tutor", "co_op_instructor", "evaluator", "umbrella_admin", "district_contact"})
EXTERNAL_ROLE_PURPOSES: dict[str, frozenset[str]] = {
    "tutor": frozenset({"education_delivery"}),
    "co_op_instructor": frozenset({"education_delivery"}),
    "evaluator": frozenset({"evaluation"}),
    "umbrella_admin": frozenset({"compliance_review"}),
    "district_contact": frozenset({"compliance_review"}),
}
VALID_ROLES = frozenset({
    "parent", "co_parent", "learner", "tutor", "co_op_instructor",
    "evaluator", "umbrella_admin", "district_contact", "system",
})
VALID_DATA_CLASSES = frozenset({
    "household_identity", "learner_education", "compliance", "portfolio",
    "health_disability", "values_preferences", "financial", "child_ai_interactions",
})
VALID_PURPOSES = frozenset({
    "education_delivery", "parent_oversight", "evaluation", "compliance_review",
    "service_inquiry", "funding_claim", "advertising", "model_training", "profiling",
    "public_release",
})


@dataclass(frozen=True)
class PrivacyFinding:
    code: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class PrivacyDecision:
    findings: tuple[PrivacyFinding, ...]
    permitted_fields: tuple[str, ...] = ()
    send_held: bool = False

    @property
    def allowed(self) -> bool:
        return not any(f.blocking for f in self.findings)


@dataclass(frozen=True)
class AccessRequest:
    actor_id: str
    actor_role: ActorRole
    learner_id: str
    target_learner_id: str
    data_class: DataClass
    purpose: Purpose
    assigned_learner_ids: tuple[str, ...] = ()
    parent_authorized: bool = False
    covered_school_involved: bool = False
    actor_household_id: str = ""
    target_household_id: str = ""


@dataclass(frozen=True)
class DisclosureEvent:
    event_id: str
    learner_id: str
    recipient_id: str
    recipient_role: ActorRole
    data_class: DataClass
    purpose: Purpose
    fields: tuple[str, ...]
    approved_by_parent: str
    disclosed_at: float
    ferpa_context: bool = False
    household_id: str = ""


class HouseholdDisclosureLedger:
    def __init__(self, *, household_id: str,
                 authorized_parent_ids: tuple[str, ...],
                 learner_ids: tuple[str, ...]) -> None:
        if (not household_id.strip() or not authorized_parent_ids or not learner_ids
                or any(not item.strip() for item in authorized_parent_ids + learner_ids)
                or len(set(authorized_parent_ids)) != len(authorized_parent_ids)
                or len(set(learner_ids)) != len(learner_ids)):
            raise ValueError("ledger household, parent, and learner scopes must be unique and nonempty")
        self._household_id = household_id.strip()
        self._authorized_parent_ids = frozenset(item.strip() for item in authorized_parent_ids)
        self._learner_ids = frozenset(item.strip() for item in learner_ids)
        self._events: dict[str, DisclosureEvent] = {}

    def record(self, event: DisclosureEvent) -> DisclosureEvent:
        if event.event_id in self._events:
            raise ValueError("disclosure events are append-only and unique")
        if (not event.event_id.strip() or not event.learner_id.strip()
                or not event.recipient_id.strip() or not event.household_id.strip()):
            raise ValueError("disclosure identity fields are required")
        if not event.approved_by_parent.strip():
            raise ValueError("external disclosure requires accountable-parent approval")
        if (event.household_id != self._household_id
                or event.approved_by_parent not in self._authorized_parent_ids
                or event.learner_id not in self._learner_ids):
            raise PermissionError("disclosure is outside the ledger household authorization")
        if (not event.fields or any(not field.strip() for field in event.fields)
                or len(set(event.fields)) != len(event.fields)):
            raise ValueError("a unique nonempty minimum-necessary field list is required")
        if event.recipient_role not in EXTERNAL_ROLES:
            raise ValueError("the disclosure ledger records external recipients only")
        if (not isinstance(event.disclosed_at, (int, float))
                or isinstance(event.disclosed_at, bool)
                or not isfinite(event.disclosed_at) or event.disclosed_at <= 0):
            raise ValueError("valid disclosure timestamp required")
        event = replace(event, disclosed_at=float(event.disclosed_at))
        decision = evaluate_access(AccessRequest(
            actor_id=event.recipient_id, actor_role=event.recipient_role,
            learner_id=event.learner_id, target_learner_id=event.learner_id,
            data_class=event.data_class, purpose=event.purpose,
            assigned_learner_ids=(event.learner_id,), parent_authorized=True,
            covered_school_involved=event.ferpa_context,
            target_household_id=event.household_id,
        ))
        if not decision.allowed:
            raise PermissionError("; ".join(f.message for f in decision.findings))
        unauthorized = set(event.fields) - set(decision.permitted_fields)
        if unauthorized:
            raise PermissionError(
                "disclosure fields exceed the minimum-necessary role scope: "
                + ", ".join(sorted(unauthorized)))
        self._events[event.event_id] = event
        return event

    def for_learner(self, learner_id: str) -> tuple[DisclosureEvent, ...]:
        return tuple(e for e in self._events.values() if e.learner_id == learner_id)


def evaluate_access(request: AccessRequest) -> PrivacyDecision:
    findings: list[PrivacyFinding] = []
    permitted: tuple[str, ...] = ()

    if (not request.actor_id.strip() or not request.learner_id.strip()
            or not request.target_learner_id.strip()):
        findings.append(PrivacyFinding(
            "identity_required", "Actor and learner identities are required."))
    if not request.target_household_id.strip():
        findings.append(PrivacyFinding(
            "household_required", "The target household identity is required."))
    if request.actor_role not in VALID_ROLES:
        findings.append(PrivacyFinding("unknown_role", "The role is not authorized for household records."))
    if request.data_class not in VALID_DATA_CLASSES:
        findings.append(PrivacyFinding("unknown_data_class", "The record class is not registered."))
    if request.purpose not in VALID_PURPOSES:
        findings.append(PrivacyFinding("unknown_purpose", "The access purpose is not registered."))
    if request.purpose in PROHIBITED_PURPOSES:
        findings.append(PrivacyFinding(
            "prohibited_purpose",
            "Child or household data may not be used for advertising, model training, profiling, or public release.",
        ))
    if request.actor_role == "learner":
        if (not request.actor_household_id.strip()
                or request.actor_household_id != request.target_household_id):
            findings.append(PrivacyFinding(
                "household_scope", "The learner is not authenticated to the target household."))
        if request.actor_id != request.learner_id:
            findings.append(PrivacyFinding(
                "learner_identity_mismatch", "Learner identity does not match the acting account."))
        if request.learner_id != request.target_learner_id:
            findings.append(PrivacyFinding("sibling_isolation", "A learner cannot access a sibling's record."))
        if request.data_class in {"household_identity", "compliance", "health_disability", "financial", "values_preferences"}:
            findings.append(PrivacyFinding("learner_restricted_class", "This record class is restricted to authorized parents."))
    elif request.actor_role in {"parent", "co_parent", "system"}:
        if (not request.actor_household_id.strip()
                or request.actor_household_id != request.target_household_id):
            findings.append(PrivacyFinding(
                "household_scope", "The actor is not authenticated to the target household."))
        if request.target_learner_id not in request.assigned_learner_ids:
            findings.append(PrivacyFinding(
                "learner_scope", "The actor is not assigned to this learner."))
        if request.parent_authorized is not True:
            findings.append(PrivacyFinding(
                "parent_authorization", "Explicit household authorization is required."))
    elif request.actor_role in EXTERNAL_ROLES:
        if request.purpose not in EXTERNAL_ROLE_PURPOSES.get(request.actor_role, frozenset()):
            findings.append(PrivacyFinding(
                "collaborator_purpose",
                "The requested purpose is outside the collaborator role authorization.",
            ))
        if request.target_learner_id not in request.assigned_learner_ids:
            findings.append(PrivacyFinding("learner_scope", "The collaborator is not assigned to this learner."))
        if request.parent_authorized is not True:
            findings.append(PrivacyFinding("parent_authorization", "Parent authorization is required for collaborator access."))
        if request.actor_role in {"tutor", "co_op_instructor"}:
            if request.data_class not in {"learner_education", "portfolio"}:
                findings.append(PrivacyFinding("collaborator_minimum_necessary", "Tutors and co-op instructors receive only assigned education/portfolio data."))
            permitted = (("assigned_course", "assignment", "feedback")
                         if request.data_class == "learner_education"
                         else ("selected_work_sample",))
        elif request.actor_role == "evaluator":
            if request.data_class not in {"learner_education", "portfolio", "compliance"}:
                findings.append(PrivacyFinding("evaluator_scope", "Evaluators receive only the parent-selected evaluation packet."))
            permitted = {
                "learner_education": ("progress_summary", "assessment_context"),
                "portfolio": ("selected_work_sample",),
                "compliance": ("attendance_summary",),
            }.get(request.data_class, ())
        elif request.actor_role in {"umbrella_admin", "district_contact"}:
            if request.data_class not in {"compliance", "portfolio", "learner_education"}:
                findings.append(PrivacyFinding("oversight_scope", "Oversight receives only route-required education records."))
            permitted = {
                "compliance": ("required_filing_fields", "delivery_receipt"),
                "portfolio": ("parent_selected_evidence",),
                "learner_education": ("parent_selected_evidence",),
            }.get(request.data_class, ())
    elif request.actor_role != "parent" and request.actor_role in VALID_ROLES:
        findings.append(PrivacyFinding("unknown_role", "The role is not authorized for household records."))

    if request.data_class == "health_disability" and request.purpose not in {
            "parent_oversight", "education_delivery", "service_inquiry"}:
        findings.append(PrivacyFinding("health_minimum_necessary", "Health/disability records require a directly related purpose."))
    if request.data_class == "financial" and request.purpose not in {"parent_oversight", "funding_claim"}:
        findings.append(PrivacyFinding("financial_scope", "Financial records are restricted to parent oversight or a held funding claim."))
    if request.covered_school_involved:
        findings.append(PrivacyFinding(
            "ferpa_context", "A covered school is involved; apply FERPA/minimum-necessary rules in addition to household controls.",
            blocking=False,
        ))
    return PrivacyDecision(tuple(findings), permitted, send_held=request.actor_role in EXTERNAL_ROLES)


def check_collection(*, biometrics: bool = False, affective_computing: bool = False,
                     covert_attention: bool = False, psychological_profile: bool = False) -> PrivacyDecision:
    findings: list[PrivacyFinding] = []
    if biometrics:
        findings.append(PrivacyFinding("biometric_collection", "Biometric identification is prohibited in the homeschool pack."))
    if affective_computing:
        findings.append(PrivacyFinding("affective_computing", "Affective/emotion inference is prohibited."))
    if covert_attention:
        findings.append(PrivacyFinding("covert_attention", "Covert attention scoring is prohibited."))
    if psychological_profile:
        findings.append(PrivacyFinding("psychological_profile", "Psychological profiling is prohibited."))
    return PrivacyDecision(tuple(findings))


def export_fields(data_class: DataClass) -> tuple[str, ...]:
    """Minimum export schema; binary metadata is stripped by the export adapter."""
    return {
        "learner_education": ("course", "assignment", "grade", "feedback"),
        "portfolio": ("title", "subject", "created_date", "content_hash"),
        "compliance": ("filing_type", "status", "receipt_id", "source_version"),
        "child_ai_interactions": ("session_id", "started_at", "mode", "safety_events"),
    }.get(data_class, ())
