"""
Unit tests for conflict_detector.py, agent.py, and breed tuner.
API-calling methods are not tested here — they require a live key.

Run:
    pytest test_agent.py -v
"""

import pytest
from datetime import time

from models import (
    Owner, Pet, Task, TaskType, DailyPlan, ScheduledTask, Scheduler, _to_time,
    ENERGY_DURATION_MULT, AGE_DURATION_MULT, AGE_FREQUENCY_MULT, ACTIVITY_TASKS,
)
from conflict_detector import detect_conflicts, Conflict
from agent import ScheduleAgent
from breed_db import BreedTrie, get_trie


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_owner(windows=None):
    o = Owner("Tester")
    for start, end in (windows or [(time(8, 0), time(20, 0))]):
        o.add_window(start, end)
    return o


def make_st(task_type, name, start_mins, duration_mins):
    task = Task(task_type, name=name, duration_minutes=duration_mins)
    return ScheduledTask(task, _to_time(start_mins), _to_time(start_mins + duration_mins), "test")


def single_pet_plans(owner_name="Tester", pet_name="Buddy", sts=None):
    plan = DailyPlan()
    if sts:
        plan.scheduled.extend(sts)
    return {pet_name: plan}


# ---------------------------------------------------------------------------
# conflict_detector tests
# ---------------------------------------------------------------------------

class TestNoConflicts:
    def test_clean_schedule_returns_empty_list(self):
        owner = make_owner()
        st1 = make_st(TaskType.WALK, "Morning Walk", 480, 30)      # 8:00–8:30
        st2 = make_st(TaskType.FEEDING, "Feeding", 510, 15)         # 8:30–8:45
        plans = single_pet_plans(sts=[st1, st2])
        assert detect_conflicts(plans, owner, []) == []


class TestOverlapDetection:
    def test_overlap_detected(self):
        owner = make_owner()
        st1 = make_st(TaskType.WALK, "Morning Walk", 480, 30)       # 8:00–8:30
        st2 = make_st(TaskType.FEEDING, "Feeding", 500, 15)          # 8:20–8:35  ← overlaps
        plans = single_pet_plans(sts=[st1, st2])
        conflicts = detect_conflicts(plans, owner, [])
        overlaps = [c for c in conflicts if c.conflict_type == "overlap"]
        assert len(overlaps) == 1
        assert "Morning Walk" in overlaps[0].reason

    def test_adjacent_tasks_not_overlap(self):
        owner = make_owner()
        st1 = make_st(TaskType.WALK, "Morning Walk", 480, 30)       # 8:00–8:30
        st2 = make_st(TaskType.FEEDING, "Feeding", 510, 15)          # 8:30–8:45  ← adjacent, not overlap
        plans = single_pet_plans(sts=[st1, st2])
        conflicts = detect_conflicts(plans, owner, [])
        overlaps = [c for c in conflicts if c.conflict_type == "overlap"]
        assert len(overlaps) == 0


class TestGapDetection:
    def test_feeding_gap_violation_detected(self):
        owner = make_owner()
        # Feeding max gap = 8h = 480 min; schedule them 10h apart.
        st1 = make_st(TaskType.FEEDING, "Morning Feeding", 480, 15)  # 8:00–8:15
        st2 = make_st(TaskType.FEEDING, "Evening Feeding", 1080, 15) # 18:00–18:15  gap=585>480
        plans = single_pet_plans(sts=[st1, st2])
        conflicts = detect_conflicts(plans, owner, [])
        gaps = [c for c in conflicts if c.conflict_type == "gap"]
        assert len(gaps) == 1
        assert "Feeding" in gaps[0].reason

    def test_no_gap_violation_within_threshold(self):
        owner = make_owner()
        # Two feedings 4h apart — within 8h threshold.
        st1 = make_st(TaskType.FEEDING, "Morning Feeding", 480, 15)  # 8:00–8:15
        st2 = make_st(TaskType.FEEDING, "Noon Feeding", 720, 15)     # 12:00–12:15  gap=225<480
        plans = single_pet_plans(sts=[st1, st2])
        conflicts = detect_conflicts(plans, owner, [])
        gaps = [c for c in conflicts if c.conflict_type == "gap"]
        assert len(gaps) == 0


class TestDependencyDetection:
    def test_dependency_violation_detected(self):
        owner = make_owner()
        feeding = Task(TaskType.FEEDING, name="Feeding", duration_minutes=15)
        medication = Task(TaskType.MEDICATION, name="Medication",
                          duration_minutes=5, dependencies=[feeding])

        # Medication at 8:00, Feeding at 8:10 — Medication scheduled before its dep.
        st_med = ScheduledTask(medication, _to_time(480), _to_time(485), "test")
        st_fed = ScheduledTask(feeding, _to_time(490), _to_time(505), "test")

        plans = single_pet_plans(sts=[st_med, st_fed])
        conflicts = detect_conflicts(plans, owner, [])
        deps = [c for c in conflicts if c.conflict_type == "dependency"]
        assert len(deps) == 1
        assert "Medication" in deps[0].reason

    def test_correct_dependency_order_no_conflict(self):
        owner = make_owner()
        feeding = Task(TaskType.FEEDING, name="Feeding", duration_minutes=15)
        medication = Task(TaskType.MEDICATION, name="Medication",
                          duration_minutes=5, dependencies=[feeding])

        # Feeding at 8:00, Medication at 8:15 — correct order.
        st_fed = ScheduledTask(feeding, _to_time(480), _to_time(495), "test")
        st_med = ScheduledTask(medication, _to_time(495), _to_time(500), "test")

        plans = single_pet_plans(sts=[st_fed, st_med])
        conflicts = detect_conflicts(plans, owner, [])
        deps = [c for c in conflicts if c.conflict_type == "dependency"]
        assert len(deps) == 0


class TestOutsideWindowDetection:
    def test_task_outside_window_detected(self):
        # Owner available 8-10 only; task scheduled at 14:00.
        owner = make_owner(windows=[(time(8, 0), time(10, 0))])
        st = make_st(TaskType.WALK, "Afternoon Walk", 840, 30)       # 14:00–14:30
        plans = single_pet_plans(sts=[st])
        conflicts = detect_conflicts(plans, owner, [])
        outside = [c for c in conflicts if c.conflict_type == "outside_window"]
        assert len(outside) == 1

    def test_task_inside_window_no_outside_conflict(self):
        owner = make_owner(windows=[(time(8, 0), time(10, 0))])
        st = make_st(TaskType.WALK, "Morning Walk", 480, 30)         # 8:00–8:30  ✓
        plans = single_pet_plans(sts=[st])
        conflicts = detect_conflicts(plans, owner, [])
        outside = [c for c in conflicts if c.conflict_type == "outside_window"]
        assert len(outside) == 0


# ---------------------------------------------------------------------------
# ScheduleAgent fix-application tests (no API key required)
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    """ScheduleAgent instance with no Anthropic client (skips __init__)."""
    return ScheduleAgent.__new__(ScheduleAgent)


class TestMoveTask:
    def test_move_task_updates_times(self, agent):
        st = make_st(TaskType.WALK, "Morning Walk", 480, 30)        # 8:00–8:30
        plans = single_pet_plans(sts=[st])
        result = agent._move_task(plans, "Morning Walk", 600)        # move to 10:00
        updated = result["Buddy"].scheduled[0]
        assert updated.start_time == _to_time(600)
        assert updated.end_time == _to_time(630)

    def test_move_task_case_insensitive(self, agent):
        st = make_st(TaskType.FEEDING, "Feeding", 480, 15)
        plans = single_pet_plans(sts=[st])
        result = agent._move_task(plans, "feeding", 510)
        assert result["Buddy"].scheduled[0].start_time == _to_time(510)

    def test_move_task_no_match_returns_unchanged(self, agent):
        st = make_st(TaskType.WALK, "Morning Walk", 480, 30)
        plans = single_pet_plans(sts=[st])
        result = agent._move_task(plans, "NonExistent", 600)
        assert result["Buddy"].scheduled[0].start_time == _to_time(480)


class TestSwapTasks:
    def test_swap_exchanges_times(self, agent):
        st_a = make_st(TaskType.WALK, "Morning Walk", 480, 30)      # 8:00–8:30
        st_b = make_st(TaskType.FEEDING, "Feeding", 510, 15)         # 8:30–8:45
        plans = single_pet_plans(sts=[st_a, st_b])
        result = agent._swap_tasks(plans, "Morning Walk", "Feeding")
        scheduled = result["Buddy"].scheduled
        walk = next(s for s in scheduled if s.task.name == "Morning Walk")
        feeding = next(s for s in scheduled if s.task.name == "Feeding")
        assert walk.start_time == _to_time(510)
        assert feeding.start_time == _to_time(480)

    def test_swap_missing_task_returns_unchanged(self, agent):
        st = make_st(TaskType.WALK, "Morning Walk", 480, 30)
        plans = single_pet_plans(sts=[st])
        result = agent._swap_tasks(plans, "Morning Walk", "GhostTask")
        assert result["Buddy"].scheduled[0].start_time == _to_time(480)


class TestApplyFix:
    def test_parses_move_suggestion(self, agent):
        st = make_st(TaskType.FEEDING, "Feeding", 480, 15)
        plans = single_pet_plans(sts=[st])
        result = agent._apply_fix(plans, "Move Feeding to 09:30")
        updated = result["Buddy"].scheduled[0]
        assert updated.start_time == _to_time(9 * 60 + 30)

    def test_parses_move_from_to_suggestion(self, agent):
        st = make_st(TaskType.FEEDING, "Feeding", 480, 15)
        plans = single_pet_plans(sts=[st])
        result = agent._apply_fix(plans, "Move Feeding from 08:00 to 09:00")
        assert result["Buddy"].scheduled[0].start_time == _to_time(540)

    def test_parses_swap_suggestion(self, agent):
        st_a = make_st(TaskType.WALK, "Walk", 480, 30)
        st_b = make_st(TaskType.FEEDING, "Feeding", 510, 15)
        plans = single_pet_plans(sts=[st_a, st_b])
        result = agent._apply_fix(plans, "Swap Walk and Feeding")
        scheduled = result["Buddy"].scheduled
        walk = next(s for s in scheduled if s.task.name == "Walk")
        assert walk.start_time == _to_time(510)

    def test_unparseable_suggestion_returns_unchanged(self, agent):
        st = make_st(TaskType.WALK, "Walk", 480, 30)
        plans = single_pet_plans(sts=[st])
        result = agent._apply_fix(plans, "I am not sure what to do here.")
        assert result["Buddy"].scheduled[0].start_time == _to_time(480)


# ---------------------------------------------------------------------------
# BreedTrie tests
# ---------------------------------------------------------------------------

@pytest.fixture
def small_trie():
    t = BreedTrie()
    for b in [
        {"name": "Labrador Retriever", "energy_level": "high",      "size": "large"},
        {"name": "Lhasa Apso",         "energy_level": "low",       "size": "small"},
        {"name": "Border Collie",      "energy_level": "very_high", "size": "medium"},
        {"name": "Border Terrier",     "energy_level": "high",      "size": "small"},
        {"name": "Beagle",             "energy_level": "medium",    "size": "small"},
    ]:
        t.insert(b)
    return t


class TestBreedTrie:
    def test_exact_prefix_returns_match(self, small_trie):
        results = small_trie.search("lab")
        assert len(results) == 1
        assert results[0]["name"] == "Labrador Retriever"

    def test_search_case_insensitive(self, small_trie):
        assert small_trie.search("LAB") == small_trie.search("lab")

    def test_multi_match_prefix(self, small_trie):
        results = small_trie.search("bor")
        names = {r["name"] for r in results}
        assert "Border Collie" in names
        assert "Border Terrier" in names

    def test_no_match_returns_empty(self, small_trie):
        assert small_trie.search("xyz") == []

    def test_max_results_respected(self, small_trie):
        results = small_trie.search("b", max_results=1)
        assert len(results) <= 1

    def test_result_contains_energy_and_size(self, small_trie):
        result = small_trie.search("beagle")[0]
        assert result["energy_level"] == "medium"
        assert result["size"] == "small"

    def test_full_name_prefix_returns_breed(self, small_trie):
        results = small_trie.search("lhasa apso")
        assert len(results) == 1
        assert results[0]["name"] == "Lhasa Apso"

    def test_empty_prefix_returns_all_up_to_limit(self, small_trie):
        results = small_trie.search("", max_results=10)
        assert len(results) == 5

    def test_get_trie_loads_50_breeds(self):
        trie = get_trie()
        all_breeds = trie.search("", max_results=100)
        assert len(all_breeds) == 50

    def test_get_trie_is_singleton(self):
        assert get_trie() is get_trie()


# ---------------------------------------------------------------------------
# Pet breed attributes tests
# ---------------------------------------------------------------------------

class TestPetBreedAttributes:
    def test_default_energy_level(self):
        assert Pet("Buddy", "dog").energy_level == "medium"

    def test_default_age_group(self):
        assert Pet("Buddy", "dog").age_group == "adult"

    def test_custom_energy_level(self):
        p = Pet("Rex", "dog", energy_level="very_high")
        assert p.energy_level == "very_high"

    def test_custom_age_group(self):
        p = Pet("Luna", "cat", age_group="senior")
        assert p.age_group == "senior"

    def test_all_fields_stored(self):
        p = Pet("Max", "dog", energy_level="high", age_group="puppy")
        assert p.name == "Max"
        assert p.pet_type == "dog"
        assert p.energy_level == "high"
        assert p.age_group == "puppy"


# ---------------------------------------------------------------------------
# Multiplier constant tests
# ---------------------------------------------------------------------------

class TestMultiplierConstants:
    def test_energy_duration_ordering(self):
        m = ENERGY_DURATION_MULT
        assert m["low"] < m["medium"] < m["high"] < m["very_high"]

    def test_medium_energy_is_baseline(self):
        assert ENERGY_DURATION_MULT["medium"] == 1.0

    def test_age_duration_adult_is_baseline(self):
        assert AGE_DURATION_MULT["adult"] == 1.0

    def test_puppy_and_senior_reduce_duration(self):
        assert AGE_DURATION_MULT["puppy"] < 1.0
        assert AGE_DURATION_MULT["senior"] < 1.0

    def test_puppy_frequency_higher_than_adult(self):
        assert AGE_FREQUENCY_MULT["puppy"] > AGE_FREQUENCY_MULT["adult"]

    def test_senior_frequency_lower_than_adult(self):
        assert AGE_FREQUENCY_MULT["senior"] < AGE_FREQUENCY_MULT["adult"]

    def test_walk_is_activity_task(self):
        assert TaskType.WALK in ACTIVITY_TASKS

    def test_fetch_is_activity_task(self):
        assert TaskType.FETCH in ACTIVITY_TASKS

    def test_feeding_is_not_activity_task(self):
        assert TaskType.FEEDING not in ACTIVITY_TASKS

    def test_medication_is_not_activity_task(self):
        assert TaskType.MEDICATION not in ACTIVITY_TASKS

    def test_grooming_is_not_activity_task(self):
        assert TaskType.GROOMING not in ACTIVITY_TASKS


# ---------------------------------------------------------------------------
# Multiplier application logic tests
# ---------------------------------------------------------------------------

def _apply(dur: int, freq: int, tt: TaskType, energy: str, age: str):
    """Mirror of the multiplier logic in app.py generate section."""
    if tt in ACTIVITY_TASKS:
        e_dur  = ENERGY_DURATION_MULT.get(energy, 1.0)
        a_dur  = AGE_DURATION_MULT.get(age, 1.0)
        a_freq = AGE_FREQUENCY_MULT.get(age, 1.0)
        dur    = max(1, round(dur  * e_dur * a_dur))
        freq   = max(1, round(freq * a_freq))
    return dur, freq


class TestMultiplierApplication:
    def test_high_energy_extends_walk_duration(self):
        dur, _ = _apply(30, 1, TaskType.WALK, "high", "adult")
        assert dur == round(30 * 1.2)

    def test_very_high_energy_extends_walk(self):
        dur, _ = _apply(30, 1, TaskType.WALK, "very_high", "adult")
        assert dur == round(30 * 1.5)

    def test_low_energy_reduces_walk(self):
        dur, _ = _apply(30, 1, TaskType.WALK, "low", "adult")
        assert dur == round(30 * 0.8)

    def test_medium_energy_no_change(self):
        dur, freq = _apply(30, 2, TaskType.WALK, "medium", "adult")
        assert dur == 30
        assert freq == 2

    def test_puppy_increases_frequency(self):
        _, freq = _apply(30, 2, TaskType.WALK, "medium", "puppy")
        assert freq == round(2 * 1.5)

    def test_senior_reduces_duration(self):
        dur, _ = _apply(30, 2, TaskType.WALK, "medium", "senior")
        assert dur == round(30 * 0.8)

    def test_senior_reduces_frequency(self):
        _, freq = _apply(4, 4, TaskType.PLAYTIME, "medium", "senior")
        assert freq == round(4 * 0.8)

    def test_high_energy_puppy_combined(self):
        dur, freq = _apply(30, 2, TaskType.WALK, "high", "puppy")
        assert dur  == round(30 * 1.2 * 0.75)
        assert freq == round(2  * 1.5)

    def test_feeding_unaffected_by_energy(self):
        dur, freq = _apply(15, 2, TaskType.FEEDING, "very_high", "puppy")
        assert dur  == 15
        assert freq == 2

    def test_medication_unaffected_by_energy(self):
        dur, freq = _apply(5, 1, TaskType.MEDICATION, "very_high", "senior")
        assert dur  == 5
        assert freq == 1

    def test_duration_never_below_one(self):
        dur, _ = _apply(1, 1, TaskType.WALK, "low", "senior")
        assert dur >= 1


# ---------------------------------------------------------------------------
# Scheduler integration: energy/age multipliers affect plan task durations
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
        dur_hi  = plan_hi.scheduled[0].task.duration_minutes
        dur_low = plan_low.scheduled[0].task.duration_minutes
        assert dur_hi > dur_low

    def test_puppy_walk_scheduled_more_frequently(self):
        plan_puppy = self._make_plan("medium", "puppy", base_freq=2)
        plan_adult = self._make_plan("medium", "adult", base_freq=2)
        assert len(plan_puppy.scheduled) >= len(plan_adult.scheduled)

    def test_medium_adult_walk_uses_base_duration(self):
        plan = self._make_plan("medium", "adult", base_dur=30)
        assert plan.scheduled[0].task.duration_minutes == 30
