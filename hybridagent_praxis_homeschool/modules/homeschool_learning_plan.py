"""Parent-directed, multi-grade homeschool learning-program planner."""
from __future__ import annotations

from dataclasses import dataclass

from .homeschool_jurisdictions import get_homeschool_profile


@dataclass(frozen=True)
class LearnerPlan:
    learner_id: str
    grade: int
    age: int
    goals: tuple[str, ...]
    skill_subjects: tuple[str, ...] = ("reading", "mathematics")


@dataclass(frozen=True)
class LearningActivity:
    activity_id: str
    title: str
    subjects: tuple[str, ...]
    objectives: tuple[str, ...]
    evidence_types: tuple[str, ...]
    minutes: int
    min_grade: int = 1
    max_grade: int = 12
    shared_family: bool = False
    safety_note: str = "adult supervision appropriate to the activity"


@dataclass(frozen=True)
class ScheduledActivity:
    day: str
    activity_id: str
    learner_ids: tuple[str, ...]
    differentiated: bool


@dataclass(frozen=True)
class LearningProgram:
    state: str
    learners: tuple[LearnerPlan, ...]
    schedule: tuple[ScheduledActivity, ...]
    covered_subjects: tuple[str, ...]
    missing_required_subjects: tuple[str, ...]
    missing_required_subjects_by_learner: tuple[tuple[str, tuple[str, ...]], ...]
    warnings: tuple[str, ...]


def build_learning_program(*, state: str, learners: tuple[LearnerPlan, ...],
                           activities: tuple[LearningActivity, ...],
                           days: tuple[str, ...] = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")) -> LearningProgram:
    profile = get_homeschool_profile(state)
    if profile is None:
        raise ValueError("unsupported state")
    if not learners or not activities or not days:
        raise ValueError("learners, activities, and days are required")
    learner_ids = [x.learner_id for x in learners]
    if any(not x for x in learner_ids) or len(set(learner_ids)) != len(learner_ids):
        raise ValueError("learner IDs must be nonempty and unique")
    if any(
        not isinstance(x.grade, int) or isinstance(x.grade, bool)
        or not isinstance(x.age, int) or isinstance(x.age, bool)
        or x.grade < 0 or x.grade > 12 or x.age < 3 or x.age > 21
        for x in learners
    ):
        raise ValueError("learner grade/age is outside the supported K-12 range")
    if len(set(days)) != len(days) or any(not day.strip() for day in days):
        raise ValueError("schedule days must be unique and nonempty")
    activity_ids = tuple(activity.activity_id.strip() for activity in activities)
    if any(not item for item in activity_ids) or len(set(activity_ids)) != len(activity_ids):
        raise ValueError("activity IDs must be unique and nonempty")

    scheduled: list[ScheduledActivity] = []
    covered_by_learner: dict[str, set[str]] = {learner_id: set() for learner_id in learner_ids}
    daily_minutes: dict[tuple[str, str], int] = {}
    for index, activity in enumerate(activities):
        if (not activity.activity_id.strip() or not activity.title.strip() or not activity.subjects
                or any(not item.strip() for item in activity.subjects)
                or not activity.objectives or any(not item.strip() for item in activity.objectives)):
            raise ValueError("activity identity, title, subjects, and objectives are required")
        if (not isinstance(activity.minutes, int) or isinstance(activity.minutes, bool)
                or activity.minutes <= 0 or activity.minutes > 480
                or not activity.evidence_types
                or any(not item.strip() for item in activity.evidence_types)):
            raise ValueError("activity needs bounded minutes and evidence")
        if (not isinstance(activity.min_grade, int) or isinstance(activity.min_grade, bool)
                or not isinstance(activity.max_grade, int) or isinstance(activity.max_grade, bool)
                or not 0 <= activity.min_grade <= activity.max_grade <= 12):
            raise ValueError("activity grade bounds must be integers in [0, 12]")
        eligible = tuple(
            learner.learner_id for learner in learners
            if activity.min_grade <= learner.grade <= activity.max_grade
        )
        if not eligible:
            continue
        day = days[index % len(days)]
        for learner_id in eligible:
            key = (learner_id, day)
            daily_minutes[key] = daily_minutes.get(key, 0) + activity.minutes
            if daily_minutes[key] > 480:
                raise ValueError("scheduled learner workload exceeds 480 minutes in one day")
        shared = activity.shared_family and len(eligible) > 1
        if shared:
            scheduled.append(ScheduledActivity(day, activity.activity_id.strip(),
                                               eligible, differentiated=True))
        else:
            for learner_id in eligible:
                scheduled.append(ScheduledActivity(day, activity.activity_id.strip(),
                                                   (learner_id,), differentiated=False))
        normalized_subjects = {s.strip().lower() for s in activity.subjects}
        for learner_id in eligible:
            covered_by_learner[learner_id].update(normalized_subjects)

    covered = set().union(*covered_by_learner.values())
    missing_by_learner = tuple(
        (learner_id, tuple(subject for subject in profile.required_subjects
                           if subject not in covered_by_learner[learner_id]))
        for learner_id in learner_ids
    )
    missing = tuple(sorted({subject for _, subjects in missing_by_learner for subject in subjects}))
    warnings: list[str] = []
    if missing:
        details = "; ".join(
            f"{learner_id}: {', '.join(subjects)}"
            for learner_id, subjects in missing_by_learner if subjects
        )
        warnings.append("required-subject coverage gaps by learner: " + details)
    if profile.instruction_days:
        warnings.append(f"calendar must ultimately evidence {profile.instruction_days} actual days")
    if profile.approval_required:
        warnings.append("program remains subject to local approval; this plan is not approval")
    return LearningProgram(profile.state, learners, tuple(scheduled), tuple(sorted(covered)),
                           missing, missing_by_learner, tuple(warnings))


def differentiate_objective(objective: str, learners: tuple[LearnerPlan, ...]) -> dict[str, str]:
    """Create transparent grade-labeled scaffolds without inferring ability."""
    if not objective.strip():
        raise ValueError("objective must be nonempty")
    return {
        learner.learner_id: f"Grade {learner.grade}: {objective.strip()} — parent selects depth and evidence."
        for learner in learners
    }
