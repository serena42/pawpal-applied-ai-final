"""Scheduler and model integration tests for PawPal+."""

# pylint: disable=missing-module-docstring,missing-function-docstring,missing-class-docstring
# pylint: disable=redefined-outer-name,wrong-import-order,too-few-public-methods,protected-access,line-too-long

from datetime import time

import pytest
from models import (
    Task, TaskType, AvailabilityWindow, Owner, Pet, Scheduler, DailyPlan,
    _mins,
    ENERGY_DURATION_MULT, ENERGY_FREQUENCY_MULT,
    AGE_DURATION_MULT, AGE_FREQUENCY_MULT, AGE_FEEDING_FREQUENCY_MULT,
    ACTIVITY_TASKS, VIGOROUS_TASKS, POST_FEEDING_GAP,
    _MIN_MED_FEEDING_GAP, _MIN_CARE_TASK_GAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def basic_owner():
    """Owner free from 8am to 6pm (10 hours)."""
    owner = Owner("Jordan")
    owner.add_window(time(8, 0), time(18, 0))
    return owner


@pytest.fixture
def tight_owner():
    """Owner free from 8am to 8:30am only (30 minutes)."""
    owner = Owner("Jordan")
    owner.add_window(time(8, 0), time(8, 30))
    return owner


@pytest.fixture
def dog():
    return Pet("Mochi", "dog")


# ---------------------------------------------------------------------------
# Model tests (should pass immediately — no scheduler logic needed)
# ---------------------------------------------------------------------------

def test_availability_window_duration():
    window = AvailabilityWindow(time(8, 0), time(10, 30))
    assert window.duration_minutes() == 150


def test_task_defaults():
    task = Task(TaskType.WALK)
    assert task.duration_minutes == 30
    assert task.frequency == 3
    assert task.priority == 1


def test_task_override():
    task = Task(TaskType.FEEDING, frequency=1, duration_minutes=10)
    assert task.frequency == 1
    assert task.duration_minutes == 10
    assert task.priority == 1  # not overridden, should still be default


def test_mark_complete():
    task = Task(TaskType.WALK)
    assert task.completed is False
    task.mark_complete()
    assert task.completed is True


def test_list_tasks_sorted_by_priority(dog):
    dog.add_task(Task(TaskType.GROOMING))   # priority 3
    dog.add_task(Task(TaskType.WALK))       # priority 1
    dog.add_task(Task(TaskType.ENRICHMENT)) # priority 2
    result = dog.list_tasks()
    priorities = [t.priority for t in result]
    assert priorities == sorted(priorities)


def test_urgency_score_frequency_breaks_priority_tie(basic_owner, dog):
    """Among same-priority tasks, higher frequency should score higher (scheduled first)."""
    # WALK: priority 1, frequency 3 — needs 3 slots, must be scheduled before lower-freq tasks
    # FEEDING: priority 1, frequency 2
    # MEDICATION: priority 1, frequency 1
    dog.add_task(Task(TaskType.MEDICATION))  # p=1, f=1
    dog.add_task(Task(TaskType.FEEDING, frequency=2))   # p=1, f=2
    dog.add_task(Task(TaskType.WALK, frequency=3))      # p=1, f=3
    scheduler = Scheduler(basic_owner, dog)
    ordered = scheduler._sort_by_priority()
    task_types = [t.task_type for t in ordered]
    # Walk (3x) should appear before Feeding (2x) before Medication (1x)
    assert task_types.index(TaskType.WALK) < task_types.index(TaskType.FEEDING)
    assert task_types.index(TaskType.FEEDING) < task_types.index(TaskType.MEDICATION)


# ---------------------------------------------------------------------------
# Scheduler tests (will fail until generate_plan() is implemented)
# ---------------------------------------------------------------------------

def test_tasks_scheduled_when_enough_time(basic_owner, dog):
    dog.add_task(Task(TaskType.WALK))
    dog.add_task(Task(TaskType.FEEDING))
    scheduler = Scheduler(basic_owner, dog)
    plan = scheduler.generate_plan()
    assert isinstance(plan, DailyPlan)
    assert len(plan.scheduled) > 0
    assert len(plan.warnings) == 0


def test_high_priority_scheduled_before_low_priority(basic_owner, dog):
    dog.add_task(Task(TaskType.GROOMING))   # priority 3
    dog.add_task(Task(TaskType.WALK))       # priority 1
    scheduler = Scheduler(basic_owner, dog)
    plan = scheduler.generate_plan()
    task_names = [st.task.task_type for st in plan.scheduled]
    assert task_names.index(TaskType.WALK) < task_names.index(TaskType.GROOMING)


def test_task_dropped_when_no_time(tight_owner, dog):
    dog.add_task(Task(TaskType.WALK))       # 30 min
    dog.add_task(Task(TaskType.FEEDING))    # 15 min
    dog.add_task(Task(TaskType.GROOMING))   # 30 min
    scheduler = Scheduler(tight_owner, dog)
    plan = scheduler.generate_plan()
    total_tasks = sum(t.frequency for t in dog.tasks)
    assert len(plan.scheduled) < total_tasks


def test_warning_generated_when_task_dropped(tight_owner, dog):
    dog.add_task(Task(TaskType.WALK))
    dog.add_task(Task(TaskType.FEEDING))
    dog.add_task(Task(TaskType.GROOMING))
    scheduler = Scheduler(tight_owner, dog)
    plan = scheduler.generate_plan()
    assert len(plan.warnings) > 0


def test_feeding_gap_no_warning(basic_owner, dog):
    """2 feedings in a 10-hour window should be spaced fine — no gap warning."""
    dog.add_task(Task(TaskType.FEEDING, frequency=2))
    plan = Scheduler(basic_owner, dog).generate_plan()
    gap_warnings = [w for w in plan.warnings if "gap" in w.lower() or "feeding" in w.lower()]
    assert len(gap_warnings) == 0


def test_feeding_gap_triggers_warning():
    """2 feedings forced into windows 11 hours apart should generate a gap warning."""
    owner = Owner("Jordan")
    owner.add_window(time(8, 0), time(9, 0))    # 1-hour morning window
    owner.add_window(time(19, 0), time(20, 0))  # 1-hour evening window
    dog = Pet("Mochi", "dog")
    dog.add_task(Task(TaskType.FEEDING, frequency=2))
    plan = Scheduler(owner, dog).generate_plan()
    gap_warnings = [w for w in plan.warnings if "gap" in w.lower() or "feeding" in w.lower()]
    assert len(gap_warnings) > 0


def test_recurring_tasks_spread_across_day(basic_owner, dog):
    """3 walks in a 10-hour day should be spread out, not back-to-back."""
    dog.add_task(Task(TaskType.WALK, frequency=3))
    scheduler = Scheduler(basic_owner, dog)
    plan = scheduler.generate_plan()
    walk_starts = sorted(
        e.start_time.hour * 60 + e.start_time.minute
        for e in plan.scheduled if e.task.task_type == TaskType.WALK
    )
    assert len(walk_starts) == 3
    # Each occurrence should be at least 90 minutes after the previous one.
    for i in range(len(walk_starts) - 1):
        assert walk_starts[i + 1] - walk_starts[i] >= 90


def test_two_pets_no_time_overlap(basic_owner):
    """Tasks for two pets must never occupy the same owner time slot."""
    dog = Pet("Mochi", "dog")
    dog.add_task(Task(TaskType.WALK, frequency=3))
    dog.add_task(Task(TaskType.FEEDING, frequency=2))

    cat = Pet("Luna", "cat")
    cat.add_task(Task(TaskType.FEEDING, frequency=2))
    cat.add_task(Task(TaskType.PLAYTIME))

    basic_owner.add_pet(dog)
    basic_owner.add_pet(cat)

    all_plans = Scheduler(basic_owner, dog).generate_all_plans()

    all_entries = [
        entry
        for plan in all_plans.values()
        for entry in plan.scheduled
    ]

    for i, a in enumerate(all_entries):
        for b in all_entries[i + 1:]:
            a_start = a.start_time.hour * 60 + a.start_time.minute
            a_end   = a.end_time.hour   * 60 + a.end_time.minute
            b_start = b.start_time.hour * 60 + b.start_time.minute
            b_end   = b.end_time.hour   * 60 + b.end_time.minute
            assert not (a_start < b_end and b_start < a_end), (
                f"Overlap: {a.task.name} ({a.start_time}–{a.end_time}) "
                f"and {b.task.name} ({b.start_time}–{b.end_time})"
            )


def test_dependency_respected(basic_owner, dog):
    """Medication depends on Feeding — Feeding must be scheduled first."""
    feeding = Task(TaskType.FEEDING)
    medication = Task(TaskType.MEDICATION, dependencies=[feeding])
    dog.add_task(feeding)
    dog.add_task(medication)
    scheduler = Scheduler(basic_owner, dog)
    plan = scheduler.generate_plan()
    scheduled_types = [st.task.task_type for st in plan.scheduled]
    assert TaskType.FEEDING in scheduled_types
    assert TaskType.MEDICATION in scheduled_types
    assert scheduled_types.index(TaskType.FEEDING) < scheduled_types.index(TaskType.MEDICATION)


# ---------------------------------------------------------------------------
# Breed-tuner helpers (mirror of multiplier logic in app.py)
# ---------------------------------------------------------------------------

def _apply(dur: int, freq: int, tt: TaskType, energy: str, age: str):
    if tt in ACTIVITY_TASKS:
        dur  = max(1, round(dur  * ENERGY_DURATION_MULT.get(energy, 1.0)  * AGE_DURATION_MULT.get(age, 1.0)))
        freq = max(1, round(freq * ENERGY_FREQUENCY_MULT.get(energy, 1.0) * AGE_FREQUENCY_MULT.get(age, 1.0)))
    elif tt == TaskType.FEEDING:
        freq = max(1, round(freq * AGE_FEEDING_FREQUENCY_MULT.get(age, 1.0)))
    return dur, freq


# ---------------------------------------------------------------------------
# Scheduler integration: breed-tuned durations and frequencies
# ---------------------------------------------------------------------------

class TestSchedulerWithBreedTuner:
    def _make_plan(self, energy: str, age: str, base_dur: int = 30, base_freq: int = 1):
        owner = Owner("Tester")
        owner.add_window(time(8, 0), time(20, 0))
        pet = Pet("Buddy", "dog", energy_level=energy, age_group=age)
        dur, freq = _apply(base_dur, base_freq, TaskType.WALK, energy, age)
        pet.add_task(Task(TaskType.WALK, duration_minutes=dur, frequency=freq))
        owner.add_pet(pet)
        return Scheduler(owner, pet).generate_plan()

    def test_very_high_energy_walk_longer_than_low(self):
        plan_hi  = self._make_plan("very_high", "adult")
        plan_low = self._make_plan("low", "adult")
        assert plan_hi.scheduled[0].task.duration_minutes > plan_low.scheduled[0].task.duration_minutes

    def test_puppy_walk_scheduled_more_frequently(self):
        plan_puppy = self._make_plan("medium", "puppy", base_freq=2)
        plan_adult = self._make_plan("medium", "adult", base_freq=2)
        assert len(plan_puppy.scheduled) >= len(plan_adult.scheduled)

    def test_medium_adult_walk_uses_base_duration(self):
        plan = self._make_plan("medium", "adult", base_dur=30)
        assert plan.scheduled[0].task.duration_minutes == 30


# ---------------------------------------------------------------------------
# Scheduler enforces post-feeding gap before vigorous activity
# ---------------------------------------------------------------------------

class TestSchedulerEnforcesPostFeedingGap:
    def _make_plan_with(self, task_types):
        owner = Owner("Jordan")
        owner.add_window(time(8, 0), time(18, 0))
        dog = Pet("Mochi", "dog")
        for tt in task_types:
            dog.add_task(Task(tt, frequency=1))
        owner.add_pet(dog)
        return Scheduler(owner, dog).generate_plan()

    def test_fetch_not_scheduled_within_gap_of_feeding(self):
        plan = self._make_plan_with([TaskType.FEEDING, TaskType.FETCH])
        feedings = [s for s in plan.scheduled if s.task.task_type == TaskType.FEEDING]
        fetches  = [s for s in plan.scheduled if s.task.task_type == TaskType.FETCH]
        for feed in feedings:
            for fetch in fetches:
                feed_end    = _mins(feed.end_time)
                fetch_start = _mins(fetch.start_time)
                if fetch_start >= feed_end:
                    assert fetch_start >= feed_end + POST_FEEDING_GAP

    def test_walk_not_scheduled_within_gap_of_feeding(self):
        plan = self._make_plan_with([TaskType.FEEDING, TaskType.WALK])
        feedings = [s for s in plan.scheduled if s.task.task_type == TaskType.FEEDING]
        walks    = [s for s in plan.scheduled if s.task.task_type == TaskType.WALK]
        for feed in feedings:
            for walk in walks:
                feed_end   = _mins(feed.end_time)
                walk_start = _mins(walk.start_time)
                if walk_start >= feed_end:
                    assert walk_start >= feed_end + POST_FEEDING_GAP

    def test_playtime_not_scheduled_within_gap_of_feeding(self):
        plan = self._make_plan_with([TaskType.FEEDING, TaskType.PLAYTIME])
        feedings  = [s for s in plan.scheduled if s.task.task_type == TaskType.FEEDING]
        playtimes = [s for s in plan.scheduled if s.task.task_type == TaskType.PLAYTIME]
        for feed in feedings:
            for play in playtimes:
                feed_end   = _mins(feed.end_time)
                play_start = _mins(play.start_time)
                if play_start >= feed_end:
                    assert play_start >= feed_end + POST_FEEDING_GAP

    def test_vigorous_tasks_is_subset_of_activity_tasks(self):
        assert VIGOROUS_TASKS.issubset(ACTIVITY_TASKS)

    def test_post_feeding_gap_is_positive(self):
        assert POST_FEEDING_GAP > 0


# ---------------------------------------------------------------------------
# Scheduler enforces minimum gap between feeding end and medication start
# ---------------------------------------------------------------------------

class TestSchedulerEnforcedMedFeedingGap:
    def test_scheduler_places_medication_after_min_gap(self):
        owner = Owner("Jordan")
        owner.add_window(time(8, 0), time(18, 0))
        dog = Pet("Mochi", "dog")
        feeding    = Task(TaskType.FEEDING,    frequency=1)
        medication = Task(TaskType.MEDICATION, frequency=1, dependencies=[feeding])
        dog.add_task(feeding)
        dog.add_task(medication)
        owner.add_pet(dog)
        plan = Scheduler(owner, dog).generate_plan()
        feed_sts = [s for s in plan.scheduled if s.task.task_type == TaskType.FEEDING]
        med_sts  = [s for s in plan.scheduled if s.task.task_type == TaskType.MEDICATION]
        assert feed_sts and med_sts
        assert _mins(med_sts[0].start_time) >= _mins(feed_sts[0].end_time) + _MIN_MED_FEEDING_GAP


# ---------------------------------------------------------------------------
# Scheduler enforces minimum gap between recurring care task occurrences
# ---------------------------------------------------------------------------

class TestSchedulerEnforcesCareTaskGap:
    def _feeding_starts(self, plan):
        return sorted(
            _mins(s.start_time)
            for s in plan.scheduled if s.task.task_type == TaskType.FEEDING
        )

    def test_two_feedings_spaced_by_min_gap(self):
        owner = Owner("Jordan")
        owner.add_window(time(8, 0), time(18, 0))
        dog = Pet("Mochi", "dog")
        dog.add_task(Task(TaskType.FEEDING, frequency=2))
        owner.add_pet(dog)
        starts = self._feeding_starts(Scheduler(owner, dog).generate_plan())
        assert len(starts) == 2
        assert starts[1] - starts[0] >= _MIN_CARE_TASK_GAP[TaskType.FEEDING]

    def test_three_feedings_all_spaced_by_min_gap(self):
        owner = Owner("Jordan")
        owner.add_window(time(7, 0), time(23, 0))
        dog = Pet("Mochi", "dog")
        dog.add_task(Task(TaskType.FEEDING, frequency=3))
        owner.add_pet(dog)
        starts = self._feeding_starts(Scheduler(owner, dog).generate_plan())
        assert len(starts) == 3
        min_gap = _MIN_CARE_TASK_GAP[TaskType.FEEDING]
        for i in range(len(starts) - 1):
            assert starts[i + 1] - starts[i] >= min_gap

    def test_feeding_not_back_to_back_in_tight_window(self):
        owner = Owner("Jordan")
        owner.add_window(time(8, 0), time(20, 0))
        dog = Pet("Mochi", "dog")
        dog.add_task(Task(TaskType.FEEDING, frequency=2))
        owner.add_pet(dog)
        starts = self._feeding_starts(Scheduler(owner, dog).generate_plan())
        if len(starts) == 2:
            assert starts[1] - starts[0] >= _MIN_CARE_TASK_GAP[TaskType.FEEDING]


# ---------------------------------------------------------------------------
# Scheduler respects per-task earliest/latest time constraints
# ---------------------------------------------------------------------------

class TestSchedulerRespectsWindowConstraints:
    def test_scheduler_places_task_after_earliest(self):
        owner = Owner("Jordan")
        owner.add_window(time(8, 0), time(18, 0))
        dog = Pet("Mochi", "dog")
        dog.add_task(Task(TaskType.GROOMING, duration_minutes=30, frequency=1, earliest=time(14, 0)))
        owner.add_pet(dog)
        plan = Scheduler(owner, dog).generate_plan()
        grooms = [s for s in plan.scheduled if s.task.task_type == TaskType.GROOMING]
        assert grooms
        assert _mins(grooms[0].start_time) >= _mins(time(14, 0))

    def test_scheduler_places_task_before_latest(self):
        owner = Owner("Jordan")
        owner.add_window(time(8, 0), time(18, 0))
        dog = Pet("Mochi", "dog")
        dog.add_task(Task(TaskType.GROOMING, duration_minutes=30, frequency=1, latest=time(10, 0)))
        owner.add_pet(dog)
        plan = Scheduler(owner, dog).generate_plan()
        grooms = [s for s in plan.scheduled if s.task.task_type == TaskType.GROOMING]
        assert grooms
        assert _mins(grooms[0].end_time) <= _mins(time(10, 0))
