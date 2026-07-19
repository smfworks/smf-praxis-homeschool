"""Homeschool Session 3: collaboration, transcript, and funding."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal

import pytest

from hybridagent import homeschool_transcript as transcript_module
from hybridagent.homeschool_collaboration import (
    CollaborationGrant,
    CollaborationLedger,
    validate_grant,
)
from hybridagent.homeschool_funding import (
    Expense,
    FundingEligibility,
    FundingLedger,
    FundingProgram,
    classify_expense,
    funding_eligibility_hash,
    funding_program_hash,
    reimbursement_packet_hash,
    submit_reimbursement,
)
from hybridagent.homeschool_transcript import (
    CourseRecord,
    DiplomaPacket,
    TranscriptEvidence,
    TranscriptEvidenceLedger,
    TranscriptPolicy,
    build_transcript,
    transcript_policy_hash,
    validate_course,
    validate_diploma,
)

NOW = 1_785_000_000.0
VALID_HASH = "sha256:" + ("a" * 64)
VALID_HASH_B = "sha256:" + ("b" * 64)
VALID_HASH_C = "sha256:" + ("c" * 64)
VALID_HASH_D = "sha256:" + ("d" * 64)


def tutor_grant(**kwargs: object) -> CollaborationGrant:
    values = {
        "grant_id": "g1", "collaborator_id": "t1", "role": "tutor",
        "learner_ids": ("l1",), "course_ids": ("math",),
        "scopes": ("assigned_course", "feedback"),
        "created_by_parent": "p1", "created_at": NOW,
        "expires_at": NOW + 1000,
    }
    values.update(kwargs)
    return CollaborationGrant(**values)  # type: ignore[arg-type]


def test_collaboration_is_learner_course_scope_and_expiry_bound():
    clock = [NOW + 10]
    ledger = CollaborationLedger(clock=lambda: clock[0])
    ledger.create(tutor_grant())
    assert ledger.authorize("g1", collaborator_id="t1", learner_id="l1",
                            scope="feedback", course_id="math").allowed
    assert not ledger.authorize("g1", collaborator_id="t1", learner_id="l2",
                                scope="feedback", course_id="math").allowed
    assert not ledger.authorize("g1", collaborator_id="t1", learner_id="l1",
                                scope="feedback", course_id="science").allowed
    clock[0] = NOW + 1000
    assert not ledger.authorize("g1", collaborator_id="t1", learner_id="l1",
                                scope="feedback", course_id="math").allowed


def test_tutor_cannot_receive_financial_or_health_scope():
    assert not validate_grant(tutor_grant(scopes=("financial",))).allowed


def test_grant_rejects_blank_scopes_and_canonicalizes_identities():
    invalid = tutor_grant(learner_ids=("",), course_ids=("",), created_by_parent="   ")
    assert not validate_grant(invalid).allowed
    ledger = CollaborationLedger(clock=lambda: NOW)
    saved = ledger.create(tutor_grant(
        grant_id=" g2 ", collaborator_id=" t2 ", learner_ids=(" l1 ",),
        course_ids=(" math ",), scopes=(" feedback ",), created_by_parent=" p1 ",
    ))
    assert saved.grant_id == "g2" and saved.created_by_parent == "p1"
    assert ledger.authorize(
        "g2", collaborator_id="t2", learner_id="l1", scope="feedback",
        course_id="math",
    ).allowed


def test_grants_are_fresh_short_lived_immutable_and_parent_revocable():
    ledger = CollaborationLedger(clock=lambda: NOW)
    grant = tutor_grant()
    ledger.create(grant)
    with pytest.raises(ValueError, match="immutable"):
        ledger.create(grant)
    with pytest.raises(PermissionError):
        ledger.revoke("g1", parent_id="other")
    ledger.revoke("g1", parent_id="p1")
    assert not ledger.authorize("g1", collaborator_id="t1", learner_id="l1",
                                scope="feedback", course_id="math").allowed
    long_lived = tutor_grant(grant_id="long", expires_at=NOW + (31 * 24 * 60 * 60))
    assert not validate_grant(long_lived, now=NOW).allowed
    stale = tutor_grant(grant_id="stale", created_at=NOW - 1000, expires_at=NOW + 1000)
    assert not validate_grant(stale, now=NOW).allowed


def test_equivalent_active_collaboration_grants_cannot_bypass_revocation():
    ledger = CollaborationLedger(clock=lambda: NOW)
    ledger.create(tutor_grant())
    with pytest.raises(ValueError, match="equivalent active"):
        ledger.create(tutor_grant(grant_id="same-access"))
    with pytest.raises(ValueError, match="equivalent active"):
        ledger.create(tutor_grant(grant_id="same-access-other-parent", created_by_parent="p2"))
    with pytest.raises(ValueError, match="overlapping active"):
        ledger.create(tutor_grant(
            grant_id="overlap", scopes=("feedback", "assignment"),
        ))
    ledger.revoke("g1", parent_id="p1")
    replacement = ledger.create(tutor_grant(grant_id="replacement"))
    assert replacement.grant_id == "replacement"


def test_unrestricted_collaboration_grant_overlaps_course_specific_grant():
    ledger = CollaborationLedger(clock=lambda: NOW)
    broad = CollaborationGrant(
        "broad", "co-parent", "co_parent", ("l1",), (), ("learning_plan",),
        "p1", NOW, NOW + 1000,
    )
    ledger.create(broad)
    with pytest.raises(ValueError, match="overlapping active"):
        ledger.create(replace(
            broad, grant_id="narrow", course_ids=("math",), created_by_parent="p2",
        ))

    reverse = CollaborationLedger(clock=lambda: NOW)
    reverse.create(replace(broad, grant_id="narrow-first", course_ids=("math",)))
    with pytest.raises(ValueError, match="overlapping active"):
        reverse.create(replace(broad, grant_id="broad-second", created_by_parent="p2"))


def test_collaboration_grant_cannot_authorize_before_creation():
    clock = [NOW]
    ledger = CollaborationLedger(clock=lambda: clock[0])
    ledger.create(tutor_grant())
    clock[0] = NOW - 1
    decision = ledger.authorize(
        "g1", collaborator_id="t1", learner_id="l1",
        scope="feedback", course_id="math",
    )
    assert not decision.allowed


def test_collaboration_stamps_creation_and_bounds_expiry_from_trusted_clock():
    ledger = CollaborationLedger(clock=lambda: NOW)
    max_ttl = 30 * 24 * 60 * 60
    created = ledger.create(tutor_grant(
        grant_id="trusted", created_at=NOW - 299,
        expires_at=NOW + max_ttl - 299,
    ))
    assert created.created_at == NOW
    with pytest.raises(ValueError, match="maximum"):
        ledger.create(tutor_grant(
            grant_id="too-long", collaborator_id="t2", created_at=NOW + 299,
            expires_at=NOW + max_ttl + 1,
        ))
    impossible = 253402300800.0
    unrepresentable = CollaborationLedger(clock=lambda: impossible)
    with pytest.raises(ValueError, match="clock"):
        unrepresentable.create(tutor_grant(
            created_at=impossible, expires_at=impossible + 100,
        ))


def test_collaboration_cannot_revoke_at_or_after_expiry():
    clock = [NOW]
    ledger = CollaborationLedger(clock=lambda: clock[0])
    ledger.create(tutor_grant(expires_at=NOW + 100))
    clock[0] = NOW + 100
    with pytest.raises(ValueError, match="timestamp"):
        ledger.revoke("g1", parent_id="p1")


def policy() -> TranscriptPolicy:
    return TranscriptPolicy("p1", "The Smith Family Home Education Program",
                            "1.0 credit = documented full-year course",
                            "A=4,B=3,C=2,D=1,F=0")


def course(identifier: str = "c1", **kwargs: object) -> CourseRecord:
    suffix = "1" if identifier == "c1" else "2"
    values = {
        "course_id": identifier, "learner_id": "l1",
        "title": "Algebra I" if identifier == "c1" else "Biology Honors",
        "school_year": "2026", "credits": Decimal("1.0"),
        "grade_points": Decimal("4.0"), "level": "standard",
        "evidence_ids": (f"work-{suffix}", f"exam-{suffix}"),
        "description": "Documented course foundations", "parent_finalized": True,
    }
    values.update(kwargs)
    return CourseRecord(**values)  # type: ignore[arg-type]


def evidence_ledger() -> TranscriptEvidenceLedger:
    ledger = TranscriptEvidenceLedger()
    for evidence_id in ("work-1", "exam-1", "work-2", "exam-2"):
        content = f"transcript-evidence:{evidence_id}".encode()
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        ledger.append(TranscriptEvidence(
            evidence_id, "l1", "2026", "portfolio_or_assessment", digest,
        ), content=content)
    return ledger


def issue_transcript(*courses: CourseRecord):
    return build_transcript(
        transcript_id="t1", learner_id="l1", state="NJ", policy=policy(),
        courses=courses or (course(),), parent_approved=True,
        evidence_ledger=evidence_ledger(),
    )


def test_transcript_requires_evidence_and_parent_final_grade():
    assert any("evidence" in x.lower() for x in validate_course(course(evidence_ids=())))
    assert any("finalize" in x.lower() for x in validate_course(course(parent_finalized=False)))


def test_transcript_rejects_bool_nan_out_of_range_and_unknown_level():
    with pytest.raises(ValueError, match="boolean"):
        validate_course(course(credits=True))
    with pytest.raises(ValueError, match="finite"):
        validate_course(course(grade_points=Decimal("NaN")))
    assert any("grade points" in x.lower() for x in validate_course(course(grade_points=Decimal("5"))))
    assert any("course level" in x.lower() for x in validate_course(course(level="invented")))


def test_transcript_gpa_is_reproducible_weighted_and_unweighted():
    transcript = issue_transcript(
        course("c1", grade_points=Decimal("4"), level="standard"),
        course("c2", grade_points=Decimal("3"), level="honors"),
    )
    assert transcript.total_credits == Decimal("2.000")
    assert transcript.unweighted_gpa == Decimal("3.500")
    assert transcript.weighted_gpa == Decimal("3.750")
    assert "Parent-issued" in transcript.provenance_note
    assert transcript.record_hash.startswith("sha256:")


def test_dual_enrollment_needs_official_provider_record():
    assert any("Dual-enrollment" in x for x in validate_course(course(level="dual_enrollment")))
    valid = course(level="dual_enrollment", external_provider="College",
                   external_record_hash=VALID_HASH)
    assert not validate_course(valid)
    assert validate_course(course(external_provider="Provider", external_record_hash="sha256:bad"))
    assert validate_course(course(external_provider="Provider"))


def test_transcript_binds_evidence_and_blocks_duplicate_credit():
    with pytest.raises(ValueError, match="different learner"):
        build_transcript(
            transcript_id="t", learner_id="l1", state="NJ", policy=policy(),
            courses=(course(learner_id="l2"),), parent_approved=True,
            evidence_ledger=evidence_ledger(),
        )
    duplicate = course("same")
    with pytest.raises(ValueError, match="unique"):
        build_transcript(
            transcript_id="t", learner_id="l1", state="NJ", policy=policy(),
            courses=(duplicate, duplicate), parent_approved=True,
            evidence_ledger=evidence_ledger(),
        )
    with pytest.raises(ValueError, match="multiple courses"):
        issue_transcript(course("c1"), course("c2", evidence_ids=("work-1", "exam-2")))
    with pytest.raises(ValueError, match="canonical course"):
        issue_transcript(course("c1"), course("c2", title=" algebra  i "))
    foreign = evidence_ledger()
    foreign_content = b"foreign-work"
    foreign._records["work-1"] = TranscriptEvidence(  # noqa: SLF001 - adversarial fixture
        "work-1", "l2", "2026", "portfolio",
        "sha256:" + hashlib.sha256(foreign_content).hexdigest(),
    )
    with pytest.raises(ValueError, match="another learner"):
        build_transcript(
            transcript_id="t", learner_id="l1", state="NJ", policy=policy(),
            courses=(course(),), parent_approved=True, evidence_ledger=foreign,
        )
    with pytest.raises(ValueError, match="supported homeschool jurisdiction"):
        build_transcript(
            transcript_id="t", learner_id="l1", state="ZZ", policy=policy(),
            courses=(course(),), parent_approved=True, evidence_ledger=evidence_ledger(),
        )


def test_external_record_hash_must_resolve_through_course_evidence():
    ledger = evidence_ledger()
    unresolved = course(
        level="dual_enrollment", external_provider="College",
        external_record_hash=VALID_HASH,
    )
    with pytest.raises(ValueError, match="does not resolve"):
        build_transcript(
            transcript_id="t", learner_id="l1", state="NJ", policy=policy(),
            courses=(unresolved,), parent_approved=True, evidence_ledger=ledger,
        )


def test_transcript_evidence_replay_under_new_id_is_rejected():
    ledger = TranscriptEvidenceLedger()
    content = b"same evidence"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    ledger.append(TranscriptEvidence("one", "l1", "2026", "portfolio", digest), content=content)
    with pytest.raises(ValueError, match="already recorded"):
        ledger.append(TranscriptEvidence("two", "l1", "2026", "portfolio", digest), content=content)
    with pytest.raises(ValueError, match="already recorded"):
        ledger.append(TranscriptEvidence("three", "l1", "2027", "portfolio", digest), content=content)
    with pytest.raises(ValueError, match="already recorded"):
        ledger.append(TranscriptEvidence("four", "l2", "2027", "portfolio", digest), content=content)


def test_diploma_is_bound_to_matching_transcript_policy_and_threshold():
    transcript = issue_transcript(course())
    packet = DiplomaPacket(
        "d1", "l1", "NJ", policy().issuer_name, "t1", transcript.record_hash,
        policy().policy_id, True, transcript.policy_hash,
    )
    assert not validate_diploma(packet, transcript=transcript, policy=policy())
    wrong = DiplomaPacket(
        "d2", "other", "NJ", policy().issuer_name, "t1", transcript.record_hash,
        policy().policy_id, True, transcript.policy_hash,
        claims_state_issued=True, claims_accredited=True,
    )
    findings = validate_diploma(wrong, transcript=transcript, policy=replace(
        policy(), required_credits=Decimal("2"),
    ))
    assert any("state-issued" in item for item in findings)
    assert any("accreditation" in item for item in findings)
    assert any("recomputed approved transcript" in item for item in findings)
    assert any("credit threshold" in item for item in findings)
    assert validate_diploma(
        packet, transcript=transcript,
        policy=replace(policy(), grade_scale="mutated"),
    )
    assert validate_diploma(
        replace(packet, state=""), transcript=transcript,
        policy=policy(),
    )
    forged = replace(transcript, courses=(), total_credits=Decimal("99"))
    assert validate_diploma(packet, transcript=forged, policy=policy())
    changed_evidence = replace(
        transcript.evidence_manifest[0], content_hash=VALID_HASH_D,
    )
    altered = replace(
        transcript,
        evidence_manifest=(changed_evidence,) + transcript.evidence_manifest[1:],
    )
    assert validate_diploma(packet, transcript=altered, policy=policy())

    def rehash(candidate):
        payload = transcript_module._transcript_payload(
            transcript_id=candidate.transcript_id,
            learner_id=candidate.learner_id,
            state=candidate.state,
            issuer_name=candidate.issuer_name,
            policy_id=candidate.policy_id,
            policy_hash=candidate.policy_hash,
            courses=candidate.courses,
            evidence_manifest=candidate.evidence_manifest,
        )
        return replace(candidate, record_hash=transcript_module._canonical_hash(payload))

    foreign = rehash(replace(
        transcript, courses=(replace(transcript.courses[0], learner_id="other"),),
    ))
    assert validate_diploma(
        replace(packet, transcript_hash=foreign.record_hash),
        transcript=foreign, policy=policy(),
    )
    two_courses = issue_transcript(course(), course("c2"))
    reused = rehash(replace(
        two_courses,
        courses=(two_courses.courses[0], replace(
            two_courses.courses[1], evidence_ids=two_courses.courses[0].evidence_ids,
        )),
    ))
    reused_packet = replace(packet, transcript_hash=reused.record_hash)
    assert validate_diploma(
        reused_packet, transcript=reused, policy=policy(),
    )
    assert transcript.policy_hash == transcript_policy_hash(policy())


def test_diploma_rejects_duplicate_credit_content_under_distinct_evidence_ids():
    transcript = issue_transcript(course(), course("c2"))
    first_hash = transcript.evidence_manifest[0].content_hash
    forged_manifest = tuple(
        replace(item, content_hash=first_hash) if item.evidence_id == "work-2" else item
        for item in transcript.evidence_manifest
    )
    forged = replace(transcript, evidence_manifest=forged_manifest)
    payload = transcript_module._transcript_payload(
        transcript_id=forged.transcript_id, learner_id=forged.learner_id,
        state=forged.state, issuer_name=forged.issuer_name,
        policy_id=forged.policy_id, policy_hash=forged.policy_hash,
        courses=forged.courses, evidence_manifest=forged.evidence_manifest,
    )
    forged = replace(forged, record_hash=transcript_module._canonical_hash(payload))
    packet = DiplomaPacket(
        "d1", "l1", "NJ", policy().issuer_name, forged.transcript_id,
        forged.record_hash, policy().policy_id, True, forged.policy_hash,
    )
    findings = validate_diploma(packet, transcript=forged, policy=policy())
    assert any("content" in finding.lower() for finding in findings)


def program(*, complete: bool = True) -> FundingProgram:
    return FundingProgram(
        "prog1", "WV", "Example Scholarship", ("curriculum", "tutoring"),
        ("Vendor A",), "2026-07-01", "2027-06-30",
        "https://example.gov/program", "2026-07-18", complete,
    )


def eligibility(*, program_record: FundingProgram | None = None,
                **kwargs: object) -> FundingEligibility:
    bound_program = program_record or program()
    values = {
        "eligibility_id": "elig1", "learner_id": "l1", "program_id": "prog1",
        "account_id": "account1", "parent_id": "parent", "award_year": "2026-2027",
        "source_verified_on": "2026-07-18", "determined_at": NOW - 60,
        "expires_at": NOW + (30 * 24 * 60 * 60), "parent_confirmed": True,
        "program_policy_hash": funding_program_hash(bound_program),
        "determination_hash": "",
    }
    values.update(kwargs)
    record = FundingEligibility(**values)  # type: ignore[arg-type]
    if not record.determination_hash:
        record = replace(record, determination_hash=funding_eligibility_hash(record))
    return record


def expense(identifier: str = "e1", **kwargs: object) -> Expense:
    receipt = "sha256:" + hashlib.sha256(receipt_content(identifier)).hexdigest()
    values = {
        "expense_id": identifier, "learner_id": "l1", "program_id": "prog1",
        "vendor": "Vendor A", "category": "curriculum",
        "amount": Decimal("100.00"), "purchased_on": "2026-08-01",
        "receipt_hash": receipt, "attested_by_parent": "parent", "parent_attested": True,
    }
    values.update(kwargs)
    return Expense(**values)  # type: ignore[arg-type]


def receipt_content(identifier: str) -> bytes:
    return f"receipt:{identifier}".encode()


def classify(item: Expense, *, rules_complete: bool = True,
             eligibility_record: FundingEligibility | None = None):
    bound_program = program(complete=rules_complete)
    return classify_expense(
        bound_program, item,
        eligibility=eligibility_record or eligibility(program_record=bound_program), now=NOW,
    )


def funding_ledger(*, award: str = "500", eligibility_record: FundingEligibility | None = None):
    bound_program = program()
    return FundingLedger(
        bound_program, award_amount=Decimal(award),
        eligibility=eligibility_record or eligibility(program_record=bound_program), now=NOW,
    )


def test_funding_classifier_requires_bound_fresh_eligibility():
    assert classify(expense()).eligibility == "eligible"
    assert classify(expense(category="travel")).eligibility == "ineligible"
    assert classify(expense(), rules_complete=False).eligibility == "uncertain"
    assert classify(expense(vendor="Unknown")).eligibility == "uncertain"
    assert classify(expense(), eligibility_record=eligibility(learner_id="other")).eligibility == "uncertain"
    assert classify(expense(), eligibility_record=eligibility(expires_at=NOW - 1)).eligibility == "uncertain"
    assert classify(expense(attested_by_parent="other")).eligibility == "ineligible"
    assert classify(
        expense(), eligibility_record=eligibility(determined_at=True),
    ).eligibility == "uncertain"


def test_funding_rejects_bool_nonfinite_invalid_dates_and_hashes():
    with pytest.raises(ValueError, match="boolean"):
        classify(expense(amount=True))
    with pytest.raises(ValueError, match="finite"):
        classify(expense(amount=Decimal("NaN")))
    with pytest.raises(ValueError, match="decimal places"):
        classify(expense(amount=Decimal("0.001")))
    assert classify_expense(
        program(), expense(), eligibility=eligibility(), now=253402300800.0,
    ).eligibility == "uncertain"
    assert classify(expense(receipt_hash="sha256:short")).eligibility == "ineligible"
    with pytest.raises(ValueError, match="ISO date"):
        classify(expense(purchased_on="2026-99-99"))
    with pytest.raises(ValueError, match="supported homeschool"):
        classify_expense(
            replace(program(), state="ZZ"), expense(), eligibility=eligibility(), now=NOW,
        )


def test_funding_policy_hash_binds_rules_and_avoids_delimiter_collisions():
    first = eligibility(learner_id="a|b", account_id="c")
    second = eligibility(learner_id="a", account_id="b|c")
    assert funding_eligibility_hash(first) != funding_eligibility_hash(second)
    original = program()
    bound = eligibility(program_record=original)
    changed = replace(original, source_url="https://example.gov/changed")
    assert classify_expense(changed, expense(), eligibility=bound, now=NOW).eligibility == "uncertain"


def test_funding_ledger_balance_packet_holds_and_receipts():
    ledger = funding_ledger()
    assert ledger.append(expense(), receipt_content=receipt_content("e1")).eligibility == "eligible"
    assert ledger.balance() == Decimal("400.00")
    packet = ledger.build_packet(("e1",), packet_id="rp1", approved_by_parent="parent")
    assert packet.total == Decimal("100.00")
    assert packet.state == "WV" and packet.program_policy_hash == funding_program_hash(program())
    assert packet.learner_id == "l1" and packet.account_id == "account1"
    assert packet.eligibility_id == "elig1"
    assert packet.determination_hash == eligibility().determination_hash
    assert packet.packet_hash == reimbursement_packet_hash(packet)
    assert packet.expense_manifest[0].receipt_hash == expense().receipt_hash

    other_eligibility = eligibility(
        eligibility_id="elig2", learner_id="l2", account_id="account2",
    )
    other = funding_ledger(eligibility_record=other_eligibility)
    other.append(
        expense(learner_id="l2"), receipt_content=receipt_content("e1"),
    )
    other_packet = other.build_packet(
        ("e1",), packet_id="rp1", approved_by_parent="parent",
    )
    assert other_packet != packet
    with pytest.raises(PermissionError, match="SEND-held"):
        submit_reimbursement(packet)
    recorded = ledger.record_submission_receipt(
        "rp1", parent_id="parent", receipt_id="external-1", submitted_at=NOW + 1,
    )
    assert recorded.status == "receipt_recorded"
    with pytest.raises(PermissionError, match="eligible learner"):
        ledger.build_packet(("e1",), packet_id="wrong-parent", approved_by_parent="other")


def test_uncertain_expense_never_enters_reimbursement_packet():
    ledger = funding_ledger()
    ledger.append(expense(vendor="Unknown"), receipt_content=receipt_content("e1"))
    with pytest.raises(ValueError, match="eligible"):
        ledger.build_packet(("e1",), packet_id="rp1", approved_by_parent="parent")


def test_funding_packets_cannot_overcommit_reuse_or_replay_receipts():
    ledger = funding_ledger(award="150")
    ledger.append(expense("e1", amount=Decimal("100")), receipt_content=receipt_content("e1"))
    ledger.append(expense("e2", amount=Decimal("100")), receipt_content=receipt_content("e2"))
    with pytest.raises(ValueError, match="receipt hash"):
        ledger.append(
            expense("e3", receipt_hash=expense("e1").receipt_hash),
            receipt_content=receipt_content("e1"),
        )
    ledger.build_packet(("e1",), packet_id="p1", approved_by_parent="parent")
    with pytest.raises(ValueError, match="already committed"):
        ledger.build_packet(("e1",), packet_id="p2", approved_by_parent="parent")
    with pytest.raises(ValueError, match="exceed"):
        ledger.build_packet(("e2",), packet_id="p2", approved_by_parent="parent")
    ledger.cancel_packet("p1", parent_id="parent")
    packet = ledger.build_packet(("e1",), packet_id="p3", approved_by_parent="parent")
    assert packet.status == "ready_for_parent_submission"


def test_funding_rejects_empty_receipts_and_duplicate_submission_receipts():
    ledger = funding_ledger()
    with pytest.raises(ValueError, match="nonempty"):
        ledger.append(expense(), receipt_content=b"")
    ledger.append(expense("e1"), receipt_content=receipt_content("e1"))
    ledger.append(expense("e2"), receipt_content=receipt_content("e2"))
    ledger.build_packet(("e1",), packet_id="p1", approved_by_parent="parent")
    ledger.build_packet(("e2",), packet_id="p2", approved_by_parent="parent")
    ledger.record_submission_receipt(
        "p1", parent_id="parent", receipt_id="external", submitted_at=NOW + 1,
    )
    with pytest.raises(ValueError, match="already recorded"):
        ledger.record_submission_receipt(
            "p2", parent_id="parent", receipt_id="external", submitted_at=NOW + 2,
        )

    tampered = funding_ledger()
    tampered.append(expense(), receipt_content=receipt_content("e1"))
    packet = tampered.build_packet(("e1",), packet_id="tampered", approved_by_parent="parent")
    tampered._packets["tampered"] = replace(packet, total=Decimal("999.00"))
    with pytest.raises(ValueError, match="packet"):
        tampered.record_submission_receipt(
            "tampered", parent_id="parent", receipt_id="tampered-receipt",
            submitted_at=NOW + 1,
        )
