"""Source-versioned home-education profiles for the governed ``homeschool`` pack.

Home education is not institutional K-12.  These profiles describe the parent-
operated legal route and intentionally do not reuse :class:`EducationProfile`.
Every obligation carries a source, confidence, and verification date so product
code can distinguish law from agency recommendation and unresolved research.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

Confidence = Literal["primary_source", "mixed", "established_knowledge"]


@dataclass(frozen=True)
class HomeschoolProfile:
    state: str
    state_name: str
    routes: tuple[str, ...]
    default_route: str
    compulsory_age_start: int
    compulsory_age_end: int
    initial_notice_days: int = 0
    notice_days_before_start: int = 0
    annual_notice_date: str = ""
    approval_required: bool = False
    parent_qualification: str = "none"
    required_subjects: tuple[str, ...] = ()
    instruction_days: int = 0
    instruction_hours_per_day: float = 0.0
    instruction_hours_elementary: int = 0
    instruction_hours_secondary: int = 0
    portfolio_required: bool = False
    portfolio_retention_years: int = 0
    progress_reports_per_year: int = 0
    assessment_frequency_years: int = 0
    assessment_grades: tuple[int, ...] = ()
    assessment_submission_date: str = ""
    requirements_defined_by_oversight: bool = False
    diploma_note: str = "parent-issued; verify recipient requirements"
    source_citation: str = ""
    source_url: str = ""
    confidence: Confidence = "primary_source"
    verified_on: str = "2026-07-18"
    notes: tuple[str, ...] = ()


PROFILES: dict[str, HomeschoolProfile] = {
    "FL": HomeschoolProfile(
        "FL", "Florida",
        ("independent_home_education", "private_school_umbrella", "pep_scholarship"),
        "independent_home_education", 6, 16, initial_notice_days=30,
        required_subjects=(), portfolio_required=True, portfolio_retention_years=2,
        assessment_frequency_years=1,
        source_citation="Fla. Stat. §1002.41 (2025)",
        source_url="https://www.leg.state.fl.us/Statutes/index.cfm?App_mode=Display_Statute&URL=1000-1099/1002/Sections/1002.41.html",
        notes=("Portfolio inspection requires 15 days' written notice.",
               "Annual evaluation has multiple statutory methods.",
               "Termination notice and final evaluation are due within 30 days."),
    ),
    "GA": HomeschoolProfile(
        "GA", "Georgia", ("home_study",), "home_study", 6, 16,
        initial_notice_days=30, annual_notice_date="09-01",
        parent_qualification="high_school_diploma_or_equivalent",
        required_subjects=("reading", "language_arts", "mathematics", "social_studies", "science"),
        instruction_days=180, instruction_hours_per_day=4.5,
        portfolio_retention_years=3, progress_reports_per_year=1,
        assessment_frequency_years=3, assessment_grades=(3, 6, 9, 12),
        source_citation="O.C.G.A. §§20-2-690, 20-2-690.1; GA DOE July 2025 guidance",
        source_url="https://gadoe.org/parent-family-resources/home-school/",
        notes=("Triennial nationally standardized testing begins after grade 3.",
               "Parent retains test results and annual progress reports."),
    ),
    "SC": HomeschoolProfile(
        "SC", "South Carolina", ("option1_district", "option2_scaihs", "option3_association"),
        "option3_association", 5, 17,
        approval_required=False, parent_qualification="high_school_diploma_or_equivalent",
        required_subjects=("reading", "writing", "mathematics", "science", "social_studies"),
        instruction_days=180, instruction_hours_per_day=4.5,
        portfolio_required=True, progress_reports_per_year=2,
        source_citation="S.C. Code §§59-65-40, 59-65-45, 59-65-47",
        source_url="https://ed.sc.gov/districts-schools/state-accountability/home-schooling/sc-code-of-law-59-65/",
        notes=("Option 1 requires district approval and statewide testing.",
               "Option 2 requires SCAIHS standing.",
               "Option 3 requires an association with at least 50 members."),
    ),
    "TN": HomeschoolProfile(
        "TN", "Tennessee", ("independent_home_school", "church_related_school"),
        "independent_home_school", 6, 18,
        parent_qualification="high_school_diploma_or_equivalent",
        instruction_days=180, instruction_hours_per_day=4.0,
        assessment_grades=(5, 7, 9),
        source_citation=("Tenn. Code Ann. §§49-6-3050, 49-50-801; "
                         "TDOE Independent Home School Requirements (Oct. 2023)"),
        source_url="https://www.tn.gov/education/families/school-options/home-schooling-in-tn.html",
        notes=("Independent initial registration may occur any time; renew before each school year.",
               "Independent attendance is submitted at year end and may be inspected.",
               "Church-related school owns recordkeeping/testing and issues transcript/diploma.",
               "An accredited online school is not Tennessee homeschool merely because it is remote."),
    ),
    "VA": HomeschoolProfile(
        "VA", "Virginia", ("home_instruction", "religious_exemption"), "home_instruction",
        5, 18, annual_notice_date="08-15",
        parent_qualification="one_of_four_statutory_paths",
        required_subjects=(), assessment_frequency_years=1,
        assessment_submission_date="08-01",
        source_citation="Va. Code §§22.1-254.1, 22.1-254(B)",
        source_url="https://law.lis.virginia.gov/vacode/title22.1/chapter14/section22.1-254.1/",
        notes=("Notice includes a subject list and qualification evidence.",
               "Religious exemption is a separate status, not a home-instruction sub-checklist."),
    ),
    "WV": HomeschoolProfile(
        "WV", "West Virginia",
        ("board_approved", "notice_home_instruction", "hope_individualized", "learning_pod"),
        "notice_home_instruction", 6, 17,
        parent_qualification="high_school_diploma_equivalent_or_qualifying_postsecondary_credential",
        required_subjects=("reading", "language", "mathematics", "science", "social_studies"),
        portfolio_retention_years=3, assessment_frequency_years=1,
        assessment_grades=(3, 5, 8, 11), assessment_submission_date="06-30",
        source_citation="W. Va. Code §18-8-1 (2026)",
        source_url="https://code.wvlegislature.gov/18-8-1/",
        notes=("Retain every annual assessment for three years.",
               "Hope Scholarship and pod routes require route-specific verification.",
               "Microschool administration is a separate product boundary, not household homeschool."),
    ),
    "MD": HomeschoolProfile(
        "MD", "Maryland", ("local_supervision", "nonpublic_supervision"),
        "local_supervision", 5, 18, notice_days_before_start=15,
        required_subjects=("english", "mathematics", "science", "social_studies", "art", "music", "health", "physical_education"),
        portfolio_required=True, progress_reports_per_year=2,
        source_citation="COMAR 13A.10.01",
        source_url="https://www.marylandpublicschools.org/about/Documents/DSFSS/SSSP/HomeInstruct/COMAR13A.10.01.pdf",
        notes=("Annual continuation verification is required.",
               "Local portfolio review occurs by semester, no more than three times per year."),
    ),
    "PA": HomeschoolProfile(
        "PA", "Pennsylvania", ("home_education", "private_tutor"), "home_education",
        6, 18, annual_notice_date="08-01",
        parent_qualification="high_school_diploma_or_equivalent_plus_statutory_household_conditions",
        required_subjects=("english", "spelling", "reading", "writing", "arithmetic", "science", "geography", "history", "civics", "safety", "health", "physical_education", "music", "art"),
        instruction_days=180, instruction_hours_elementary=900,
        instruction_hours_secondary=990, portfolio_required=True,
        progress_reports_per_year=1, assessment_grades=(3, 5, 8),
        source_citation="24 P.S. §§13-1327, 13-1327.1; PA DOE guide rev. May 2026",
        source_url="https://www.pa.gov/agencies/education/programs-and-services/instruction/elementary-and-secondary-education/home-education-and-private-tutoring",
        diploma_note="state-recognized only through qualifying statutory issuer/process",
        notes=("Annual qualified evaluator report is submitted to the superintendent.",
               "Public cyber charter is not home education."),
    ),
    "OH": HomeschoolProfile(
        "OH", "Ohio", ("home_education",), "home_education", 6, 18,
        initial_notice_days=5, annual_notice_date="08-30",
        required_subjects=("english_language_arts", "mathematics", "science", "history", "government", "social_studies"),
        source_citation="Ohio Rev. Code §3321.042; Ohio DOE current guidance",
        source_url="https://education.ohio.gov/Topics/Ohio-Education-Options/Home-Schooling",
        notes=("Use current post-2023 requirements; stale 900-hour/testing summaries are not encoded.",
               "Online community schools are public schools, not home education."),
    ),
    "NJ": HomeschoolProfile(
        "NJ", "New Jersey", ("equivalent_instruction_elsewhere",),
        "equivalent_instruction_elsewhere", 6, 16,
        required_subjects=(),
        source_citation="N.J.S.A. 18A:38-25; NJ DOE Homeschool FAQ",
        source_url="https://www.nj.gov/education/safety/nontraditional/faq_homeschool.shtml",
        diploma_note="no automatic district or state-endorsed diploma",
        notes=("Notice is prudent but not a universal statutory filing.",
               "District does not approve curriculum or routinely monitor outcomes."),
    ),
    "NY": HomeschoolProfile(
        "NY", "New York", ("home_instruction",), "home_instruction", 6, 16,
        initial_notice_days=14, annual_notice_date="07-01",
        required_subjects=("arithmetic", "reading", "spelling", "writing", "english", "geography", "us_history", "science", "health", "music", "visual_arts", "physical_education"),
        instruction_days=180, instruction_hours_elementary=900,
        instruction_hours_secondary=990, progress_reports_per_year=4,
        assessment_frequency_years=1,
        source_citation="8 NYCRR §100.10",
        source_url="https://www.nysed.gov/nonpublic-schools/home-instruction",
        diploma_note="home instruction does not produce a New York public-school diploma",
        notes=("IHIP, four quarterly reports, and annual assessment are required.",
               "Grade-band subjects and secondary unit-equivalent rules apply."),
    ),
    "CT": HomeschoolProfile(
        "CT", "Connecticut", ("equivalent_instruction_elsewhere",),
        "equivalent_instruction_elsewhere", 5, 18,
        required_subjects=("reading", "writing", "spelling", "english_grammar", "geography", "arithmetic", "us_history", "citizenship"),
        source_citation="Conn. Gen. Stat. §10-184; C-14/state guidance",
        source_url="https://portal.ct.gov/sde/homeschooling/homeschooling-in-connecticut",
        diploma_note="parent transcript is not a state-accredited credential",
        notes=("Notice, attendance logs, portfolios, and assessment evidence are recommended practices unless a binding source says otherwise.",
               "District may determine re-entry credit locally."),
    ),
    "MA": HomeschoolProfile(
        "MA", "Massachusetts", ("home_instruction_approved",),
        "home_instruction_approved", 6, 16, approval_required=True,
        required_subjects=("orthography", "reading", "writing", "english", "geography", "arithmetic", "us_history", "citizenship", "drawing", "music", "physical_education", "health"),
        source_citation="M.G.L. c.76 §1; Care & Protection of Charles, 399 Mass. 324; Brunelle, 428 Mass. 512",
        source_url="https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXII/Chapter76/Section1",
        notes=("Local approval is required in advance.",
               "District may review curriculum, time, competency, materials, and assessment.",
               "A home visit is not a universal approval condition."),
    ),
}


def get_homeschool_profile(state: str) -> HomeschoolProfile | None:
    """Return a profile by two-letter state code; unknown states return ``None``."""
    if not isinstance(state, str):
        return None
    return PROFILES.get(state.strip().upper())


def profile_for_route(state: str, route: str) -> HomeschoolProfile | None:
    """Return state requirements narrowed to the parent-confirmed legal route.

    State profiles hold shared authority and defaults. This function removes
    obligations that belong to a different route so calendars, progress, and
    dashboard summaries do not flatten umbrella/exemption paths into the
    independent-home-education path.
    """
    profile = get_homeschool_profile(state)
    if profile is None:
        return None
    normalized = route.strip().lower() if isinstance(route, str) else ""
    if normalized not in profile.routes:
        return None
    if profile.state == "TN" and normalized == "church_related_school":
        return replace(
            profile,
            parent_qualification="church_related_school_defined",
            required_subjects=(),
            instruction_days=0,
            instruction_hours_per_day=0.0,
            assessment_frequency_years=0,
            assessment_grades=(),
            requirements_defined_by_oversight=True,
            diploma_note="church-related school issues transcript and diploma",
        )
    if profile.state == "SC":
        if normalized == "option1_district":
            return replace(profile, approval_required=True, assessment_frequency_years=1)
        if normalized == "option2_scaihs":
            return replace(
                profile, portfolio_required=False, progress_reports_per_year=0,
                requirements_defined_by_oversight=True,
            )
    if profile.state == "MD" and normalized == "nonpublic_supervision":
        return replace(
            profile, portfolio_required=False, progress_reports_per_year=0,
            requirements_defined_by_oversight=True,
        )
    if profile.state == "VA" and normalized == "religious_exemption":
        return replace(
            profile,
            annual_notice_date="",
            approval_required=True,
            assessment_frequency_years=0,
            assessment_grades=(),
            requirements_defined_by_oversight=True,
        )
    if profile.state == "FL" and normalized == "private_school_umbrella":
        return replace(
            profile,
            initial_notice_days=0,
            portfolio_required=False,
            portfolio_retention_years=0,
            assessment_frequency_years=0,
            assessment_grades=(),
            requirements_defined_by_oversight=True,
            diploma_note="private umbrella school is school of record and credential issuer",
        )
    if profile.state == "FL" and normalized == "pep_scholarship":
        return replace(
            profile,
            initial_notice_days=0,
            portfolio_required=False,
            portfolio_retention_years=0,
            assessment_frequency_years=1,
            requirements_defined_by_oversight=True,
        )
    if profile.state == "PA" and normalized == "private_tutor":
        return replace(
            profile,
            annual_notice_date="",
            parent_qualification="pennsylvania_certified_private_tutor",
            portfolio_required=False,
            progress_reports_per_year=0,
            assessment_grades=(),
            requirements_defined_by_oversight=True,
        )
    if profile.state == "PA" and normalized == "home_education":
        return replace(profile, assessment_frequency_years=1)
    if profile.state == "WV" and normalized == "board_approved":
        return replace(
            profile,
            approval_required=True,
            required_subjects=(),
            assessment_frequency_years=0,
            assessment_grades=(),
            requirements_defined_by_oversight=True,
            confidence="mixed",
        )
    if profile.state == "WV" and normalized in {"hope_individualized", "learning_pod"}:
        return replace(
            profile,
            required_subjects=(),
            assessment_frequency_years=0,
            assessment_grades=(),
            requirements_defined_by_oversight=True,
            confidence="mixed",
        )
    return profile


def registered_homeschool_states() -> tuple[str, ...]:
    return tuple(PROFILES)


def homeschool_summary() -> list[dict[str, object]]:
    return [
        {
            "state": p.state,
            "routes": p.routes,
            "notice": p.annual_notice_date or p.initial_notice_days,
            "assessment": p.assessment_frequency_years,
            "confidence": p.confidence,
        }
        for p in PROFILES.values()
    ]
