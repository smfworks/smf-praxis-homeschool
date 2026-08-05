"""Child-safe, parent-visible tutoring and assessment-integrity policy."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from .homeschool_validation import valid_sha256

TutorMode = Literal["formative", "practice", "summative", "graded_homework"]
TUTOR_MODES = frozenset({"formative", "practice", "summative", "graded_homework"})


@dataclass(frozen=True)
class TutorRequest:
    session_id: str
    learner_id: str
    age: int
    mode: TutorMode
    prompt: str
    asks_for_complete_answer: bool = False
    parent_visible: bool = True
    external_contact_requested: bool = False
    purchase_requested: bool = False
    public_post_requested: bool = False


@dataclass(frozen=True)
class TutorDecision:
    allowed: bool
    strategy: str
    findings: tuple[str, ...]
    parent_review_required: bool
    preserve_learner_authorship: bool = True
    learner_id: str = ""
    session_id: str = ""
    submission_id: str = ""
    draft_hash: str = ""
    ai_edit_provenance: str = ""


def assess_tutor_request(request: TutorRequest) -> TutorDecision:
    if not request.session_id or not request.learner_id or not request.prompt.strip():
        raise ValueError("session, learner, and prompt are required")
    if (not isinstance(request.age, int) or isinstance(request.age, bool)
            or request.age < 3 or request.age > 21):
        raise ValueError("age is outside the supported education range")
    if request.mode not in TUTOR_MODES:
        raise ValueError("tutor mode must be formative, practice, summative, or graded_homework")
    escalate, message = safety_escalation(request.prompt)
    if escalate:
        return TutorDecision(
            False, "pause_for_immediate_human_help", (message,), True,
            learner_id=request.learner_id, session_id=request.session_id,
        )
    findings: list[str] = []
    allowed = True
    strategy = "guided_questions_then_hint_then_explanation"

    if request.mode in {"summative", "graded_homework"} and request.asks_for_complete_answer:
        allowed = False
        strategy = "refuse_final_answer_offer_conceptual_hint"
        findings.append("Complete answers are blocked on summative or graded work.")
    elif request.asks_for_complete_answer:
        strategy = "worked_analogy_then_learner_attempt"
        findings.append("Use a parallel example; require the learner to produce the submitted answer.")

    if request.parent_visible is not True:
        allowed = False
        findings.append("Child tutoring sessions must remain parent-visible.")
    if request.external_contact_requested:
        allowed = False
        findings.append("A child may not autonomously contact an unknown adult or external account.")
    if request.purchase_requested:
        allowed = False
        findings.append("Purchases require parent approval outside the tutoring session.")
    if request.public_post_requested:
        allowed = False
        findings.append("A learner may not autonomously publish content externally.")
    if request.age < 13:
        findings.append("Under-13 interaction is parent-mediated; no direct account creation or profiling.")
    return TutorDecision(allowed, strategy, tuple(findings), parent_review_required=True)


@dataclass(frozen=True)
class AuthorshipCheck:
    learner_draft_present: bool
    sources_cited: bool
    detector_only_claim: bool = False
    ai_rewrote_submission: bool = False
    learner_id: str = ""
    session_id: str = ""
    submission_id: str = ""
    draft_hash: str = ""
    ai_edit_provenance: str = "none"


@dataclass(frozen=True)
class AuthorshipRecord:
    learner_id: str
    session_id: str
    submission_id: str
    draft_hash: str


class AuthorshipLedger:
    """Immutable trusted binding between a submission and its exact draft bytes."""

    def __init__(self) -> None:
        self._records: dict[str, AuthorshipRecord] = {}

    def register(self, *, learner_id: str, session_id: str, submission_id: str,
                 draft_content: bytes) -> AuthorshipRecord:
        learner_id = learner_id.strip()
        session_id = session_id.strip()
        submission_id = submission_id.strip()
        if not all((learner_id, session_id, submission_id)) or not draft_content:
            raise ValueError("authorship binding requires identities and nonempty draft bytes")
        if submission_id in self._records:
            raise ValueError("authorship submission identity is immutable")
        record = AuthorshipRecord(
            learner_id, session_id, submission_id,
            "sha256:" + hashlib.sha256(draft_content).hexdigest(),
        )
        self._records[submission_id] = record
        return record

    def get(self, submission_id: str) -> AuthorshipRecord:
        try:
            return self._records[submission_id.strip()]
        except KeyError as exc:
            raise KeyError("unknown authorship submission") from exc


def check_authorship(
        check: AuthorshipCheck, *, draft_content: bytes,
        authorship_ledger: AuthorshipLedger | None = None) -> TutorDecision:
    findings: list[str] = []
    allowed = True
    if (not check.learner_id.strip() or not check.session_id.strip()
            or not check.submission_id.strip() or not valid_sha256(check.draft_hash)):
        allowed = False
        findings.append("Authorship review must bind learner, session, submission, and draft hash.")
    if (not draft_content or check.draft_hash
            != "sha256:" + hashlib.sha256(draft_content).hexdigest()):
        allowed = False
        findings.append("Draft hash must be recomputed from the reviewed learner draft bytes.")
    try:
        trusted = authorship_ledger.get(check.submission_id) if authorship_ledger else None
    except KeyError:
        trusted = None
    if (trusted is None
            or check.learner_id != trusted.learner_id
            or check.session_id != trusted.session_id
            or check.submission_id != trusted.submission_id
            or check.draft_hash != trusted.draft_hash):
        allowed = False
        findings.append(
            "Authorship identifiers and draft hash must match the immutable trusted submission record."
        )
    if check.ai_edit_provenance not in {
            "none", "coaching", "grammar_edit", "source_suggestions"}:
        allowed = False
        findings.append("AI edit provenance is not a recognized transparent category.")
    if not check.learner_draft_present:
        allowed = False
        findings.append("No learner-authored draft is present.")
    if check.ai_rewrote_submission:
        allowed = False
        findings.append("AI may coach or edit transparently, not replace learner authorship.")
    if not check.sources_cited:
        allowed = False
        findings.append("Add source attribution before parent review.")
    if check.detector_only_claim:
        findings.append("Detector output alone cannot establish misconduct or AI authorship.")
    return TutorDecision(
        allowed, "parent_review_of_authorship", tuple(findings), True,
        learner_id=check.learner_id, session_id=check.session_id,
        submission_id=check.submission_id, draft_hash=check.draft_hash,
        ai_edit_provenance=check.ai_edit_provenance,
    )


def safety_escalation(text: str) -> tuple[bool, str]:
    """Pause tutoring on explicit safety language without diagnosing or reporting.

    This deterministic layer is intentionally conservative and is not a crisis
    classifier. It routes the learner to immediate human help and avoids
    defaulting to a parent when the disclosure may implicate the home.
    """
    lower = " ".join(text.lower().split())
    self_harm = (
        r"\b(suicid(?:e|al)|self[- ]?harm)\b",
        r"\b(kill|hurt|cut) myself\b",
        r"\b(?:end my life|end it all|take my life|overdose)\b",
        r"\b(?:do not|don't) want to (?:live|be alive)\b",
        r"\b(?:better off dead|can't go on)\b",
        r"\b(?:want|wish|plan|planning|going) to die\b",
        r"\b(?:am |i'm )?(?:cutting|harming|hurting) myself\b",
        r"\b(?:am |i'm )?(?:cutting|harming|hurting) my (?:wrist|wrists|arm|arms)\b",
    )
    violence = (
        (r"\b(?:will|want to|plan to|going to)? ?(?:kill|shoot|stab|hurt|seriously hurt) "
        r"(?:someone|him|her|them|my|the|a)\b"),
        r"\bbring(?:ing)? (?:a )?(?:gun|knife|weapon|bomb)\b",
    )
    home_abuse = (
        r"\bunsafe at home\b", r"\babuse[sd]?\b", r"\bhurt(?:s|ing)? me\b",
        r"\b(?:hits|beats|chokes|molests) me\b", r"\b(?:molested|raped) me\b",
        (r"\b(?:hit|hits|hitting|punch(?:ed|es|ing)?|beat(?:s|ing)?|chok(?:ed|es|ing)|"
        r"slap(?:ped|s|ping)?|kick(?:ed|s|ing)?) me\b"),
        (r"\b(?:threatened|threatens|threatening|plans?|wants?|going|will) "
        r"(?:to )?(?:hurt|kill|shoot|stab) me\b"),
        r"\b(?:touch|touches|touched) me (?:there|sexually|inappropriately)\b",
        r"\bi (?:was|am being) touched (?:sexually|inappropriately)\b",
        r"\b(?:forced|forces|forcing|threatened|threatens) me\b",
        (r"\b(?:my )?(?:dad|mom|father|mother|parent|guardian|caregiver|family member) "
        r"(?:hit|hits|punched|punches|beat|beats|choked|chokes) me\b"),
        (r"\b(?:my )?(?:step(?:dad|mom|father|mother|parent)|foster (?:father|mother|parent)|"
        r"dad|mom|father|mother|parent|guardian|caregiver|family member) "
        r"(?:(?:says?|said) (?:he|she|they) (?:will|would|might) )?"
        r"(?:hit|hits|hitting|punch(?:ed|es|ing)?|beat(?:s|ing)?|chok(?:ed|es|ing)|"
        r"slap(?:ped|s|ping)?|kick(?:ed|s|ing)?|kill(?:s|ing)?) me\b"),
        (r"\b(?:someone|somebody|a person) at home (?:is )?"
        r"(?:hit(?:s|ting)?|beat(?:s|ing)?|slap(?:s|ping)?|kick(?:s|ing)?) me\b"),
        (r"\b(?:my )?(?:dad|mom|father|mother|parent|guardian|caregiver|family member) "
        r"(?:is )?(?:touching|touches|touched) me(?: inappropriately| sexually)?\b"),
        r"\bafraid of (?:my )?(?:parent|guardian|caregiver|family)\b",
    )
    household_danger = any(re.search(pattern, lower) for pattern in home_abuse)
    direct_danger = any(re.search(pattern, lower) for pattern in self_harm + violence)
    if household_danger:
        return True, (
            "Pause tutoring and contact a trusted safe adult outside the potentially involved "
            "household member. If there is immediate danger, contact local emergency services. "
            "Praxis does not investigate or file a report."
        )
    if direct_danger:
        return True, (
            "Pause tutoring. If anyone may be in immediate danger, contact local emergency "
            "services now and stay with a trusted safe adult. Tell a trusted adult who is not "
            "involved in the danger. Praxis does not diagnose, investigate, or file a report."
        )
    return False, ""
