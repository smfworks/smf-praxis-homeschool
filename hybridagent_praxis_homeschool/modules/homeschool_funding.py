"""Optional homeschool scholarship/ESA expense and audit support.

Funding never determines homeschool legal status.  Eligibility is source-versioned,
uncertainty is explicit, and reimbursement submission is absent from this module.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Literal

from .homeschool_jurisdictions import get_homeschool_profile
from .homeschool_validation import iso_date, valid_sha256

Eligibility = Literal["eligible", "ineligible", "uncertain"]


@dataclass(frozen=True)
class FundingProgram:
    program_id: str
    state: str
    name: str
    eligible_categories: tuple[str, ...]
    approved_vendors: tuple[str, ...]
    award_start: str
    award_end: str
    source_url: str
    verified_on: str
    rules_complete: bool = False


@dataclass(frozen=True)
class FundingEligibility:
    eligibility_id: str
    learner_id: str
    program_id: str
    account_id: str
    parent_id: str
    award_year: str
    source_verified_on: str
    determined_at: float
    expires_at: float
    parent_confirmed: bool
    program_policy_hash: str
    determination_hash: str


def _canonical_hash(payload: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def funding_program_hash(program: FundingProgram) -> str:
    payload = {
        "schema": "praxis.funding-program.v1",
        "program_id": program.program_id,
        "state": program.state,
        "name": program.name,
        "eligible_categories": sorted(program.eligible_categories),
        "approved_vendors": sorted(program.approved_vendors),
        "award_start": program.award_start,
        "award_end": program.award_end,
        "source_url": program.source_url,
        "verified_on": program.verified_on,
        "rules_complete": program.rules_complete,
    }
    return _canonical_hash(payload)


def funding_eligibility_hash(eligibility: FundingEligibility) -> str:
    payload = {
        "schema": "praxis.funding-eligibility.v1",
        "eligibility_id": eligibility.eligibility_id,
        "learner_id": eligibility.learner_id,
        "program_id": eligibility.program_id,
        "account_id": eligibility.account_id,
        "parent_id": eligibility.parent_id,
        "award_year": eligibility.award_year,
        "source_verified_on": eligibility.source_verified_on,
        "determined_at": eligibility.determined_at,
        "expires_at": eligibility.expires_at,
        "parent_confirmed": eligibility.parent_confirmed,
        "program_policy_hash": eligibility.program_policy_hash,
    }
    return _canonical_hash(payload)


@dataclass(frozen=True)
class Expense:
    expense_id: str
    learner_id: str
    program_id: str
    vendor: str
    category: str
    amount: Decimal
    purchased_on: str
    receipt_hash: str
    invoice_hash: str = ""
    attested_by_parent: str = ""
    parent_attested: bool = False


@dataclass(frozen=True)
class ExpenseDecision:
    eligibility: Eligibility
    findings: tuple[str, ...]


@dataclass(frozen=True)
class ReimbursementExpense:
    expense_id: str
    learner_id: str
    program_id: str
    vendor: str
    category: str
    amount: Decimal
    purchased_on: str
    receipt_hash: str
    invoice_hash: str
    attested_by_parent: str
    parent_attested: bool


@dataclass(frozen=True)
class ReimbursementPacket:
    packet_id: str
    learner_id: str
    account_id: str
    eligibility_id: str
    determination_hash: str
    program_id: str
    state: str
    program_policy_hash: str
    expense_ids: tuple[str, ...]
    expense_manifest: tuple[ReimbursementExpense, ...]
    total: Decimal
    source_verified_on: str
    approved_by_parent: str
    packet_hash: str
    status: str = "ready_for_parent_submission"
    receipt_id: str = ""
    submitted_at: float = 0.0


def _money(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("amount must not be boolean")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount must be decimal") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("amount must be finite and positive")
    exponent = result.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise ValueError("amount must have no more than two decimal places")
    quantized = result.quantize(Decimal("0.01"))
    if quantized < Decimal("0.01"):
        raise ValueError("amount must be at least one cent")
    return quantized


def _valid_time(value: object) -> bool:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not isfinite(value) or value <= 0):
        return False
    try:
        datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return False
    return True


def _expense_manifest_entry(expense: Expense) -> ReimbursementExpense:
    return ReimbursementExpense(
        expense_id=expense.expense_id,
        learner_id=expense.learner_id,
        program_id=expense.program_id,
        vendor=expense.vendor,
        category=expense.category,
        amount=_money(expense.amount),
        purchased_on=expense.purchased_on,
        receipt_hash=expense.receipt_hash,
        invoice_hash=expense.invoice_hash,
        attested_by_parent=expense.attested_by_parent,
        parent_attested=expense.parent_attested,
    )


def reimbursement_packet_hash(packet: ReimbursementPacket) -> str:
    payload = {
        "schema": "praxis.reimbursement-packet.v1",
        "packet_id": packet.packet_id,
        "learner_id": packet.learner_id,
        "account_id": packet.account_id,
        "eligibility_id": packet.eligibility_id,
        "determination_hash": packet.determination_hash,
        "program_id": packet.program_id,
        "state": packet.state,
        "program_policy_hash": packet.program_policy_hash,
        "expense_ids": list(packet.expense_ids),
        "expense_manifest": [
            {
                "expense_id": item.expense_id,
                "learner_id": item.learner_id,
                "program_id": item.program_id,
                "vendor": item.vendor,
                "category": item.category,
                "amount": str(item.amount),
                "purchased_on": item.purchased_on,
                "receipt_hash": item.receipt_hash,
                "invoice_hash": item.invoice_hash,
                "attested_by_parent": item.attested_by_parent,
                "parent_attested": item.parent_attested,
            }
            for item in packet.expense_manifest
        ],
        "total": str(packet.total),
        "source_verified_on": packet.source_verified_on,
        "approved_by_parent": packet.approved_by_parent,
    }
    return _canonical_hash(payload)


def _validate_program(program: FundingProgram) -> None:
    if not program.program_id.strip() or not program.name.strip() or not program.source_url.strip():
        raise ValueError("program identity, name, and source are required")
    if (program.state != program.state.strip().upper()
            or get_homeschool_profile(program.state) is None):
        raise ValueError("program state must be a canonical supported homeschool jurisdiction")
    award_start = iso_date(program.award_start, "award_start")
    award_end = iso_date(program.award_end, "award_end")
    iso_date(program.verified_on, "verified_on")
    if award_end < award_start:
        raise ValueError("award_end must not precede award_start")
    if (not program.eligible_categories
            or any(not item.strip() for item in program.eligible_categories)
            or len(set(program.eligible_categories)) != len(program.eligible_categories)
            or any(not item.strip() for item in program.approved_vendors)
            or len(set(program.approved_vendors)) != len(program.approved_vendors)):
        raise ValueError("program categories and vendors must be unique and nonempty")
    if program.rules_complete is not True and program.rules_complete is not False:
        raise ValueError("rules_complete must be a literal boolean")


def classify_expense(program: FundingProgram, expense: Expense, *,
                     eligibility: FundingEligibility, now: float) -> ExpenseDecision:
    findings: list[str] = []
    _validate_program(program)
    award_start = iso_date(program.award_start, "award_start")
    award_end = iso_date(program.award_end, "award_end")
    iso_date(program.verified_on, "verified_on")
    if award_end < award_start:
        raise ValueError("award_end must not precede award_start")
    if expense.program_id != program.program_id:
        return ExpenseDecision("ineligible", ("Expense is bound to a different program.",))
    _money(expense.amount)
    if (not eligibility.eligibility_id.strip() or not eligibility.account_id.strip()
            or not eligibility.parent_id.strip()
            or eligibility.program_id != program.program_id
            or eligibility.learner_id != expense.learner_id
            or eligibility.award_year != f"{award_start.year}-{award_end.year}"
            or eligibility.source_verified_on != program.verified_on
            or eligibility.parent_confirmed is not True
            or eligibility.program_policy_hash != funding_program_hash(program)
            or not valid_sha256(eligibility.determination_hash)
            or eligibility.determination_hash != funding_eligibility_hash(eligibility)):
        return ExpenseDecision("uncertain", ("A bound source-versioned learner eligibility record is required.",))
    if (not _valid_time(now) or not _valid_time(eligibility.determined_at)
            or not _valid_time(eligibility.expires_at)
            or not eligibility.determined_at <= now <= eligibility.expires_at
            or eligibility.expires_at - eligibility.determined_at > 366 * 24 * 60 * 60):
        return ExpenseDecision("uncertain", ("Learner eligibility is stale, future-dated, or overlong.",))
    now_date = datetime.fromtimestamp(now, tz=timezone.utc).date()
    verified = iso_date(program.verified_on, "verified_on")
    if verified > now_date:
        return ExpenseDecision("uncertain", ("Program source verification is future-dated.",))
    if (expense.parent_attested is not True
            or expense.attested_by_parent.strip() != eligibility.parent_id
            or not valid_sha256(expense.receipt_hash)):
        return ExpenseDecision("ineligible", ("Parent-attested receipt provenance is required.",))
    if expense.invoice_hash and not valid_sha256(expense.invoice_hash):
        return ExpenseDecision("ineligible", ("Invoice hash is not a canonical SHA-256 reference.",))
    purchased_on = iso_date(expense.purchased_on, "purchased_on")
    if purchased_on < award_start or purchased_on > award_end:
        return ExpenseDecision("ineligible", ("Purchase date is outside the award period.",))
    if expense.category not in program.eligible_categories:
        return ExpenseDecision("ineligible", ("Expense category is not listed as eligible.",))
    if program.approved_vendors and expense.vendor not in program.approved_vendors:
        findings.append("Vendor is not in the source-versioned approved-vendor list.")
    if program.rules_complete is not True:
        findings.append("Program rules are incomplete or require current eligibility verification.")
    if findings:
        return ExpenseDecision("uncertain", tuple(findings))
    return ExpenseDecision("eligible", ())


class FundingLedger:
    def __init__(self, program: FundingProgram, *, award_amount: Decimal,
                 eligibility: FundingEligibility, now: float) -> None:
        self.program = program
        self.award_amount = _money(award_amount)
        self.eligibility = eligibility
        self._now = now
        self._expenses: dict[str, Expense] = {}
        self._receipt_hashes: set[str] = set()
        self._invoice_hashes: set[str] = set()
        self._packets: dict[str, ReimbursementPacket] = {}
        self._committed_expense_ids: set[str] = set()
        self._submission_receipt_ids: set[str] = set()

    def append(self, expense: Expense, *, receipt_content: bytes,
               invoice_content: bytes | None = None) -> ExpenseDecision:
        if expense.expense_id in self._expenses:
            raise ValueError("expense identity is immutable")
        if not expense.expense_id or not expense.learner_id or not expense.vendor.strip():
            raise ValueError("expense, learner, and vendor identities are required")
        if not receipt_content:
            raise ValueError("receipt content must be nonempty")
        actual_receipt = "sha256:" + hashlib.sha256(receipt_content).hexdigest()
        if expense.receipt_hash != actual_receipt:
            raise ValueError("receipt hash does not match the ingested receipt")
        if expense.invoice_hash:
            if invoice_content is None:
                raise ValueError("invoice content is required when an invoice hash is recorded")
            actual_invoice = "sha256:" + hashlib.sha256(invoice_content).hexdigest()
            if expense.invoice_hash != actual_invoice:
                raise ValueError("invoice hash does not match the ingested invoice")
        elif invoice_content is not None:
            raise ValueError("invoice hash is required when invoice content is supplied")
        if expense.receipt_hash in self._receipt_hashes:
            raise ValueError("receipt hash is already recorded")
        if expense.invoice_hash and expense.invoice_hash in self._invoice_hashes:
            raise ValueError("invoice hash is already recorded")
        decision = classify_expense(
            self.program, expense, eligibility=self.eligibility, now=self._now,
        )
        self._expenses[expense.expense_id] = expense
        self._receipt_hashes.add(expense.receipt_hash)
        if expense.invoice_hash:
            self._invoice_hashes.add(expense.invoice_hash)
        return decision

    def balance(self, *, include_uncertain: bool = False) -> Decimal:
        used = Decimal("0")
        for expense in self._expenses.values():
            decision = classify_expense(
                self.program, expense, eligibility=self.eligibility, now=self._now,
            )
            if decision.eligibility == "eligible" or (
                    include_uncertain and decision.eligibility == "uncertain"):
                used += _money(expense.amount)
        return max(Decimal("0"), self.award_amount - used).quantize(Decimal("0.01"))

    @staticmethod
    def _manifest_entry(expense: Expense) -> ReimbursementExpense:
        return _expense_manifest_entry(expense)

    def _validate_packet(self, packet: ReimbursementPacket, *, expected_id: str) -> None:
        eligibility = self.eligibility
        try:
            expenses = tuple(self._expenses[item] for item in packet.expense_ids)
        except KeyError as exc:
            raise ValueError("reimbursement packet references an unknown expense") from exc
        expected_manifest = tuple(self._manifest_entry(item) for item in expenses)
        expected_total = sum((item.amount for item in expected_manifest), Decimal("0"))
        if (packet.packet_id != expected_id
                or not packet.expense_ids
                or len(set(packet.expense_ids)) != len(packet.expense_ids)
                or packet.program_id != self.program.program_id
                or packet.state != self.program.state
                or packet.program_policy_hash != funding_program_hash(self.program)
                or packet.source_verified_on != self.program.verified_on
                or packet.learner_id != eligibility.learner_id
                or packet.account_id != eligibility.account_id
                or packet.eligibility_id != eligibility.eligibility_id
                or packet.determination_hash != eligibility.determination_hash
                or eligibility.determination_hash != funding_eligibility_hash(eligibility)
                or eligibility.parent_confirmed is not True
                or eligibility.program_policy_hash != funding_program_hash(self.program)
                or packet.approved_by_parent != eligibility.parent_id
                or packet.expense_manifest != expected_manifest
                or packet.expense_ids != tuple(item.expense_id for item in expected_manifest)
                or packet.total != expected_total
                or not valid_sha256(packet.packet_hash)
                or packet.packet_hash != reimbursement_packet_hash(packet)):
            raise ValueError("reimbursement packet integrity binding is invalid")
        if any(classify_expense(
            self.program, item, eligibility=eligibility, now=self._now,
        ).eligibility != "eligible" for item in expenses):
            raise ValueError("reimbursement packet contains an ineligible expense")

    def build_packet(self, expense_ids: tuple[str, ...], *, packet_id: str,
                     approved_by_parent: str) -> ReimbursementPacket:
        packet_id = packet_id.strip()
        approved_by_parent = approved_by_parent.strip()
        if not packet_id or not approved_by_parent:
            raise PermissionError("packet identity and parent approval are required")
        if approved_by_parent != self.eligibility.parent_id:
            raise PermissionError("packet approval must come from the eligible learner's parent")
        if packet_id in self._packets:
            raise ValueError("reimbursement packet identity is immutable")
        if not expense_ids or len(set(expense_ids)) != len(expense_ids):
            raise ValueError("a unique nonempty expense set is required")
        selected: list[Expense] = []
        for expense_id in expense_ids:
            if expense_id in self._committed_expense_ids:
                raise ValueError("expense is already committed to a reimbursement packet")
            try:
                expense = self._expenses[expense_id]
            except KeyError as exc:
                raise KeyError("unknown expense") from exc
            decision = classify_expense(
                self.program, expense, eligibility=self.eligibility, now=self._now,
            )
            if decision.eligibility != "eligible":
                raise ValueError("only source-verified eligible expenses enter a packet")
            selected.append(expense)
        total = sum((_money(x.amount) for x in selected), Decimal("0"))
        committed = sum((packet.total for packet in self._packets.values()
                         if packet.status != "cancelled"), Decimal("0"))
        if committed + total > self.award_amount:
            raise ValueError("reimbursement packets exceed the award amount")
        packet = ReimbursementPacket(
            packet_id=packet_id, program_id=self.program.program_id,
            state=self.program.state, program_policy_hash=funding_program_hash(self.program),
            expense_ids=expense_ids, total=total,
            source_verified_on=self.program.verified_on,
            approved_by_parent=approved_by_parent,
            learner_id=self.eligibility.learner_id,
            account_id=self.eligibility.account_id,
            eligibility_id=self.eligibility.eligibility_id,
            determination_hash=self.eligibility.determination_hash,
            expense_manifest=tuple(self._manifest_entry(item) for item in selected),
            packet_hash="",
        )
        packet = replace(packet, packet_hash=reimbursement_packet_hash(packet))
        self._packets[packet_id] = packet
        self._committed_expense_ids.update(expense_ids)
        return packet

    def cancel_packet(self, packet_id: str, *, parent_id: str) -> ReimbursementPacket:
        try:
            packet = self._packets[packet_id]
        except KeyError as exc:
            raise KeyError("unknown reimbursement packet") from exc
        if packet.status != "ready_for_parent_submission":
            raise ValueError("only a ready packet can be cancelled")
        if parent_id.strip() != packet.approved_by_parent:
            raise PermissionError("only the approving parent may cancel the packet")
        self._validate_packet(packet, expected_id=packet_id)
        cancelled = replace(packet, status="cancelled")
        self._packets[packet_id] = cancelled
        self._committed_expense_ids.difference_update(packet.expense_ids)
        return cancelled

    def record_submission_receipt(self, packet_id: str, *, parent_id: str,
                                  receipt_id: str, submitted_at: float) -> ReimbursementPacket:
        try:
            packet = self._packets[packet_id]
        except KeyError as exc:
            raise KeyError("unknown reimbursement packet") from exc
        if packet.status != "ready_for_parent_submission":
            raise ValueError("packet is not ready for an external receipt")
        self._validate_packet(packet, expected_id=packet_id)
        canonical_receipt = receipt_id.strip()
        if parent_id.strip() != packet.approved_by_parent or not canonical_receipt:
            raise PermissionError("approving parent and external receipt are required")
        if canonical_receipt in self._submission_receipt_ids:
            raise ValueError("submission receipt identity is already recorded")
        if (not _valid_time(submitted_at) or submitted_at < self._now
                or submitted_at > self.eligibility.expires_at):
            raise ValueError("valid submission receipt timestamp required")
        recorded = replace(packet, status="receipt_recorded", receipt_id=canonical_receipt,
                           submitted_at=float(submitted_at))
        self._packets[packet_id] = recorded
        self._submission_receipt_ids.add(canonical_receipt)
        return recorded


def submit_reimbursement(_: ReimbursementPacket) -> None:
    raise PermissionError("Funding claims are SEND-held; this module never submits them.")
