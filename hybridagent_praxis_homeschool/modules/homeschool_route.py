"""Legal-route classification and migration gate for parent home education.

Praxis may explain available routes, but only the accountable parent can confirm
one.  Public virtual and cyber-charter enrollment are deliberately rejected as
homeschool routes because the school remains the school of record.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from .homeschool_jurisdictions import (
    HomeschoolProfile,
    get_homeschool_profile,
    profile_for_route,
)
from .homeschool_validation import iso_date

NON_HOMESCHOOL_ROUTES = frozenset({
    "public_virtual", "public_online_school", "cyber_charter",
    "district_remote", "full_time_public_school",
})
OUT_OF_PACK_ROUTES = frozenset({"microschool"})


@dataclass(frozen=True)
class RouteFinding:
    code: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class RouteSelection:
    state: str
    route: str
    confirmed_by_parent: bool
    effective_date: str
    district_enrolled: bool = False
    school_of_record: str = "parent"
    oversight_entity: str = ""
    source_version: str = "2026-07-18"


@dataclass(frozen=True)
class RouteDecision:
    selection: RouteSelection
    profile: HomeschoolProfile | None
    findings: tuple[RouteFinding, ...]

    @property
    def allowed(self) -> bool:
        return self.profile is not None and not any(f.blocking for f in self.findings)

    def require_allowed(self) -> RouteSelection:
        if not self.allowed:
            text = "; ".join(f.message for f in self.findings) or "route not allowed"
            raise ValueError(text)
        return self.selection


@dataclass(frozen=True)
class RouteMigration:
    previous: RouteSelection
    next: RouteSelection
    frozen_profile_verified_on: str
    requires_new_notice: bool
    checklist: tuple[str, ...]


def available_routes(state: str) -> tuple[str, ...]:
    profile = get_homeschool_profile(state)
    return profile.routes if profile else ()


def evaluate_route(selection: RouteSelection) -> RouteDecision:
    findings: list[RouteFinding] = []
    profile = get_homeschool_profile(selection.state)
    route = selection.route.strip().lower() if isinstance(selection.route, str) else ""

    if profile is None:
        findings.append(RouteFinding("unsupported_state", "No verified homeschool profile exists for this state."))
        return RouteDecision(selection, None, tuple(findings))
    school_of_record = selection.school_of_record.strip().lower() or "parent"
    if route == "church_related_school" and school_of_record in {"parent", "church_related_school"}:
        school_of_record = "church_related_school"
    elif route == "private_school_umbrella" and school_of_record in {"parent", "private_school"}:
        school_of_record = "private_school"
    canonical = replace(
        selection, state=profile.state, route=route,
        school_of_record=school_of_record,
        oversight_entity=selection.oversight_entity.strip(),
    )
    if not route:
        findings.append(RouteFinding("route_required", "The parent must choose and confirm a legal route."))
    elif route in NON_HOMESCHOOL_ROUTES:
        findings.append(RouteFinding(
            "public_school_not_homeschool",
            "A public virtual/cyber school remains the school of record and cannot be treated as independent homeschool.",
        ))
    elif route in OUT_OF_PACK_ROUTES:
        findings.append(RouteFinding(
            "separate_product_boundary",
            "Microschool administration is not household homeschool; use a separately governed operator workflow.",
        ))
    elif route not in profile.routes:
        findings.append(RouteFinding(
            "route_not_available",
            f"Route '{route}' is not registered for {profile.state}; choose from {', '.join(profile.routes)}.",
        ))

    if selection.confirmed_by_parent is not True:
        findings.append(RouteFinding(
            "parent_confirmation_required",
            "Praxis may compare routes but cannot choose the family's legal status.",
        ))
    if selection.district_enrolled is True:
        findings.append(RouteFinding(
            "district_enrollment_conflict",
            "District enrollment conflicts with an independent home-education route; resolve school-of-record status.",
        ))
    if school_of_record not in {
            "parent", "public_school", "private_school", "church_related_school"}:
        findings.append(RouteFinding(
            "school_of_record_invalid", "School of record must use a registered classification."))
    if school_of_record == "public_school" and route not in NON_HOMESCHOOL_ROUTES:
        findings.append(RouteFinding(
            "school_of_record_conflict",
            "The public school is marked as school of record while a homeschool route is selected.",
        ))
    if school_of_record == "private_school" and route != "private_school_umbrella":
        findings.append(RouteFinding(
            "school_of_record_conflict",
            "A private school is marked as school of record outside the private-school umbrella route.",
        ))
    if school_of_record == "church_related_school" and route != "church_related_school":
        findings.append(RouteFinding(
            "school_of_record_conflict",
            "A church-related school is marked as school of record outside that supervised route.",
        ))
    try:
        iso_date(selection.effective_date, "effective_date")
    except ValueError as exc:
        findings.append(RouteFinding("effective_date_invalid", str(exc)))
    try:
        iso_date(selection.source_version, "source_version")
    except ValueError as exc:
        findings.append(RouteFinding("source_version_invalid", str(exc)))
    route_profile = profile_for_route(profile.state, route) or profile
    if route_profile.confidence != "primary_source":
        findings.append(RouteFinding(
            "primary_verification_required",
            f"{profile.state} route data is {route_profile.confidence}; current primary text must be verified before filing.",
            blocking=False,
        ))
    if (profile.state == "SC" and route in {"option2_scaihs", "option3_association"}
            and not canonical.oversight_entity):
        findings.append(RouteFinding(
            "association_required", "The selected South Carolina route requires a named oversight association."))
    if (profile.state == "TN" and route == "church_related_school"
            and not canonical.oversight_entity):
        findings.append(RouteFinding(
            "umbrella_required", "The church-related-school route requires the supervising school."))
    oversight_routes = {
        ("FL", "private_school_umbrella"), ("FL", "pep_scholarship"),
        ("MD", "nonpublic_supervision"), ("PA", "private_tutor"),
    }
    if (profile.state, route) in oversight_routes and not canonical.oversight_entity:
        findings.append(RouteFinding(
            "oversight_required", "The selected route requires a named supervising organization or tutor."))
    return RouteDecision(canonical, route_profile, tuple(findings))


def migrate_route(previous: RouteSelection, next_selection: RouteSelection) -> RouteMigration:
    """Freeze a prior-year route and generate a parent-facing migration checklist."""
    previous_decision = evaluate_route(previous)
    previous = previous_decision.require_allowed()
    prev_profile = previous_decision.profile
    assert prev_profile is not None
    next_decision = evaluate_route(next_selection)
    next_selection = next_decision.require_allowed()
    changed_state = previous.state != next_selection.state
    changed_route = previous.route != next_selection.route
    checklist = ["preserve prior-year records and source version"]
    if changed_state:
        checklist.extend(("send parent-approved termination/move notice if required",
                          "create a new state compliance calendar"))
    if changed_route:
        checklist.append("confirm new oversight and school-of-record responsibilities")
    checklist.append("retain delivery receipts; Praxis does not file automatically")
    return RouteMigration(
        previous=previous,
        next=next_selection,
        frozen_profile_verified_on=previous.source_version,
        requires_new_notice=changed_state or changed_route,
        checklist=tuple(checklist),
    )


def new_selection(state: str, route: str, *, confirmed_by_parent: bool,
                  effective_date: str | None = None,
                  district_enrolled: bool = False,
                  school_of_record: str = "parent",
                  oversight_entity: str = "",
                  source_version: str = "2026-07-18") -> RouteSelection:
    """Convenience constructor using an ISO date without inferring a route."""
    value = effective_date or date.today().isoformat()
    return RouteSelection(
        state=state.upper(), route=route,
        confirmed_by_parent=confirmed_by_parent, effective_date=value,
        district_enrolled=district_enrolled, school_of_record=school_of_record,
        oversight_entity=oversight_entity, source_version=source_version,
    )
