"""Evidence-backed homeschool compliance calendar, time ledger, and filing gate.

The module prepares parent work but has no transport.  A draft becomes
``ready_for_parent_send`` only after an accountable-parent attestation; it never
becomes "filed" until an external receipt is recorded.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from math import isfinite

from .homeschool_jurisdictions import (
    HomeschoolProfile,
    get_homeschool_profile,
    profile_for_route,
)
from .homeschool_route import RouteDecision, RouteSelection, evaluate_route
from .homeschool_validation import iso_date, valid_sha256


@dataclass(frozen=True)
class ComplianceTask:
    task_id: str
    title: str
    due_date: str
    required: bool
    external_action: bool
    authority: str
    status: str = "open"


@dataclass(frozen=True)
class ComplianceCalendar:
    state: str
    route: str
    school_year: str
    source_verified_on: str
    tasks: tuple[ComplianceTask, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstructionEntry:
    entry_id: str
    learner_id: str
    on_date: str
    subject: str
    hours: float
    evidence_ids: tuple[str, ...]
    parent_attested: bool


@dataclass(frozen=True)
class InstructionProgress:
    learner_id: str
    days: int
    hours: float
    subjects: tuple[str, ...]
    missing_subjects: tuple[str, ...]
    required_days: int
    required_hours: float
    days_remaining: int
    hours_remaining: float


class InstructionLedger:
    """Append-only in-process ledger; persistence adapters may store its records."""

    def __init__(self) -> None:
        self._entries: dict[str, InstructionEntry] = {}
        self._evidence_owners: dict[tuple[str, str], str] = {}

    def append(self, entry: InstructionEntry) -> InstructionEntry:
        canonical_date = iso_date(entry.on_date, "on_date").isoformat()
        entry = replace(
            entry,
            entry_id=entry.entry_id.strip(),
            learner_id=entry.learner_id.strip(),
            on_date=canonical_date,
            subject=entry.subject.strip().lower(),
            evidence_ids=tuple(item.strip() for item in entry.evidence_ids),
        )
        if not entry.entry_id or not entry.learner_id:
            raise ValueError("instruction entry and learner identities must be nonempty strings")
        if entry.entry_id in self._entries:
            raise ValueError("instruction entry IDs are immutable and unique")
        if isinstance(entry.hours, bool) or not isinstance(entry.hours, (int, float)):
            raise ValueError("hours must be a finite number")
        hours = float(entry.hours)
        if not isfinite(hours) or hours <= 0 or hours > 24:
            raise ValueError("hours must be finite and in (0, 24]")
        if not entry.subject:
            raise ValueError("subject must be nonempty")
        if (not entry.evidence_ids or any(not item for item in entry.evidence_ids)
                or len(set(entry.evidence_ids)) != len(entry.evidence_ids)):
            raise ValueError("instruction evidence IDs must be unique and nonempty")
        if entry.parent_attested is not True:
            raise ValueError("attendance is not recorded until a parent attests it")
        daily_hours = sum(
            existing.hours for existing in self._entries.values()
            if existing.learner_id == entry.learner_id and existing.on_date == entry.on_date
        )
        if daily_hours + hours > 24:
            raise ValueError("aggregate instruction hours exceed 24 for this learner and date")
        for evidence_id in entry.evidence_ids:
            if (entry.learner_id, evidence_id) in self._evidence_owners:
                raise ValueError("instruction evidence is already counted for this learner")
        saved = replace(entry, hours=hours)
        self._entries[saved.entry_id] = saved
        for evidence_id in saved.evidence_ids:
            self._evidence_owners[(saved.learner_id, evidence_id)] = saved.entry_id
        return saved

    def for_learner(self, learner_id: str) -> tuple[InstructionEntry, ...]:
        return tuple(e for e in self._entries.values() if e.learner_id == learner_id)

    def progress(self, learner_id: str, profile: HomeschoolProfile, *,
                 school_year_start: str, grade: int = 1) -> InstructionProgress:
        if not isinstance(grade, int) or isinstance(grade, bool) or not 0 <= grade <= 12:
            raise ValueError("grade must be an integer in [0, 12]")
        start = iso_date(school_year_start, "school_year_start")
        try:
            end = start.replace(year=start.year + 1)
        except ValueError:
            end = start.replace(year=start.year + 1, day=28)
        entries = tuple(
            entry for entry in self.for_learner(learner_id)
            if start <= iso_date(entry.on_date, "on_date") < end
        )
        days = len({e.on_date for e in entries})
        hours = round(sum(e.hours for e in entries), 4)
        subjects = tuple(sorted({e.subject for e in entries}))
        missing = tuple(s for s in profile.required_subjects if s not in subjects)
        required_hours = float(
            profile.instruction_hours_elementary if grade <= 6
            else profile.instruction_hours_secondary
        )
        if not required_hours and profile.instruction_days and profile.instruction_hours_per_day:
            required_hours = profile.instruction_days * profile.instruction_hours_per_day
        return InstructionProgress(
            learner_id, days, hours, subjects, missing, profile.instruction_days,
            required_hours, max(0, profile.instruction_days - days),
            round(max(0.0, required_hours - hours), 4),
        )


@dataclass(frozen=True)
class FilingDraft:
    filing_id: str
    state: str
    route: str
    filing_type: str
    content_hash: str
    required_fields_complete: bool
    source_verified_on: str
    status: str = "draft"
    parent_id: str = ""
    attested_at: float = 0.0
    receipt_id: str = ""
    sent_at: float = 0.0
    household_id: str = ""
    receipt_recorded_by: str = ""


class FilingLedger:
    """Draft/attest/receipt state machine with no send capability."""

    def __init__(self, *, household_id: str,
                 authorized_parent_ids: tuple[str, ...]) -> None:
        household = household_id.strip()
        parents = frozenset(item.strip() for item in authorized_parent_ids)
        if (not household or not parents or "" in parents
                or len(parents) != len(authorized_parent_ids)):
            raise ValueError("filing ledger requires one household and unique authorized parents")
        self._household_id = household
        self._authorized_parent_ids = parents
        self._filings: dict[str, FilingDraft] = {}

    def register(self, draft: FilingDraft, *, route_decision: RouteDecision) -> FilingDraft:
        canonical_decision = evaluate_route(route_decision.selection)
        if not route_decision.allowed or not canonical_decision.allowed:
            raise ValueError("filing requires a validated parent-confirmed route decision")
        selection = canonical_decision.selection
        profile = canonical_decision.profile
        assert profile is not None
        draft = replace(
            draft,
            filing_id=draft.filing_id.strip(),
            filing_type=draft.filing_type.strip(),
            household_id=draft.household_id.strip(),
        )
        if draft.filing_id in self._filings:
            raise ValueError("filing identity is immutable")
        if (not draft.filing_id.strip() or not draft.filing_type.strip()
                or not valid_sha256(draft.content_hash)):
            raise ValueError("filing identity, type, and canonical sha256 content hash are required")
        if (draft.state != selection.state or draft.route != selection.route
                or profile_for_route(draft.state, draft.route) is None):
            raise ValueError("filing state and route must match the validated route decision")
        if draft.household_id != self._household_id:
            raise PermissionError("filing belongs to another household")
        iso_date(draft.source_verified_on, "source_verified_on")
        if (profile.confidence != "primary_source"
                or draft.source_verified_on != profile.verified_on
                or selection.source_version != profile.verified_on):
            raise ValueError("filing requires the current primary-source route version")
        if (draft.status != "draft" or draft.parent_id or draft.attested_at != 0.0
                or draft.receipt_id or draft.sent_at != 0.0 or draft.receipt_recorded_by):
            raise ValueError("new filings must begin as an unapproved draft with no receipt state")
        self._filings[draft.filing_id] = draft
        return draft

    def attest(self, filing_id: str, *, parent_id: str, attested_at: float) -> FilingDraft:
        current = self._require(filing_id)
        if current.status != "draft":
            raise ValueError("only a draft can be attested")
        if current.required_fields_complete is not True:
            raise ValueError("required fields are incomplete")
        parent_id = parent_id.strip()
        if parent_id not in self._authorized_parent_ids:
            raise PermissionError("filing attestation requires an authorized parent")
        if (isinstance(attested_at, bool) or not isinstance(attested_at, (int, float))
                or not isfinite(attested_at) or attested_at <= 0):
            raise ValueError("valid parent identity and timestamp are required")
        updated = replace(current, status="ready_for_parent_send",
                          parent_id=parent_id, attested_at=float(attested_at))
        self._filings[filing_id] = updated
        return updated

    def record_receipt(self, filing_id: str, *, receipt_id: str, sent_at: float,
                       recorded_by_parent_id: str) -> FilingDraft:
        current = self._require(filing_id)
        if current.status != "ready_for_parent_send":
            raise ValueError("parent attestation is required before a receipt")
        actor = recorded_by_parent_id.strip()
        if actor not in self._authorized_parent_ids:
            raise PermissionError("receipt recording requires an authorized parent")
        if (not receipt_id.strip() or isinstance(sent_at, bool)
                or not isinstance(sent_at, (int, float))
                or not isfinite(sent_at) or sent_at < current.attested_at):
            raise ValueError("valid external receipt and send time are required")
        updated = replace(current, status="receipt_recorded",
                          receipt_id=receipt_id.strip(), sent_at=float(sent_at),
                          receipt_recorded_by=actor)
        self._filings[filing_id] = updated
        return updated

    def _require(self, filing_id: str) -> FilingDraft:
        try:
            return self._filings[filing_id]
        except KeyError as exc:
            raise KeyError("unknown filing") from exc

    def get(self, filing_id: str) -> FilingDraft:
        return self._require(filing_id)


def _iso(year: int, mm_dd: str) -> str:
    month, day = (int(x) for x in mm_dd.split("-"))
    return date(year, month, day).isoformat()


def build_compliance_calendar(selection: RouteSelection, *, school_year_start: str,
                              commencement: str,
                              learner_grades: tuple[int, ...] = (),
                              materials_received_on: str = "",
                              reporting_dates: tuple[str, ...] = (),
                              assessment_due_date: str = "") -> ComplianceCalendar:
    """Create a deterministic calendar after the parent's route passes the gate."""
    decision = evaluate_route(selection)
    decision.require_allowed()
    selection = decision.selection
    profile = profile_for_route(selection.state, selection.route)
    assert profile is not None
    start = date.fromisoformat(school_year_start)
    if not 1900 <= start.year < date.max.year:
        raise ValueError("school_year_start must permit a complete school-year calendar")
    try:
        next_school_year = start.replace(year=start.year + 1)
    except ValueError:
        # A leap-day school year closes on the final representable February day.
        next_school_year = date(start.year + 1, 2, 28)
    if commencement not in {"annual_continuation", "initial_start", "midyear_start"}:
        raise ValueError("commencement must be annual_continuation, initial_start, or midyear_start")
    materials_received = (date.fromisoformat(materials_received_on)
                          if materials_received_on else None)
    selected_reporting_dates = tuple(
        iso_date(value, "reporting_date") for value in reporting_dates
    )
    if selected_reporting_dates:
        if len(selected_reporting_dates) != profile.progress_reports_per_year:
            raise ValueError("reporting_dates must match the route's annual report count")
        if (len(set(selected_reporting_dates)) != len(selected_reporting_dates)
                or tuple(sorted(selected_reporting_dates)) != selected_reporting_dates
                or any(not start <= value < next_school_year
                       for value in selected_reporting_dates)):
            raise ValueError("reporting_dates must be unique, ordered, and inside the school year")
    selected_assessment_due = (
        iso_date(assessment_due_date, "assessment_due_date")
        if assessment_due_date else None
    )
    if (selected_assessment_due is not None
            and not start <= selected_assessment_due < next_school_year):
        raise ValueError("assessment_due_date must fall inside the school year")
    tasks: list[ComplianceTask] = []

    def add(code: str, title: str, due: date | str, *, external: bool = True,
            required: bool = True, authority: str | None = None) -> None:
        tasks.append(ComplianceTask(
            f"{profile.state.lower()}-{start.year}-{code}", title,
            due if isinstance(due, str) else due.isoformat(), required, external,
            authority or profile.source_citation,
        ))

    def add_planning_target(code: str, title: str) -> None:
        add(
            code, title, start, external=False, required=False,
            authority=(
                "Planning target only—not a statutory deadline. The accountable parent must "
                "select and verify the actual date against current route requirements."
            ),
        )

    if profile.approval_required:
        add("approval", "Obtain local approval before home instruction", start)
    if profile.state == "NY":
        if commencement == "annual_continuation":
            add("annual-notice", "Prepare annual notice/declaration",
                _iso(start.year, profile.annual_notice_date))
        else:
            add("initial-notice", "Prepare initial or midyear notice of intent",
                start + timedelta(days=profile.initial_notice_days))
    else:
        if commencement != "annual_continuation" and profile.initial_notice_days:
            add("initial-notice", "Prepare initial notice/declaration",
                start + timedelta(days=profile.initial_notice_days))
        if commencement != "annual_continuation" and profile.notice_days_before_start:
            add("initial-notice", "Submit parent-approved notice before instruction",
                start - timedelta(days=profile.notice_days_before_start))
        if commencement == "annual_continuation" and profile.annual_notice_date:
            add("annual-notice", "Prepare annual notice/declaration",
                _iso(start.year, profile.annual_notice_date))

    if profile.state == "TN" and selection.route == "independent_home_school":
        add("intent", "Submit parent-approved Intent to Home School before school year", start)
        add("attendance", "Submit parent-approved year-end attendance to director of schools",
            start + timedelta(days=364))
    elif profile.state == "TN" and selection.route == "church_related_school":
        add("umbrella-standing",
            "Confirm umbrella enrollment and school-of-record responsibilities",
            start, external=False)

    if profile.requirements_defined_by_oversight:
        add("oversight-requirements",
            "Confirm supervising organization's current records, assessment, and reporting requirements",
            start, external=False)
    if profile.state == "PA" and selection.route == "private_tutor":
        add("tutor-standing",
            "Confirm the private tutor filed current certification and required background record",
            start, external=False)

    if profile.state == "NY":
        if commencement == "annual_continuation":
            ihip_due = date(start.year, 8, 15)
            if materials_received is not None:
                ihip_due = max(ihip_due, materials_received + timedelta(days=28))
        else:
            if materials_received is None:
                raise ValueError(
                    "materials_received_on is required for an initial or midyear New York IHIP deadline")
            ihip_due = materials_received + timedelta(days=28)
        add("ihip", "Submit parent-approved IHIP", ihip_due)
        if selected_reporting_dates:
            for quarter, due in enumerate(selected_reporting_dates, start=1):
                add(f"quarter-{quarter}", f"Submit quarterly report {quarter}", due)
        else:
            for quarter in range(1, 5):
                add_planning_target(
                    f"quarter-plan-{quarter}",
                    f"Set parent-selected quarterly reporting date {quarter}",
                )
    elif profile.state == "MD" and selection.route == "local_supervision":
        if selected_reporting_dates:
            add("portfolio-1", "Prepare first-semester portfolio review",
                selected_reporting_dates[0])
            add("portfolio-2", "Prepare second-semester portfolio review",
                selected_reporting_dates[1])
        else:
            add_planning_target("portfolio-plan-1", "Set first portfolio-review date")
            add_planning_target("portfolio-plan-2", "Set second portfolio-review date")
    elif profile.progress_reports_per_year:
        if selected_reporting_dates:
            for number, due in enumerate(selected_reporting_dates, start=1):
                add(f"progress-{number}", f"Prepare progress report {number}", due,
                    external=profile.state in {"NY", "SC", "PA"})
        else:
            for number in range(1, profile.progress_reports_per_year + 1):
                add_planning_target(
                    f"progress-plan-{number}",
                    f"Set parent-selected progress reporting date {number}",
                )

    needs_assessment = profile.assessment_frequency_years == 1
    if profile.assessment_grades and learner_grades:
        needs_assessment = needs_assessment or any(g in profile.assessment_grades for g in learner_grades)
    if profile.state == "PA" and selection.route == "home_education":
        if selected_assessment_due is not None:
            add("annual-evaluator", "Complete annual qualified-evaluator review",
                selected_assessment_due)
        else:
            add_planning_target("annual-evaluator-plan", "Set parent-selected evaluator date")
        if any(g in profile.assessment_grades for g in learner_grades):
            if selected_assessment_due is not None:
                add("standardized-test", "Complete grade-triggered standardized testing",
                    selected_assessment_due)
            else:
                add_planning_target(
                    "standardized-test-plan",
                    "Set parent-selected grade-triggered testing date",
                )
    elif needs_assessment or (profile.assessment_grades and any(
            g in profile.assessment_grades for g in learner_grades)):
        if profile.assessment_submission_date:
            add(
                "assessment", "Complete required assessment/evaluator workflow",
                _iso(start.year + 1, profile.assessment_submission_date),
            )
        elif selected_assessment_due is not None:
            add(
                "assessment", "Complete required assessment/evaluator workflow",
                selected_assessment_due,
            )
        else:
            add_planning_target(
                "assessment-plan", "Set parent-selected assessment/evaluator date",
            )

    add("records-close", "Close annual records and freeze evidence archive",
        next_school_year, external=False)
    warnings = tuple(f.message for f in decision.findings if not f.blocking)
    return ComplianceCalendar(profile.state, selection.route, str(start.year),
                              profile.verified_on, tuple(sorted(tasks, key=lambda t: t.due_date)),
                              warnings)


def profile_for_calendar(state: str) -> HomeschoolProfile:
    profile = get_homeschool_profile(state)
    if profile is None:
        raise ValueError("unsupported state")
    return profile
