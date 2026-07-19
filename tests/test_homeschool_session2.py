"""Homeschool Session 2: learning, tutor, portfolio, assessment, support."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime

import pytest

from hybridagent.home_tutor import (
    AuthorshipCheck,
    AuthorshipLedger,
    TutorRequest,
    assess_tutor_request,
    check_authorship,
    safety_escalation,
)
from hybridagent.homeschool_assessment import (
    AssessmentPlan,
    AssessmentResult,
    AssessmentResultLedger,
    EvaluatorRoomLedger,
    ParentAssessmentAttestation,
    ParentAssessmentResultAttestation,
    accepted_methods,
    assessment_attestation_hash,
    assessment_plan_hash,
    assessment_result_attestation_hash,
    assessment_result_manifest_hash,
    evaluate_assessment,
    import_result,
)
from hybridagent.homeschool_jurisdictions import get_homeschool_profile
from hybridagent.homeschool_learning_plan import (
    LearnerPlan,
    LearningActivity,
    build_learning_program,
    differentiate_objective,
)
from hybridagent.homeschool_portfolio import (
    ParentArtifactAttestation,
    PortfolioArtifact,
    PortfolioLedger,
    artifact_attestation_hash,
    portfolio_artifact_manifest_hash,
)
from hybridagent.homeschool_support import (
    HomeschoolSupportPlan,
    ParentSupportAttestation,
    ReentryEvidenceLedger,
    ReentryEvidenceRecord,
    ReentryPacket,
    ServiceInquiryDraft,
    SupportEvidence,
    SupportEvidenceLedger,
    SupportStrategy,
    evaluate_service_inquiry,
    release_service_inquiry,
    support_attestation_hash,
    support_plan_hash,
    validate_reentry_packet,
    validate_support_plan,
)

NOW = 1_785_000_000.0
SCHEDULED = datetime(2026, 10, 1, 12).timestamp()
RECEIVED = datetime(2026, 10, 2, 12).timestamp()
IMPORTED = datetime(2026, 10, 3, 12).timestamp()
VALID_HASH = "sha256:" + ("a" * 64)
VALID_HASH_B = "sha256:" + ("b" * 64)
REPORT_CONTENT = b"assessment-report"
RESULT_HASH = "sha256:" + hashlib.sha256(REPORT_CONTENT).hexdigest()


def attestation(plan: AssessmentPlan) -> ParentAssessmentAttestation:
    profile = get_homeschool_profile(plan.state)
    assert profile is not None
    record = ParentAssessmentAttestation(
        "att1", "parent1", plan.learner_id, plan.state, plan.route, plan.method,
        profile.verified_on, SCHEDULED - 60, assessment_plan_hash(plan), "",
    )
    return replace(record, attestation_hash=assessment_attestation_hash(record))


def artifact(identifier: str, learner_id: str, created_date: str, title: str,
             subjects: tuple[str, ...], artifact_type: str, author: str,
             hours: float = 0.0, metadata: tuple[tuple[str, str], ...] = (),
             *, content: bytes | None = None,
             parent_attested: bool = True) -> tuple[PortfolioArtifact, bytes]:
    body = content if content is not None else f"evidence:{identifier}".encode()
    content_hash = "sha256:" + hashlib.sha256(body).hexdigest()
    base = PortfolioArtifact(
        identifier, learner_id, created_date, title, subjects, artifact_type,
        content_hash, author, hours, metadata, parent_attested, None,
    )
    att = ParentArtifactAttestation(
        f"att-{identifier}", "parent1", learner_id, identifier,
        content_hash, created_date, portfolio_artifact_manifest_hash(base), "",
    )
    att = replace(att, attestation_hash=artifact_attestation_hash(att))
    return replace(base, parent_attestation=att), body


def assessment_plan(*, state: str, route: str, grade: int, method: str,
                    assessment_id: str = "as1", learner_id: str = "l1",
                    administrator_id: str = "tester",
                    qualification: str = "qualified",
                    scheduled_at: float = SCHEDULED) -> AssessmentPlan:
    base = AssessmentPlan(
        assessment_id, learner_id, state, route, grade, "2026-2027", method,
        administrator_id, qualification, True, scheduled_at, True,
        "2026-08-01", "2027-07-31", None,
    )
    return replace(base, parent_attestation=attestation(base))


def assessment_result(plan: AssessmentPlan, *, assessment_id: str | None = None,
                      result_hash: str = RESULT_HASH, received_at: float = RECEIVED,
                      source: str = "publisher_report") -> AssessmentResult:
    base = AssessmentResult(
        assessment_id or plan.assessment_id, plan.learner_id, plan.school_year,
        result_hash, received_at, source, True,
    )
    manifest_hash = assessment_result_manifest_hash(base)
    result_attestation = ParentAssessmentResultAttestation(
        "result-att", "parent1", base.assessment_id, base.learner_id,
        base.school_year, manifest_hash, RECEIVED + 1, "",
    )
    result_attestation = replace(
        result_attestation,
        attestation_hash=assessment_result_attestation_hash(result_attestation),
    )
    return replace(
        base, result_manifest_hash=manifest_hash, parent_attestation=result_attestation,
    )


def learners() -> tuple[LearnerPlan, ...]:
    return (
        LearnerPlan("l1", 3, 8, ("fluency",)),
        LearnerPlan("l2", 7, 12, ("algebra readiness",)),
    )


def activity(identifier: str, subjects: tuple[str, ...], *, shared: bool = True,
             min_grade: int = 1, max_grade: int = 12) -> LearningActivity:
    return LearningActivity(identifier, identifier, subjects, ("explain concept",),
                            ("work_sample",), 45, min_grade, max_grade, shared)


def test_multi_grade_shared_schedule_and_subject_gaps():
    program = build_learning_program(
        state="GA", learners=learners(),
        activities=(activity("history", ("social_studies",)),
                    activity("math", ("mathematics",), shared=False)),
    )
    assert any(len(x.learner_ids) == 2 and x.differentiated for x in program.schedule)
    assert "science" in program.missing_required_subjects
    assert any("180 actual days" in x for x in program.warnings)


def test_subject_coverage_is_computed_for_each_learner():
    profile = get_homeschool_profile("GA")
    assert profile is not None
    program = build_learning_program(
        state="GA", learners=learners(),
        activities=(activity(
            "young-only", profile.required_subjects, min_grade=1, max_grade=3,
        ),),
    )
    gaps = dict(program.missing_required_subjects_by_learner)
    assert not gaps["l1"] and gaps["l2"] == profile.required_subjects


def test_learning_plan_rejects_empty_evidence():
    bad = LearningActivity("a", "A", ("science",), ("observe",), (), 30)
    with pytest.raises(ValueError, match="evidence"):
        build_learning_program(state="GA", learners=learners(), activities=(bad,))


def test_learning_plan_rejects_duplicate_ids_blank_subjects_and_daily_overcommit():
    duplicate = activity("same", ("science",), shared=False)
    with pytest.raises(ValueError, match="activity IDs"):
        build_learning_program(
            state="GA", learners=learners(), activities=(duplicate, duplicate),
        )
    with pytest.raises(ValueError, match="subjects"):
        build_learning_program(
            state="GA", learners=learners(), activities=(activity("blank", (" ",)),),
        )
    first = replace(activity("one", ("science",), shared=False), minutes=300)
    second = replace(activity("two", ("mathematics",), shared=False), minutes=300)
    with pytest.raises(ValueError, match="480 minutes"):
        build_learning_program(
            state="GA", learners=learners(), activities=(first, second), days=("Monday",),
        )


def test_massachusetts_plan_warns_not_approval():
    program = build_learning_program(state="MA", learners=learners(),
                                     activities=(activity("reading", ("reading",)),))
    assert any("not approval" in x for x in program.warnings)


def test_objective_differentiation_is_transparent():
    result = differentiate_objective("Compare primary sources", learners())
    assert result["l1"].startswith("Grade 3")
    assert result["l2"].startswith("Grade 7")


def test_tutor_blocks_complete_summative_answers():
    decision = assess_tutor_request(TutorRequest(
        "s1", "l1", 12, "summative", "Give me the final answer",
        asks_for_complete_answer=True,
    ))
    assert not decision.allowed
    assert decision.strategy == "refuse_final_answer_offer_conceptual_hint"


def test_tutor_rejects_invalid_mode_and_boolean_age_bypasses():
    with pytest.raises(ValueError, match="mode"):
        assess_tutor_request(TutorRequest(
            "s1", "l1", 12, "ungraded",  # type: ignore[arg-type]
            "Give final answer", asks_for_complete_answer=True,
        ))
    with pytest.raises(ValueError, match="age"):
        assess_tutor_request(TutorRequest(
            "s1", "l1", True, "practice", "Help",
        ))


def test_tutor_uses_parallel_example_for_formative_request():
    decision = assess_tutor_request(TutorRequest(
        "s1", "l1", 10, "formative", "Help with fractions",
        asks_for_complete_answer=True,
    ))
    assert decision.allowed
    assert decision.strategy == "worked_analogy_then_learner_attempt"


def test_child_external_contact_purchase_and_public_post_blocked():
    decision = assess_tutor_request(TutorRequest(
        "s1", "l1", 11, "practice", "Post this and buy a course",
        external_contact_requested=True, purchase_requested=True,
        public_post_requested=True,
    ))
    assert not decision.allowed and len(decision.findings) >= 3


def test_parent_visibility_required():
    decision = assess_tutor_request(TutorRequest(
        "s1", "l1", 15, "practice", "Private session", parent_visible=False,
    ))
    assert not decision.allowed


@pytest.mark.parametrize("prompt", (
    "I want to kill myself tonight",
    "My uncle kicked me",
    "I will shoot my teacher",
))
def test_tutor_primary_path_pauses_on_direct_danger(prompt: str):
    decision = assess_tutor_request(TutorRequest(
        "s-danger", "l1", 12, "practice", prompt,
    ))
    assert not decision.allowed
    assert decision.strategy == "pause_for_immediate_human_help"
    assert any("Pause tutoring" in finding for finding in decision.findings)


def test_authorship_not_replaced_and_detector_not_verdict():
    body = b"learner draft"
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    ledger = AuthorshipLedger()
    ledger.register(
        learner_id="l1", session_id="s1", submission_id="sub1", draft_content=body,
    )
    decision = check_authorship(AuthorshipCheck(
        learner_draft_present=False, sources_cited=False,
        detector_only_claim=True, ai_rewrote_submission=True,
        learner_id="l1", session_id="s1", submission_id="sub1",
        draft_hash=digest,
    ), draft_content=body, authorship_ledger=ledger)
    assert not decision.allowed
    assert any("Detector" in x for x in decision.findings)
    assert not check_authorship(AuthorshipCheck(
        learner_draft_present=True, sources_cited=False,
        learner_id="l1", session_id="s1", submission_id="sub1",
        draft_hash=digest,
    ), draft_content=body, authorship_ledger=ledger).allowed
    bound = check_authorship(AuthorshipCheck(
        learner_draft_present=True, sources_cited=True,
        learner_id="l1", session_id="s1", submission_id="sub1",
        draft_hash=digest, ai_edit_provenance="coaching",
    ), draft_content=body, authorship_ledger=ledger)
    assert bound.allowed and bound.submission_id == "sub1" and bound.draft_hash == digest
    assert not check_authorship(AuthorshipCheck(
        learner_draft_present=True, sources_cited=True,
    ), draft_content=body, authorship_ledger=ledger).allowed


def test_authorship_recomputes_hash_from_supplied_draft_bytes():
    body = b"learner-authored draft"
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    check = AuthorshipCheck(
        learner_draft_present=True, sources_cited=True,
        learner_id="l1", session_id="s1", submission_id="sub1",
        draft_hash=digest,
    )
    ledger = AuthorshipLedger()
    ledger.register(
        learner_id="l1", session_id="s1", submission_id="sub1", draft_content=body,
    )
    assert check_authorship(check, draft_content=body, authorship_ledger=ledger).allowed
    assert not check_authorship(
        check, draft_content=b"AI-replaced draft", authorship_ledger=ledger,
    ).allowed
    for relabeled in (
        replace(check, learner_id="other"),
        replace(check, session_id="other"),
        replace(check, submission_id="other"),
    ):
        assert not check_authorship(
            relabeled, draft_content=body, authorship_ledger=ledger,
        ).allowed


def test_safety_escalation_reminds_never_files():
    triggered, message = safety_escalation("I feel unsafe at home")
    assert triggered and "file a report" in message
    triggered, message = safety_escalation("I want to kill myself tonight")
    assert triggered and "emergency services" in message
    triggered, message = safety_escalation("My parent touched me inappropriately")
    assert triggered and "outside the potentially involved" in message


@pytest.mark.parametrize("text", (
    "I want to die", "I am cutting myself", "I am cutting my wrists",
    "My dad hit me", "My stepdad hit me", "My mom slapped me",
    "My foster father kicked me", "My uncle kicked me",
    "My dad says he will kill me", "She threatened to kill me",
    "Someone at home is hitting me",
    "My parent is touching me inappropriately",
    "I was touched inappropriately", "I will shoot my teacher",
))
def test_safety_escalation_covers_common_direct_disclosures(text: str):
    triggered, message = safety_escalation(text)
    assert triggered and message
    if "parent" in text.lower() or "dad" in text.lower():
        assert "outside the potentially involved" in message


def test_mixed_danger_and_household_abuse_routes_outside_household():
    prompt = "My dad hit me and I want to die"
    triggered, message = safety_escalation(prompt)
    assert triggered and "outside the potentially involved household member" in message
    decision = assess_tutor_request(TutorRequest("s1", "l1", 15, "practice", prompt))
    assert not decision.allowed
    assert decision.strategy == "pause_for_immediate_human_help"
    assert "outside the potentially involved household member" in decision.findings[0]


def test_portfolio_is_append_only_parent_attested_and_hashed():
    ledger = PortfolioLedger(today=date(2026, 12, 31))
    base, content = artifact(
        "a1", "l1", "2026-08-01", "Essay", ("writing",), "writing",
        "learner", 1.0, (("gps", "secret"),),
    )
    ledger.append(base, content=content)
    with pytest.raises(ValueError, match="immutable"):
        ledger.append(base, content=content)
    with pytest.raises(ValueError, match="sha256"):
        candidate, candidate_content = artifact(
            "a2", "l1", "2026-08-01", "Bad", ("science",), "work_sample", "learner",
        )
        ledger.append(replace(candidate, content_hash="md5:abc"), content=candidate_content)
    empty, _ = artifact(
        "empty", "l1", "2026-08-01", "Empty", ("science",),
        "work_sample", "learner", content=b"",
    )
    with pytest.raises(ValueError, match="nonempty"):
        ledger.append(empty, content=b"")
    late, late_content = artifact(
        "late", "l1", "2026-08-02", "Late", ("science",), "work_sample", "learner",
    )
    assert late.parent_attestation is not None
    early_att = replace(late.parent_attestation, confirmed_on="2026-08-01", attestation_hash="")
    early_att = replace(early_att, attestation_hash=artifact_attestation_hash(early_att))
    with pytest.raises(ValueError, match="bound"):
        ledger.append(replace(late, parent_attestation=early_att), content=late_content)
    overclaimed, overclaimed_content = artifact(
        "hours", "l1", "2026-08-02", "Overclaimed", ("science",),
        "work_sample", "learner", 25.0,
    )
    with pytest.raises(ValueError, match=r"\[0, 24\]"):
        ledger.append(overclaimed, content=overclaimed_content)
    mutated, mutated_content = artifact(
        "mutated", "l1", "2026-08-02", "Essay", ("writing",),
        "writing", "learner", 1.0,
    )
    with pytest.raises(ValueError, match="bound"):
        ledger.append(replace(
            mutated, title="Relabeled project", subjects=("science", "mathematics"),
            instructional_hours=24.0,
        ), content=mutated_content)
    metadata_bound, metadata_content = artifact(
        "metadata", "l1", "2026-08-03", "Lab", ("science",),
        "work_sample", "learner", 1.0, (("rubric", "original"),),
    )
    with pytest.raises(ValueError, match="bound"):
        ledger.append(
            replace(metadata_bound, metadata=(("rubric", "substituted"),)),
            content=metadata_content,
        )


def test_portfolio_report_checks_state_subject_coverage():
    ledger = PortfolioLedger(today=date(2026, 12, 31))
    sample, content = artifact(
        "a1", "l1", "2026-08-01", "Math page", ("mathematics",),
        "work_sample", "learner", 1.0,
    )
    ledger.append(sample, content=content)
    profile = get_homeschool_profile("GA")
    assert profile is not None
    report = ledger.report(
        "l1", profile, period_start="2026-08-01", period_end="2027-07-31",
    )
    assert not report.complete and "science" in report.missing_subjects


def test_portfolio_export_strips_arbitrary_metadata():
    ledger = PortfolioLedger(today=date(2026, 12, 31))
    sample, content = artifact(
        "a1", "l1", "2026-08-01", "Math page", ("mathematics",),
        "work_sample", "learner", 1.0, (("gps", "12,34"),),
    )
    ledger.append(sample, content=content)
    profile = get_homeschool_profile("NJ")
    assert profile is not None
    exported = ledger.export(
        "l1", profile, approved_by_parent=True,
        period_start="2026-08-01", period_end="2027-07-31",
    )
    assert "metadata" not in exported.artifact_manifest[0]
    with pytest.raises(PermissionError):
        ledger.export(
            "l1", profile, approved_by_parent=False,
            period_start="2026-08-01", period_end="2027-07-31",
        )


def test_partial_portfolio_export_must_be_complete_on_its_own():
    ledger = PortfolioLedger(today=date(2026, 12, 31))
    profile = get_homeschool_profile("PA")
    assert profile is not None
    complete, complete_content = artifact(
        "complete", "l1", "2026-08-01", "Integrated project",
        profile.required_subjects, "project", "learner", 4.0,
    )
    partial, partial_content = artifact(
        "partial", "l1", "2026-08-02", "Reading log", ("reading",),
        "attendance_log", "parent", 1.0,
    )
    ledger.append(complete, content=complete_content)
    ledger.append(partial, content=partial_content)
    assert ledger.report(
        "l1", profile, period_start="2026-08-01", period_end="2027-07-31",
    ).complete
    exported = ledger.export(
        "l1", profile, approved_by_parent=True,
        period_start="2026-08-01", period_end="2027-07-31",
        selected_ids=("partial",),
    )
    assert not exported.evaluator_ready


def test_portfolio_rejects_future_and_replayed_evidence_and_scopes_periods():
    ledger = PortfolioLedger(today=date(2026, 9, 1))
    with pytest.raises(ValueError, match="future"):
        future, future_content = artifact(
            "future", "l1", "2026-09-02", "Future work", ("reading",),
            "work_sample", "learner",
        )
        ledger.append(future, content=future_content)
    current, current_content = artifact(
        "current", "l1", "2026-08-15", "Current work", ("reading",),
        "work_sample", "learner",
    )
    ledger.append(current, content=current_content)
    with pytest.raises(ValueError, match="already recorded"):
        replay, replay_content = artifact(
            "replay", "l1", "2026-08-16", "Replayed", ("mathematics",),
            "work_sample", "learner", content=current_content,
        )
        ledger.append(replay, content=replay_content)
    profile = get_homeschool_profile("PA")
    assert profile is not None
    prior = ledger.report(
        "l1", profile, period_start="2025-08-01", period_end="2026-07-31",
    )
    assert prior.artifact_count == 0


def test_wv_grade_assessment_trigger_and_methods():
    plan = assessment_plan(
        state="WV", route="notice_home_instruction", grade=5,
        method="nationally_normed_test", qualification="publisher-qualified",
    )
    decision = evaluate_assessment(plan, evaluated_at=SCHEDULED)
    assert decision.required and decision.allowed
    assert "certified_teacher_portfolio" in accepted_methods("WV")


def test_assessment_requires_parent_method_selection_and_qualification():
    valid = assessment_plan(
        state="FL", route="independent_home_education", grade=4,
        method="nationally_normed_test", assessment_id="a", learner_id="l",
    )
    assert not evaluate_assessment(replace(valid, parent_selected=False)).allowed
    no_qual = replace(valid, administrator_id="", administrator_qualification="")
    assert not evaluate_assessment(no_qual).allowed
    assert not evaluate_assessment(replace(valid, route_confirmed_by_parent=False)).allowed
    assert not evaluate_assessment(replace(valid, parent_attestation=None)).allowed
    assert not evaluate_assessment(replace(valid, scheduled_at=True)).allowed  # type: ignore[arg-type]
    assert not evaluate_assessment(replace(valid, scheduled_at=1e300)).allowed
    assert not evaluate_assessment(replace(valid, assessment_id="replayed")).allowed
    assert not evaluate_assessment(replace(valid, school_year="2027-2028")).allowed


def test_assessment_rejects_parent_attestation_from_future_trusted_time():
    plan = assessment_plan(
        state="GA", route="home_study", grade=3,
        method="nationally_normed_test",
    )
    assert plan.parent_attestation is not None
    decision = evaluate_assessment(
        plan, evaluated_at=plan.parent_attestation.confirmed_at - 1,
    )
    assert not decision.allowed
    assert any("future" in finding.lower() for finding in decision.findings)


def test_assessment_result_bound_to_plan_with_provenance():
    plan = assessment_plan(
        state="GA", route="home_study", grade=3,
        method="nationally_normed_test",
    )
    result = assessment_result(plan)
    ledger = AssessmentResultLedger()
    assert import_result(
        plan, result, imported_at=IMPORTED, report_content=REPORT_CONTENT, ledger=ledger,
    ) == result
    with pytest.raises(ValueError, match="bound"):
        import_result(
            plan, assessment_result(plan, assessment_id="other"),
            imported_at=IMPORTED, report_content=REPORT_CONTENT,
            ledger=AssessmentResultLedger(),
        )
    with pytest.raises(ValueError, match="provenance"):
        import_result(
            plan, assessment_result(plan, result_hash="sha256:short"),
            imported_at=IMPORTED, report_content=REPORT_CONTENT,
            ledger=AssessmentResultLedger(),
        )
    with pytest.raises(ValueError, match="timestamp"):
        import_result(
            plan, assessment_result(plan, received_at=SCHEDULED - 1),
            imported_at=IMPORTED, report_content=REPORT_CONTENT,
            ledger=AssessmentResultLedger(),
        )
    with pytest.raises(ValueError):
        import_result(
            plan, assessment_result(plan, received_at=1e300),
            imported_at=1e300, report_content=REPORT_CONTENT,
            ledger=AssessmentResultLedger(),
        )
    with pytest.raises(ValueError, match="provenance"):
        import_result(
            plan, result, imported_at=IMPORTED, report_content=b"tampered-report",
            ledger=AssessmentResultLedger(),
        )
    with pytest.raises(ValueError, match="immutable"):
        import_result(
            plan, result, imported_at=IMPORTED, report_content=REPORT_CONTENT, ledger=ledger,
        )
    relabeled = replace(result, source="different_source")
    with pytest.raises(ValueError, match="attestation"):
        import_result(
            plan, relabeled, imported_at=IMPORTED, report_content=REPORT_CONTENT,
            ledger=AssessmentResultLedger(),
        )


def test_assessment_methods_are_route_specific_and_invalid_routes_fail_closed():
    assert accepted_methods("TN", "independent_home_school") == ("state_or_standardized_test",)
    assert accepted_methods("TN", "church_related_school") == ("church_related_school_defined",)
    assert accepted_methods("FL", "pep_scholarship") == (
        "nationally_normed_test", "state_assessment",
    )
    assert accepted_methods("PA", "private_tutor") == ()
    umbrella = assessment_plan(
        state="TN", route="church_related_school", grade=5,
        method="church_related_school_defined", assessment_id="tn1",
        administrator_id="", qualification="",
    )
    decision = evaluate_assessment(umbrella, evaluated_at=SCHEDULED)
    assert decision.allowed and not decision.required
    invalid = replace(
        assessment_plan(
            state="TN", route="independent_home_school", grade=5,
            method="state_or_standardized_test", assessment_id="tn2",
        ),
        route="invented_route",
    )
    assert not evaluate_assessment(invalid).allowed


def test_no_assessment_route_uses_explicit_not_applicable_outcome():
    plan = assessment_plan(
        state="FL", route="private_school_umbrella", grade=4,
        method="not_applicable", assessment_id="fl-na",
        administrator_id="", qualification="", scheduled_at=0.0,
    )
    decision = evaluate_assessment(plan, evaluated_at=SCHEDULED)
    assert decision.allowed and not decision.required
    assert decision.accepted_methods == ("not_applicable",)
    with pytest.raises(ValueError, match="no-assessment"):
        import_result(
            plan, assessment_result(plan), imported_at=IMPORTED,
            report_content=REPORT_CONTENT, ledger=AssessmentResultLedger(),
        )


def test_sc_option1_and_pa_evaluator_are_annual_requirements():
    sc = assessment_plan(
        state="SC", route="option1_district", grade=4,
        method="statewide_test", assessment_id="sc1",
        administrator_id="district", qualification="authorized",
    )
    assert evaluate_assessment(sc).required
    pa = assessment_plan(
        state="PA", route="home_education", grade=4,
        method="qualified_evaluator", assessment_id="pa1",
        administrator_id="evaluator", qualification="qualified",
    )
    assert evaluate_assessment(pa).required


def test_evaluator_room_is_learner_artifact_and_time_scoped():
    portfolio = PortfolioLedger(today=date(2026, 12, 31))
    first, first_content = artifact(
        "a1", "l1", "2026-08-01", "Work", ("reading",), "work_sample", "learner",
    )
    second, second_content = artifact(
        "a2", "l2", "2026-08-01", "Other", ("reading",), "work_sample", "learner",
    )
    third, third_content = artifact(
        "a3", "l1", "2026-08-02", "More work", ("writing",), "work_sample", "learner",
    )
    portfolio.append(first, content=first_content)
    portfolio.append(second, content=second_content)
    portfolio.append(third, content=third_content)
    clock = [NOW]
    ledger = EvaluatorRoomLedger(portfolio, clock=lambda: clock[0])
    room = ledger.create(room_id="r1", learner_id="l1", evaluator_id="e1",
                         artifact_ids=("a1",), expires_at=NOW + 100,
                         created_by_parent="p1")
    with pytest.raises(ValueError, match="overlapping active"):
        ledger.create(
            room_id="r1-equivalent", learner_id="l1", evaluator_id="e1",
            artifact_ids=("a1",), expires_at=NOW + 100, created_by_parent="p2",
        )
    with pytest.raises(ValueError, match="overlapping active"):
        ledger.create(
            room_id="r1-partial", learner_id="l1", evaluator_id="e1",
            artifact_ids=("a1", "a3"), expires_at=NOW + 100, created_by_parent="p2",
        )
    assert ledger.authorize("r1", evaluator_id="e1", learner_id="l1", artifact_id="a1")
    assert not ledger.authorize("r1", evaluator_id="e1", learner_id="l2", artifact_id="a1")
    with pytest.raises(PermissionError, match="another learner"):
        ledger.create(room_id="r2", learner_id="l1", evaluator_id="e1",
                      artifact_ids=("a2",), expires_at=NOW + 100,
                      created_by_parent="p1")
    with pytest.raises(ValueError, match="bounded"):
        ledger.create(room_id="r3", learner_id="l1", evaluator_id="e1",
                      artifact_ids=("a1",), expires_at=NOW + (15 * 24 * 60 * 60),
                      created_by_parent="p1")
    clock[0] = NOW + 20
    ledger.revoke("r1", parent_id="p1")
    assert not ledger.authorize("r1", evaluator_id="e1", learner_id="l1", artifact_id="a1")
    replacement = ledger.create(
        room_id="r4", learner_id="l1", evaluator_id="e1",
        artifact_ids=("a1",), expires_at=NOW + 100, created_by_parent="p1",
    )
    assert replacement.room_id == "r4"
    with pytest.raises(ValueError, match="immutable"):
        ledger.create(
            room_id=" r1 ", learner_id="l1", evaluator_id="e2",
            artifact_ids=("a1",), expires_at=NOW + 100,
            created_by_parent="p1",
        )
    assert room.revoked is False  # stale snapshots cannot authorize; ledger state controls access.
    clock[0] = NOW + 101
    assert not ledger.authorize("r1", evaluator_id="e1", learner_id="l1", artifact_id="a1")


def test_support_plan_is_not_diagnosis_or_iep():
    bad = HomeschoolSupportPlan(
        "p1", "l1", "parent", (SupportStrategy("reading", "audiobook"),),
        diagnosis_claimed_by_praxis=True, labeled_as_iep=True,
    )
    decision = validate_support_plan(bad)
    assert not decision.allowed
    assert any("not an IEP" in x for x in decision.findings)
    privacy = HomeschoolSupportPlan(
        "p2", "l1", "parent", (
            SupportStrategy("reading", "audiobook", source="praxis_diagnosis"),
        ), therapy_schedule_private=False,
    )
    assert not validate_support_plan(privacy).allowed


def test_support_plan_requires_bound_parent_and_clinician_evidence():
    content = b"clinician recommendation"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    ledger = SupportEvidenceLedger(household_id="h1", authorized_parent_ids=("parent",))
    ledger.append(SupportEvidence(
        "clinical-1", "l1", "clinician_document", digest, "h1",
    ), content=content)
    base = HomeschoolSupportPlan(
        "p3", "l1", "parent", (
            SupportStrategy(
                "reading", "audiobook", "clinician_document", ("clinical-1",),
            ),
        ),
    )
    att = ParentSupportAttestation(
        "support-att", "parent", "l1", NOW, support_plan_hash(base), "",
    )
    att = replace(att, attestation_hash=support_attestation_hash(att))
    plan = replace(base, parent_attestation=att)
    assert validate_support_plan(
        plan, evidence_ledger=ledger, validated_at=NOW + 1,
    ).allowed
    assert not validate_support_plan(
        replace(plan, learner_id="l2"),
        evidence_ledger=ledger, validated_at=NOW + 1,
    ).allowed
    assert not validate_support_plan(replace(
        plan,
        strategies=(SupportStrategy("reading", "different", "clinician_document", ("clinical-1",)),),
    ), evidence_ledger=ledger, validated_at=NOW + 1).allowed
    unrepresentable = replace(att, confirmed_at=253402300800.0, attestation_hash="")
    unrepresentable = replace(
        unrepresentable, attestation_hash=support_attestation_hash(unrepresentable),
    )
    assert not validate_support_plan(
        replace(base, parent_attestation=unrepresentable),
        evidence_ledger=ledger, validated_at=NOW + 1,
    ).allowed
    assert not validate_support_plan(
        plan, evidence_ledger=ledger, validated_at=NOW - 1,
    ).allowed


def test_support_plan_hash_uses_unambiguous_canonical_encoding():
    first = HomeschoolSupportPlan(
        "p1", "l1", "parent",
        (SupportStrategy("a|b", "c", "parent_observation"),),
    )
    second = HomeschoolSupportPlan(
        "p1", "l1", "parent",
        (SupportStrategy("a", "b|c", "parent_observation"),),
    )
    assert support_plan_hash(first) != support_plan_hash(second)


def test_service_inquiry_never_guarantees_or_sends():
    content = b"parent observation"
    evidence = SupportEvidenceLedger(household_id="h1", authorized_parent_ids=("p1",))
    evidence.append(SupportEvidence(
        "work-1", "l1", "parent_observation",
        "sha256:" + hashlib.sha256(content).hexdigest(), "h1",
    ), content=content)
    draft = ServiceInquiryDraft(
        "i1", "l1", "NJ", "evaluation_request", "p1", ("work-1",),
        claims_guaranteed_services=True, household_id="h1",
    )
    assert not evaluate_service_inquiry(draft, evidence_ledger=evidence).allowed
    with pytest.raises(PermissionError, match="SEND-held"):
        release_service_inquiry(draft)
    injected = ServiceInquiryDraft(
        "i2", "l1", "New York", "service_availability", "p1", (),
        status="sent", household_id="h1",
    )
    assert not evaluate_service_inquiry(injected).allowed
    unknown = replace(draft, claims_guaranteed_services=False, evidence_ids=("unknown",))
    assert not evaluate_service_inquiry(unknown, evidence_ledger=evidence).allowed
    blank = replace(draft, claims_guaranteed_services=False, evidence_ids=(" ",))
    assert not evaluate_service_inquiry(blank, evidence_ledger=evidence).allowed
    unauthorized = replace(
        draft, parent_id="arbitrary-unverified-actor", claims_guaranteed_services=False,
    )
    assert not evaluate_service_inquiry(unauthorized, evidence_ledger=evidence).allowed
    availability = ServiceInquiryDraft(
        "i3", "l1", "NJ", "service_availability", "p1", (), household_id="h1",
    )
    assert evaluate_service_inquiry(availability, evidence_ledger=evidence).allowed
    assert not evaluate_service_inquiry(availability).allowed
    cross_household = SupportEvidenceLedger(
        household_id="h2", authorized_parent_ids=("p1",),
    )
    cross_household.append(SupportEvidence(
        "work-1", "l1", "parent_observation",
        "sha256:" + hashlib.sha256(content).hexdigest(), "h2",
    ), content=content)
    assert not evaluate_service_inquiry(draft, evidence_ledger=cross_household).allowed
    assert not evaluate_service_inquiry(
        availability, evidence_ledger=cross_household,
    ).allowed


def test_reentry_packet_warns_placement_not_guaranteed():
    ledger = ReentryEvidenceLedger()
    for record in (
        ReentryEvidenceRecord("portfolio", "p1", "l1"),
        ReentryEvidenceRecord("assessment", "a1", "l1"),
        ReentryEvidenceRecord("transcript", "t1", "l1"),
    ):
        ledger.append(record)
    packet = ReentryPacket("l1", "CT", ("p1",), ("a1",), "t1", True)
    assert validate_reentry_packet(packet, evidence_ledger=ledger).allowed
    assert "does not guarantee" in packet.placement_warning
    assert not validate_reentry_packet(
        ReentryPacket("l1", "CT", ("p1",), (), "", "yes"),  # type: ignore[arg-type]
        evidence_ledger=ledger,
    ).allowed
    assert not validate_reentry_packet(ReentryPacket(
        "l1", "CT", ("p1",), (), "t1", True, "Placement guaranteed.",
    ), evidence_ledger=ledger).allowed
    assert not validate_reentry_packet(
        ReentryPacket("", "ZZ", (), (), " ", True), evidence_ledger=ledger,
    ).allowed
    foreign = ReentryEvidenceLedger()
    foreign.append(ReentryEvidenceRecord("transcript", "t1", "l2"))
    assert not validate_reentry_packet(
        ReentryPacket("l1", "CT", (), (), "t1", True), evidence_ledger=foreign,
    ).allowed
