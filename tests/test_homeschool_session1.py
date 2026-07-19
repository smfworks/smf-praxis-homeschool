"""Homeschool Session 1: jurisdiction, route, compliance, and privacy."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from hybridagent.homeschool_compliance import (
    FilingDraft,
    FilingLedger,
    InstructionEntry,
    InstructionLedger,
    build_compliance_calendar,
)
from hybridagent.homeschool_jurisdictions import (
    get_homeschool_profile,
    profile_for_route,
    registered_homeschool_states,
)
from hybridagent.homeschool_route import (
    RouteSelection,
    evaluate_route,
    migrate_route,
)
from hybridagent.household_education_privacy import (
    AccessRequest,
    DisclosureEvent,
    HouseholdDisclosureLedger,
    check_collection,
    evaluate_access,
)

STATES = ("FL", "GA", "SC", "TN", "VA", "WV", "MD", "PA", "OH", "NJ", "NY", "CT", "MA")
NOW = datetime(2026, 8, 1).timestamp()
VALID_HASH = "sha256:" + ("a" * 64)


def sel(state: str, route: str | None = None, *,
        district_enrolled: bool = False, school_of_record: str = "parent",
        oversight_entity: str = "") -> RouteSelection:
    profile = get_homeschool_profile(state)
    assert profile is not None
    return RouteSelection(
        state, route or profile.default_route, True, "2026-08-01",
        district_enrolled=district_enrolled, school_of_record=school_of_record,
        oversight_entity=oversight_entity,
    )


def test_all_13_profiles_are_source_versioned():
    assert registered_homeschool_states() == STATES
    for state in STATES:
        profile = get_homeschool_profile(state)
        assert profile is not None
        assert profile.source_citation and profile.source_url
        assert profile.verified_on == "2026-07-18"
        assert profile.routes and profile.default_route in profile.routes


def test_cross_state_regulatory_divergence():
    ny = get_homeschool_profile("NY")
    nj = get_homeschool_profile("NJ")
    ga = get_homeschool_profile("GA")
    ma = get_homeschool_profile("MA")
    wv = get_homeschool_profile("WV")
    assert ny and nj and ga and ma and wv
    assert ny.progress_reports_per_year == 4 and ny.instruction_hours_secondary == 990
    assert nj.instruction_days == 0 and not nj.approval_required
    assert ga.instruction_days == 180 and ga.instruction_hours_per_day == 4.5
    assert ma.approval_required
    assert len(wv.routes) == 4 and "microschool" not in wv.routes
    assert wv.assessment_grades == (3, 5, 8, 11)


def test_unknown_state_is_not_inferred():
    assert get_homeschool_profile("CA") is None
    assert get_homeschool_profile(1) is None  # type: ignore[arg-type]


def test_parent_must_confirm_route():
    decision = evaluate_route(RouteSelection("FL", "independent_home_education", False, "2026-08-01"))
    assert not decision.allowed
    assert any(f.code == "parent_confirmation_required" for f in decision.findings)


def test_route_dates_and_identifiers_are_canonical_and_fail_closed():
    decision = evaluate_route(RouteSelection(
        "tn", " CHURCH_RELATED_SCHOOL ", True, "2026-08-01",
        oversight_entity=" Umbrella Academy ",
    ))
    assert decision.allowed
    assert decision.selection.state == "TN"
    assert decision.selection.route == "church_related_school"
    assert decision.selection.school_of_record == "church_related_school"
    assert decision.selection.oversight_entity == "Umbrella Academy"
    conflict = evaluate_route(RouteSelection(
        "TN", "church_related_school", True, "2026-08-01",
        school_of_record="public_school", oversight_entity="Umbrella Academy",
    ))
    assert not conflict.allowed
    assert conflict.selection.school_of_record == "public_school"
    invalid = evaluate_route(RouteSelection(
        "FL", "independent_home_education", True, "not-a-date",
    ))
    assert not invalid.allowed
    assert any(f.code == "effective_date_invalid" for f in invalid.findings)
    assert profile_for_route("FL", "invented") is None


def test_public_virtual_is_not_independent_homeschool():
    decision = evaluate_route(RouteSelection(
        "OH", "public_virtual", True, "2026-08-01",
        district_enrolled=True, school_of_record="public_school",
    ))
    assert not decision.allowed
    assert any(f.code == "public_school_not_homeschool" for f in decision.findings)


def test_microschool_administration_remains_outside_household_pack():
    decision = evaluate_route(RouteSelection("WV", "microschool", True, "2026-08-01"))
    assert not decision.allowed
    assert any(f.code == "separate_product_boundary" for f in decision.findings)


def test_sc_association_must_be_named():
    decision = evaluate_route(sel("SC", "option3_association"))
    assert not decision.allowed
    assert any(f.code == "association_required" for f in decision.findings)
    ok = evaluate_route(sel("SC", "option3_association", oversight_entity="Association 50"))
    assert ok.allowed


def test_tennessee_primary_source_is_verified():
    decision = evaluate_route(sel("TN"))
    assert decision.allowed
    assert not any(f.code == "primary_verification_required" for f in decision.findings)


def test_tennessee_routes_have_different_calendars_and_record_owners():
    independent = build_compliance_calendar(
        sel("TN", "independent_home_school"), school_year_start="2026-08-01",
        commencement="annual_continuation", learner_grades=(5,),
    )
    independent_titles = {task.title for task in independent.tasks}
    assert "Submit parent-approved Intent to Home School before school year" in independent_titles
    assert "Submit parent-approved year-end attendance to director of schools" in independent_titles
    assert any("assessment" in title.lower() for title in independent_titles)

    umbrella = build_compliance_calendar(
        sel("TN", "church_related_school", oversight_entity="Umbrella Academy"),
        school_year_start="2026-08-01", commencement="annual_continuation",
        learner_grades=(5,),
    )
    umbrella_titles = {task.title for task in umbrella.tasks}
    assert "Confirm umbrella enrollment and school-of-record responsibilities" in umbrella_titles
    assert any("supervising organization" in title for title in umbrella_titles)
    assert not any("Intent to Home School" in title for title in umbrella_titles)
    assert "Complete required assessment/evaluator workflow" not in umbrella_titles


def test_route_migration_freezes_previous_profile():
    previous = RouteSelection(
        "NJ", "equivalent_instruction_elsewhere", True, "2025-08-01",
        source_version="2025-06-30",
    )
    migration = migrate_route(previous, sel("PA"))
    assert migration.requires_new_notice
    assert migration.frozen_profile_verified_on == "2025-06-30"
    assert any("prior-year" in x for x in migration.checklist)
    with pytest.raises(ValueError, match="Route"):
        migrate_route(RouteSelection("NJ", "invented", True, "2025-08-01"), sel("PA"))


def test_wv_alternate_route_surfaces_primary_verification_warning():
    decision = evaluate_route(sel("WV", "learning_pod"))
    assert decision.allowed and decision.profile is not None
    assert decision.profile.requirements_defined_by_oversight
    assert any(f.code == "primary_verification_required" for f in decision.findings)


def test_ny_calendar_uses_parent_selected_quarterly_reporting_dates():
    reporting_dates = ("2026-10-31", "2027-01-31", "2027-04-30", "2027-07-31")
    calendar = build_compliance_calendar(
        sel("NY"), school_year_start="2026-08-01", learner_grades=(7,),
        commencement="annual_continuation", reporting_dates=reporting_dates,
    )
    titles = {t.title for t in calendar.tasks}
    assert "Prepare annual notice/declaration" in titles
    assert "Prepare initial or midyear notice of intent" not in titles
    assert "Submit parent-approved IHIP" in titles
    assert next(t for t in calendar.tasks if "IHIP" in t.title).due_date == "2026-08-15"
    quarterly = tuple(t for t in calendar.tasks if "quarterly report" in t.title)
    assert tuple(task.due_date for task in quarterly) == reporting_dates
    assert any("assessment" in title.lower() for title in titles)
    assert all(t.authority for t in calendar.tasks)


def test_calendar_labels_non_source_deadlines_as_planning_targets():
    calendar = build_compliance_calendar(
        sel("NY"), school_year_start="2026-08-01", learner_grades=(7,),
        commencement="annual_continuation",
    )
    assert not any("Submit quarterly report" in task.title for task in calendar.tasks)
    planning = tuple(task for task in calendar.tasks if "reporting date" in task.title)
    assert len(planning) == 4
    assert all(not task.required and not task.external_action for task in planning)
    assert all("not a statutory deadline" in task.authority for task in planning)


def test_ny_midyear_calendar_uses_event_driven_notice_and_ihip_dates():
    with pytest.raises(ValueError, match="materials_received_on"):
        build_compliance_calendar(
            sel("NY"), school_year_start="2027-01-10",
            commencement="midyear_start",
        )
    calendar = build_compliance_calendar(
        sel("NY"), school_year_start="2027-01-10",
        commencement="midyear_start", materials_received_on="2027-01-20",
    )
    tasks = {task.title: task for task in calendar.tasks}
    assert "Prepare annual notice/declaration" not in tasks
    assert tasks["Prepare initial or midyear notice of intent"].due_date == "2027-01-24"
    assert tasks["Submit parent-approved IHIP"].due_date == "2027-02-17"


def test_md_local_route_has_two_portfolio_reviews():
    calendar = build_compliance_calendar(
        sel("MD", "local_supervision"), school_year_start="2026-09-01",
        commencement="initial_start", reporting_dates=("2027-01-15", "2027-05-15"),
    )
    assert sum("portfolio review" in t.title for t in calendar.tasks) == 2
    notice = next(t for t in calendar.tasks if "notice before instruction" in t.title)
    assert notice.due_date == "2026-08-17"


def test_umbrella_and_private_tutor_calendars_do_not_leak_independent_duties():
    florida = build_compliance_calendar(
        sel("FL", "private_school_umbrella", oversight_entity="Umbrella School"),
        school_year_start="2026-08-01", commencement="annual_continuation",
    )
    florida_titles = {task.title for task in florida.tasks}
    assert "Prepare initial notice/declaration" not in florida_titles
    assert any("supervising organization" in title for title in florida_titles)

    pennsylvania = build_compliance_calendar(
        sel("PA", "private_tutor", oversight_entity="Certified Tutor"),
        school_year_start="2026-08-01", commencement="annual_continuation",
        learner_grades=(5,),
    )
    pa_titles = {task.title for task in pennsylvania.tasks}
    assert "Prepare annual notice/declaration" not in pa_titles
    assert "Complete required assessment/evaluator workflow" not in pa_titles
    assert any("private tutor filed" in title for title in pa_titles)


def test_pa_home_education_uses_parent_selected_evaluator_and_test_date():
    annual = build_compliance_calendar(
        sel("PA", "home_education"), school_year_start="2026-08-01",
        commencement="annual_continuation", learner_grades=(4,),
        assessment_due_date="2027-06-15",
    )
    evaluator = next(
        task for task in annual.tasks
        if task.title == "Complete annual qualified-evaluator review"
    )
    assert evaluator.due_date == "2027-06-15"
    assert "Complete grade-triggered standardized testing" not in {
        task.title for task in annual.tasks
    }
    tested = build_compliance_calendar(
        sel("PA", "home_education"), school_year_start="2026-08-01",
        commencement="annual_continuation", learner_grades=(5,),
        assessment_due_date="2027-06-15",
    )
    testing = next(
        task for task in tested.tasks
        if task.title == "Complete grade-triggered standardized testing"
    )
    assert testing.due_date == "2027-06-15"
    planning = build_compliance_calendar(
        sel("PA", "home_education"), school_year_start="2026-08-01",
        commencement="annual_continuation", learner_grades=(5,),
    )
    assert not any(
        task.title == "Complete annual qualified-evaluator review" and task.required
        for task in planning.tasks
    )
    assert any("evaluator date" in task.title.lower() for task in planning.tasks)



def test_sc_option1_calendar_includes_annual_statewide_assessment_workflow():
    calendar = build_compliance_calendar(
        sel("SC", "option1_district"), school_year_start="2026-08-01",
        commencement="annual_continuation", learner_grades=(4,),
    )
    assert any("assessment/evaluator" in task.title for task in calendar.tasks)


def test_instruction_ledger_requires_evidence_and_attestation():
    ledger = InstructionLedger()
    with pytest.raises(ValueError, match="evidence"):
        ledger.append(InstructionEntry(
            "e1", "l1", "2026-08-01", "mathematics", 2.0, (), True,
        ))
    with pytest.raises(ValueError, match="attests"):
        ledger.append(InstructionEntry(
            "e1", "l1", "2026-08-01", "mathematics", 2.0,
            ("work-1",), False,
        ))


def test_instruction_ledger_rejects_bool_nonfinite_and_duplicate():
    ledger = InstructionLedger()
    with pytest.raises(ValueError):
        ledger.append(InstructionEntry("bad", "l1", "2026-08-01", "math", True,
                                       ("a",), True))
    with pytest.raises(ValueError):
        ledger.append(InstructionEntry("bad2", "l1", "2026-08-01", "math", float("nan"),
                                       ("a",), True))
    entry = InstructionEntry("e1", "l1", "2026-08-01", "mathematics", 2.0,
                             ("a",), True)
    ledger.append(entry)
    with pytest.raises(ValueError, match="immutable"):
        ledger.append(entry)


def test_instruction_ledger_canonicalizes_identifiers_and_rejects_alias_replay():
    ledger = InstructionLedger()
    with pytest.raises(ValueError, match="identities"):
        ledger.append(InstructionEntry(
            " ", "l1", "2026-08-01", "math", 1, ("work",), True,
        ))
    with pytest.raises(ValueError, match="subject"):
        ledger.append(InstructionEntry(
            "e0", "l1", "2026-08-01", " ", 1, ("work",), True,
        ))
    with pytest.raises(ValueError, match="unique"):
        ledger.append(InstructionEntry(
            "e1", "l1", "2026-08-01", "math", 1, ("work", "work"), True,
        ))
    ledger.append(InstructionEntry(
        "e2", "l1", "2026-08-01", "math", 1, (" work ",), True,
    ))
    with pytest.raises(ValueError, match="already counted"):
        ledger.append(InstructionEntry(
            "e3", "l1", "2026-08-02", "science", 1, ("work",), True,
        ))


def test_instruction_progress_rejects_non_integer_grade():
    ledger = InstructionLedger()
    profile = get_homeschool_profile("PA")
    assert profile is not None
    with pytest.raises(ValueError, match="grade"):
        ledger.progress("l1", profile, school_year_start="2026-08-01", grade=float("nan"))


def test_instruction_ledger_rejects_daily_overcount_and_evidence_reuse():
    ledger = InstructionLedger()
    ledger.append(InstructionEntry(
        "e1", "l1", "2026-08-01", "mathematics", 20, ("work-1",), True,
    ))
    with pytest.raises(ValueError, match="exceed 24"):
        ledger.append(InstructionEntry(
            "e2", "l1", "2026-08-01", "science", 5, ("work-2",), True,
        ))
    with pytest.raises(ValueError, match="already counted"):
        ledger.append(InstructionEntry(
            "e3", "l1", "2026-08-02", "science", 1, ("work-1",), True,
        ))


def test_instruction_ledger_canonicalizes_semantic_date_aliases():
    ledger = InstructionLedger()
    saved = ledger.append(InstructionEntry(
        "e1", "l1", "20260801", "mathematics", 20, ("work-1",), True,
    ))
    assert saved.on_date == "2026-08-01"
    with pytest.raises(ValueError, match="exceed 24"):
        ledger.append(InstructionEntry(
            "e2", "l1", "2026-08-01", "science", 5, ("work-2",), True,
        ))
    profile = get_homeschool_profile("GA")
    assert profile is not None
    progress = ledger.progress("l1", profile, school_year_start="2026-08-01")
    assert progress.days == 1 and progress.hours == 20


def test_instruction_progress_never_fabricates_days():
    ledger = InstructionLedger()
    ledger.append(InstructionEntry("old", "l1", "2025-08-01", "science", 8,
                                   ("old-work",), True))
    ledger.append(InstructionEntry("e1", "l1", "2026-08-01", "mathematics", 2,
                                   ("work-1",), True))
    ledger.append(InstructionEntry("e2", "l1", "2026-08-01", "reading", 1,
                                   ("work-2",), True))
    profile = get_homeschool_profile("GA")
    assert profile is not None
    progress = ledger.progress("l1", profile, school_year_start="2026-08-01", grade=4)
    assert progress.days == 1 and progress.hours == 3
    assert progress.days_remaining == 179
    assert "science" in progress.missing_subjects


def test_filing_requires_authorized_household_parent_attestation_then_receipt():
    route_decision = evaluate_route(sel("FL", "independent_home_education"))
    ledger = FilingLedger(household_id="h1", authorized_parent_ids=("p1",))
    ledger.register(FilingDraft(
        "f1", "FL", "independent_home_education", "notice",
        VALID_HASH, True, "2026-07-18", household_id="h1",
    ), route_decision=route_decision)
    with pytest.raises(PermissionError, match="authorized parent"):
        ledger.attest("f1", parent_id="arbitrary-unverified-actor", attested_at=NOW)
    with pytest.raises(ValueError, match="attestation"):
        ledger.record_receipt(
            "f1", receipt_id="mail-1", sent_at=NOW,
            recorded_by_parent_id="p1",
        )
    ready = ledger.attest("f1", parent_id="p1", attested_at=NOW)
    assert ready.status == "ready_for_parent_send"
    with pytest.raises(PermissionError, match="authorized parent"):
        ledger.record_receipt(
            "f1", receipt_id="mail-1", sent_at=NOW + 1,
            recorded_by_parent_id="other",
        )
    recorded = ledger.record_receipt(
        "f1", receipt_id="mail-1", sent_at=NOW + 1,
        recorded_by_parent_id="p1",
    )
    assert recorded.status == "receipt_recorded"
    assert recorded.receipt_recorded_by == "p1"


def test_filing_rejects_noncanonical_hash_invalid_source_and_route_mismatch():
    decision = evaluate_route(sel("FL", "independent_home_education"))
    ledger = FilingLedger(household_id="h1", authorized_parent_ids=("p1",))
    with pytest.raises(ValueError, match="sha256"):
        ledger.register(FilingDraft(
            "f1", "FL", "independent_home_education", "notice",
            "sha256:short", True, "2026-07-18", household_id="h1",
        ), route_decision=decision)
    with pytest.raises(ValueError, match="ISO date"):
        ledger.register(FilingDraft(
            "f2", "FL", "independent_home_education", "notice",
            VALID_HASH, True, "not-a-date", household_id="h1",
        ), route_decision=decision)
    with pytest.raises(ValueError, match="unapproved draft"):
        ledger.register(FilingDraft(
            "f3", "FL", "independent_home_education", "notice", VALID_HASH, True,
            "2026-07-18", status="receipt_recorded", parent_id="p1",
            attested_at=NOW, receipt_id="fabricated", sent_at=NOW,
            household_id="h1", receipt_recorded_by="p1",
        ), route_decision=decision)
    with pytest.raises(ValueError, match="parent-confirmed route"):
        ledger.register(FilingDraft(
            "f4", "FL", "independent_home_education", "notice", VALID_HASH, True,
            "2026-07-18", household_id="h1",
        ), route_decision=evaluate_route(replace(sel("FL"), confirmed_by_parent=False)))
    with pytest.raises(ValueError, match="match the validated route"):
        ledger.register(FilingDraft(
            "f5", "GA", "home_study", "notice", VALID_HASH, True,
            "2026-07-18", household_id="h1",
        ), route_decision=decision)


def test_prohibited_child_data_purposes_blocked():
    for purpose in ("advertising", "model_training", "profiling", "public_release"):
        decision = evaluate_access(AccessRequest(
            "vendor", "tutor", "l1", "l1", "learner_education", purpose,
            assigned_learner_ids=("l1",), parent_authorized=True,
            target_household_id="h1",
        ))
        assert not decision.allowed


def test_sibling_and_restricted_record_isolation():
    decision = evaluate_access(AccessRequest(
        "l1", "learner", "l1", "l2", "health_disability", "parent_oversight",
        target_household_id="h1",
    ))
    codes = {f.code for f in decision.findings}
    assert {"sibling_isolation", "learner_restricted_class"} <= codes


def test_learner_access_is_bound_to_authenticated_household():
    decision = evaluate_access(AccessRequest(
        "l1", "learner", "l1", "l1", "learner_education", "education_delivery",
        actor_household_id="h1", target_household_id="h2",
    ))
    assert not decision.allowed
    assert any(f.code == "household_scope" for f in decision.findings)


@pytest.mark.parametrize(("role", "data_class", "purpose"), (
    ("tutor", "learner_education", "funding_claim"),
    ("evaluator", "portfolio", "service_inquiry"),
    ("district_contact", "learner_education", "education_delivery"),
))
def test_external_roles_are_bound_to_fail_closed_purpose_allowlists(
        role: str, data_class: str, purpose: str):
    decision = evaluate_access(AccessRequest(
        role, role, "l1", "l1", data_class, purpose,  # type: ignore[arg-type]
        assigned_learner_ids=("l1",), parent_authorized=True,
        target_household_id="h1",
    ))
    assert not decision.allowed
    assert any(f.code == "collaborator_purpose" for f in decision.findings)


def test_initial_notice_is_not_reissued_for_annual_continuation():
    annual = build_compliance_calendar(
        sel("FL", "independent_home_education"), school_year_start="2026-08-01",
        commencement="annual_continuation",
    )
    assert "Prepare initial notice/declaration" not in {task.title for task in annual.tasks}
    initial = build_compliance_calendar(
        sel("FL", "independent_home_education"), school_year_start="2026-08-01",
        commencement="initial_start",
    )
    assert "Prepare initial notice/declaration" in {task.title for task in initial.tasks}


def test_calendar_requires_explicit_commencement_and_school_year_date_bounds():
    selection = sel("FL", "independent_home_education")
    with pytest.raises(TypeError):
        build_compliance_calendar(selection, school_year_start="2026-08-01")

    ny = sel("NY", "home_instruction")
    with pytest.raises(ValueError, match="inside the school year"):
        build_compliance_calendar(
            ny,
            school_year_start="2026-08-01",
            commencement="annual_continuation",
            reporting_dates=("2026-10-31", "2027-01-31", "2027-04-30", "2027-08-01"),
        )
    with pytest.raises(ValueError, match="inside the school year"):
        build_compliance_calendar(
            selection,
            school_year_start="2026-08-01",
            commencement="annual_continuation",
            assessment_due_date="2027-08-01",
        )
    calendar = build_compliance_calendar(
        selection,
        school_year_start="2026-08-01",
        commencement="annual_continuation",
    )
    records_close = next(task for task in calendar.tasks if task.task_id.endswith("records-close"))
    assert records_close.due_date == "2027-08-01"
    leap_calendar = build_compliance_calendar(
        selection,
        school_year_start="2028-02-29",
        commencement="annual_continuation",
    )
    leap_close = next(
        task for task in leap_calendar.tasks if task.task_id.endswith("records-close")
    )
    assert leap_close.due_date == "2029-02-28"


def test_tutor_is_course_scoped_not_financial():
    education = evaluate_access(AccessRequest(
        "t1", "tutor", "l1", "l1", "learner_education", "education_delivery",
        assigned_learner_ids=("l1",), parent_authorized=True,
        target_household_id="h1",
    ))
    assert education.allowed and education.send_held
    financial = evaluate_access(AccessRequest(
        "t1", "tutor", "l1", "l1", "financial", "funding_claim",
        assigned_learner_ids=("l1",), parent_authorized=True,
        target_household_id="h1",
    ))
    assert not financial.allowed


def test_system_and_co_parent_require_explicit_household_scope():
    for role in ("system", "co_parent"):
        blocked = evaluate_access(AccessRequest(
            role, role, "l1", "l1", "learner_education", "parent_oversight",
            target_household_id="h1",
        ))
        assert not blocked.allowed
        allowed = evaluate_access(AccessRequest(
            role, role, "l1", "l1", "learner_education", "parent_oversight",
            assigned_learner_ids=("l1",), parent_authorized=True,
            actor_household_id="h1", target_household_id="h1",
        ))
        assert allowed.allowed


def test_parent_access_is_bound_to_authenticated_household_and_learner():
    cross_household = evaluate_access(AccessRequest(
        "p1", "parent", "l1", "l1", "health_disability", "parent_oversight",
        assigned_learner_ids=("l1",), parent_authorized=True,
        actor_household_id="h1", target_household_id="h2",
    ))
    assert not cross_household.allowed
    wrong_learner = evaluate_access(AccessRequest(
        "p1", "parent", "l1", "l2", "learner_education", "parent_oversight",
        assigned_learner_ids=("l1",), parent_authorized=True,
        actor_household_id="h1", target_household_id="h1",
    ))
    assert not wrong_learner.allowed
    allowed = evaluate_access(AccessRequest(
        "p1", "parent", "l1", "l1", "health_disability", "parent_oversight",
        assigned_learner_ids=("l1",), parent_authorized=True,
        actor_household_id="h1", target_household_id="h1",
    ))
    assert allowed.allowed


def test_disclosure_requires_parent_and_is_append_only():
    ledger = HouseholdDisclosureLedger(
        household_id="h1", authorized_parent_ids=("p1",), learner_ids=("l1",),
    )
    event = DisclosureEvent(
        "d1", "l1", "eval1", "evaluator", "portfolio", "evaluation",
        ("selected_work_sample",), "p1", NOW, household_id="h1",
    )
    ledger.record(event)
    with pytest.raises(ValueError, match="append-only"):
        ledger.record(event)
    assert ledger.for_learner("l1") == (event,)
    for index, invalid_time in enumerate((True, False, "1", float("nan"),
                                          float("inf"), float("-inf"))):
        with pytest.raises(ValueError, match="timestamp"):
            ledger.record(replace(
                event, event_id=f"bad-time-{index}", disclosed_at=invalid_time,
            ))
    with pytest.raises(PermissionError, match="minimum-necessary"):
        ledger.record(DisclosureEvent(
            "d2", "l1", "eval1", "evaluator", "portfolio", "evaluation",
            ("selected_work_sample", "home_address"), "p1", NOW,
            household_id="h1",
        ))
    with pytest.raises(PermissionError, match="minimum-necessary"):
        ledger.record(DisclosureEvent(
            "d3", "l1", "eval1", "evaluator", "portfolio", "evaluation",
            ("attendance_summary",), "p1", NOW, household_id="h1",
        ))
    with pytest.raises(PermissionError, match="household authorization"):
        ledger.record(DisclosureEvent(
            "d4", "l1", "eval1", "evaluator", "portfolio", "evaluation",
            ("selected_work_sample",), "other-parent", NOW, household_id="h1",
        ))


def test_prohibited_surveillance_collection():
    assert not check_collection(biometrics=True).allowed
    assert not check_collection(affective_computing=True).allowed
    assert not check_collection(covert_attention=True).allowed
    assert not check_collection(psychological_profile=True).allowed
