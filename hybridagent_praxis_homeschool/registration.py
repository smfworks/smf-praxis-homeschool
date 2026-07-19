"""Registration — wire the homeschool vertical into the Praxis base registry."""

from __future__ import annotations

from hybridagent.broker import RiskClass
from hybridagent.evals import EvalCase
from hybridagent.verticals.registry import (
    VerticalSpec,
    register_vertical_eval_cases,
    register_vertical_spec,
)


_HOMESCHOOL_SPEC = VerticalSpec(
    name="homeschool",
    persona_keyword="homeschool",
    compliance_mode="enforced",
    autonomous={RiskClass.READ, RiskClass.DRAFT},
    held={RiskClass.SEND, RiskClass.DESTRUCTIVE},
    version="0.1.0",
)


def _route_gate_case():
    def run() -> tuple[bool, str]:
        from .modules.homeschool_route import RouteSelection, evaluate_route
        result = evaluate_route(RouteSelection(
            "OH", "public_virtual", True, "2026-08-01",
            district_enrolled=True, school_of_record="public_school",
        ))
        blocked = any(f.code == "public_school_not_homeschool" for f in result.findings)
        return blocked and not result.allowed, f"blocked={blocked}"
    return run


def _attendance_case():
    def run() -> tuple[bool, str]:
        from .modules.homeschool_compliance import InstructionEntry, InstructionLedger
        ledger = InstructionLedger()
        rejected = False
        try:
            ledger.append(InstructionEntry(
                "bad", "l1", "2026-08-01", "math", 1.0, (), True,
            ))
        except ValueError:
            rejected = True
        ledger.append(InstructionEntry(
            "ok", "l1", "2026-08-01", "math", 1.0, ("work-1",), True,
        ))
        return rejected and len(ledger.for_learner("l1")) == 1, f"rejected={rejected}"
    return run


def _tutor_case():
    def run() -> tuple[bool, str]:
        from .modules.home_tutor import TutorRequest, assess_tutor_request
        graded = assess_tutor_request(TutorRequest(
            "s1", "l1", 14, "summative", "give answer", asks_for_complete_answer=True,
        ))
        formative = assess_tutor_request(TutorRequest(
            "s2", "l1", 14, "formative", "help me reason",
        ))
        return (not graded.allowed) and formative.allowed, (
            f"graded={graded.allowed} formative={formative.allowed}")
    return run


def _collaboration_case():
    def run() -> tuple[bool, str]:
        from .modules.homeschool_collaboration import CollaborationGrant, validate_grant
        valid = validate_grant(CollaborationGrant(
            "g1", "t1", "tutor", ("l1",), ("math",),
            ("assigned_course", "feedback"), "p1", 1.0, 100.0,
        ))
        financial = validate_grant(CollaborationGrant(
            "g2", "t1", "tutor", ("l1",), ("math",),
            ("financial",), "p1", 1.0, 100.0,
        ))
        return valid.allowed and not financial.allowed, (
            f"valid={valid.allowed} financial={financial.allowed}")
    return run


def _transcript_case():
    def run() -> tuple[bool, str]:
        from decimal import Decimal
        import hashlib

        from .modules.homeschool_transcript import (
            CourseRecord,
            DiplomaPacket,
            TranscriptEvidence,
            TranscriptEvidenceLedger,
            TranscriptPolicy,
            build_transcript,
            validate_diploma,
        )
        evidence = TranscriptEvidenceLedger()
        content = b"vertical-eval-work"
        evidence.append(TranscriptEvidence(
            "work-1", "l1", "2026", "portfolio",
            "sha256:" + hashlib.sha256(content).hexdigest(),
        ), content=content)
        policy = TranscriptPolicy("p1", "Family Home Education", "one year", "A=4")
        transcript = build_transcript(
            transcript_id="t1", learner_id="l1", state="NJ",
            policy=policy,
            courses=(CourseRecord(
                "c1", "l1", "Algebra I", "2026", Decimal("1"), Decimal("4"),
                "standard", ("work-1",), "Algebra foundations", True,
            ),),
            parent_approved=True, evidence_ledger=evidence,
        )
        diploma_ok = not validate_diploma(DiplomaPacket(
            "d1", "l1", "NJ", "Family Home Education", "t1",
            transcript.record_hash, "p1", True, transcript.policy_hash,
        ), transcript=transcript, policy=policy)
        return ("Parent-issued" in transcript.provenance_note and diploma_ok,
                f"gpa={transcript.unweighted_gpa} diploma={diploma_ok}")
    return run


def _manual_cases() -> list[EvalCase]:
    return [
        EvalCase("vertical.homeschool.route_gate", "vertical",
                 "Public virtual enrollment is not mislabeled independent homeschool.",
                 _route_gate_case()),
        EvalCase("vertical.homeschool.no_fabricated_attendance", "vertical",
                 "Attendance needs parent attestation and evidence.",
                 _attendance_case()),
        EvalCase("vertical.homeschool.child_safe_tutor", "vertical",
                 "Complete graded answers are blocked while formative help remains available.",
                 _tutor_case()),
        EvalCase("vertical.homeschool.private_collaboration", "vertical",
                 "Tutor access is learner/course scoped and excludes financial data.",
                 _collaboration_case()),
        EvalCase("vertical.homeschool.transcript_provenance", "vertical",
                 "Transcript is evidence-backed and parent-issued without accreditation claims.",
                 _transcript_case()),
    ]


def register() -> None:
    register_vertical_spec(_HOMESCHOOL_SPEC)
    register_vertical_eval_cases(_manual_cases)