"""
Unit tests for conflict_detector.py, agent.py, and breed tuner.
API-calling methods are not tested here — they require a live key.

Run:
    pytest test_agent.py -v
"""

# pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
# pylint: disable=redefined-outer-name,unused-argument,import-outside-toplevel,line-too-long

from datetime import time
import pytest

from models import (
    Owner, Pet, Task, TaskType, DailyPlan, ScheduledTask, _to_time, _mins,
    ENERGY_DURATION_MULT, ENERGY_FREQUENCY_MULT,
    AGE_DURATION_MULT, AGE_FREQUENCY_MULT, AGE_FEEDING_FREQUENCY_MULT,
    ACTIVITY_TASKS, POST_FEEDING_GAP, PET_TASK_DEFAULTS,
    _MIN_MED_FEEDING_GAP, _MIN_CARE_TASK_GAP,
)
from conflict_detector import detect_conflicts, suggest_coverage_windows
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


def single_pet_plans(pet_name="Buddy", sts=None):
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
        assert not detect_conflicts(plans, owner, [])


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
        e_freq = ENERGY_FREQUENCY_MULT.get(energy, 1.0)
        a_dur  = AGE_DURATION_MULT.get(age, 1.0)
        a_freq = AGE_FREQUENCY_MULT.get(age, 1.0)
        dur    = max(1, round(dur  * e_dur * a_dur))
        freq   = max(1, round(freq * e_freq * a_freq))
    elif tt == TaskType.FEEDING:
        freq = max(1, round(freq * AGE_FEEDING_FREQUENCY_MULT.get(age, 1.0)))
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
        assert freq == round(2 * ENERGY_FREQUENCY_MULT["high"] * AGE_FREQUENCY_MULT["puppy"])

    def test_feeding_unaffected_by_energy(self):
        dur, freq = _apply(15, 2, TaskType.FEEDING, "very_high", "adult")
        assert dur  == 15
        assert freq == 2  # energy does not affect feeding frequency; only age does

    def test_medication_unaffected_by_energy(self):
        dur, freq = _apply(5, 1, TaskType.MEDICATION, "very_high", "senior")
        assert dur  == 5
        assert freq == 1

    def test_duration_never_below_one(self):
        dur, _ = _apply(1, 1, TaskType.WALK, "low", "senior")
        assert dur >= 1


# ---------------------------------------------------------------------------
# Fix #1: Post-feeding gap before vigorous activity
# ---------------------------------------------------------------------------

class TestPostFeedingGapDetection:
    def test_vigorous_task_immediately_after_feeding_detected(self):
        owner = make_owner()
        feed = make_st(TaskType.FEEDING, "Feeding", 480, 15)   # 8:00–8:15
        fetch = make_st(TaskType.FETCH, "Fetch", 480 + 15, 20) # 8:15–8:35 — 0 min gap
        plans = single_pet_plans(sts=[feed, fetch])
        conflicts = detect_conflicts(plans, owner, [])
        pfg = [c for c in conflicts if c.conflict_type == "post_feeding_gap"]
        assert len(pfg) == 1
        assert "Fetch" in pfg[0].reason

    def test_walk_too_soon_after_feeding_detected(self):
        owner = make_owner()
        feed = make_st(TaskType.FEEDING, "Feeding", 480, 15)    # 8:00–8:15
        walk = make_st(TaskType.WALK, "Walk", 495 + 10, 30)     # 8:25–8:55 — 10 min gap
        plans = single_pet_plans(sts=[feed, walk])
        conflicts = detect_conflicts(plans, owner, [])
        pfg = [c for c in conflicts if c.conflict_type == "post_feeding_gap"]
        assert len(pfg) == 1

    def test_vigorous_task_after_full_gap_no_conflict(self):
        owner = make_owner()
        feed = make_st(TaskType.FEEDING, "Feeding", 480, 15)    # 8:00–8:15
        fetch = make_st(TaskType.FETCH, "Fetch", 480 + 15 + POST_FEEDING_GAP, 20)  # 8:45+
        plans = single_pet_plans(sts=[feed, fetch])
        conflicts = detect_conflicts(plans, owner, [])
        pfg = [c for c in conflicts if c.conflict_type == "post_feeding_gap"]
        assert len(pfg) == 0

    def test_grooming_not_flagged_after_feeding(self):
        """Non-vigorous tasks may follow feeding immediately."""
        owner = make_owner()
        feed = make_st(TaskType.FEEDING, "Feeding", 480, 15)
        groom = make_st(TaskType.GROOMING, "Grooming", 495, 30)  # 8:15 — no gap needed
        plans = single_pet_plans(sts=[feed, groom])
        conflicts = detect_conflicts(plans, owner, [])
        pfg = [c for c in conflicts if c.conflict_type == "post_feeding_gap"]
        assert len(pfg) == 0

    def test_suggested_fix_mentions_safe_time(self):
        owner = make_owner()
        feed = make_st(TaskType.FEEDING, "Feeding", 480, 15)    # ends 8:15
        fetch = make_st(TaskType.FETCH, "Fetch", 495, 20)       # starts 8:15
        plans = single_pet_plans(sts=[feed, fetch])
        conflicts = detect_conflicts(plans, owner, [])
        pfg = [c for c in conflicts if c.conflict_type == "post_feeding_gap"]
        assert len(pfg) == 1
        assert "08:45" in pfg[0].suggested_fix  # 8:15 + 30 min = 8:45


# ---------------------------------------------------------------------------
# Fix #2: Energy level scales activity frequency
# ---------------------------------------------------------------------------

class TestEnergyFrequencyMultConstants:
    def test_very_high_energy_freq_above_medium(self):
        assert ENERGY_FREQUENCY_MULT["very_high"] > ENERGY_FREQUENCY_MULT["medium"]

    def test_low_energy_freq_below_medium(self):
        assert ENERGY_FREQUENCY_MULT["low"] < ENERGY_FREQUENCY_MULT["medium"]

    def test_medium_energy_is_baseline(self):
        assert ENERGY_FREQUENCY_MULT["medium"] == 1.0

    def test_ordering_low_medium_high_very_high(self):
        m = ENERGY_FREQUENCY_MULT
        assert m["low"] < m["medium"] < m["high"] < m["very_high"]

    def test_all_keys_present(self):
        assert set(ENERGY_FREQUENCY_MULT) == {"low", "medium", "high", "very_high"}


class TestEnergyFrequencyApplication:
    def test_very_high_energy_increases_walk_frequency(self):
        _, freq = _apply(30, 3, TaskType.WALK, "very_high", "adult")
        assert freq == round(3 * ENERGY_FREQUENCY_MULT["very_high"])

    def test_low_energy_decreases_walk_frequency(self):
        _, freq = _apply(30, 3, TaskType.WALK, "low", "adult")
        assert freq == round(3 * ENERGY_FREQUENCY_MULT["low"])

    def test_medium_energy_leaves_frequency_unchanged(self):
        _, freq = _apply(30, 3, TaskType.WALK, "medium", "adult")
        assert freq == 3

    def test_energy_and_age_frequency_combined(self):
        _, freq = _apply(30, 2, TaskType.WALK, "very_high", "puppy")
        expected = max(1, round(2 * ENERGY_FREQUENCY_MULT["very_high"] * AGE_FREQUENCY_MULT["puppy"]))
        assert freq == expected

    def test_very_high_energy_senior_does_not_exceed_adult_very_high(self):
        _, freq_vh_senior = _apply(30, 2, TaskType.WALK, "very_high", "senior")
        _, freq_vh_adult  = _apply(30, 2, TaskType.WALK, "very_high", "adult")
        assert freq_vh_senior < freq_vh_adult

    def test_feeding_frequency_unaffected_by_energy(self):
        _, freq = _apply(15, 2, TaskType.FEEDING, "very_high", "adult")
        assert freq == 2  # non-activity task — unchanged

    def test_frequency_never_below_one(self):
        _, freq = _apply(30, 1, TaskType.WALK, "low", "senior")
        assert freq >= 1


# ---------------------------------------------------------------------------
# Fix #3: Minimum delay between feeding end and medication start
# ---------------------------------------------------------------------------

class TestMedFeedingGapDetection:
    def test_medication_immediately_after_feeding_detected(self):
        owner = make_owner()
        feed = make_st(TaskType.FEEDING, "Feeding", 480, 15)        # 8:00–8:15
        med  = make_st(TaskType.MEDICATION, "Medication", 495, 5)   # 8:15–8:20 — 0 min gap
        plans = single_pet_plans(sts=[feed, med])
        conflicts = detect_conflicts(plans, owner, [])
        mfg = [c for c in conflicts if c.conflict_type == "med_feeding_gap"]
        assert len(mfg) == 1
        assert "Medication" in mfg[0].reason

    def test_medication_after_gap_no_conflict(self):
        owner = make_owner()
        feed = make_st(TaskType.FEEDING, "Feeding", 480, 15)        # 8:00–8:15
        # medication starts after feeding end + _MIN_MED_FEEDING_GAP
        med  = make_st(TaskType.MEDICATION, "Medication", 495 + _MIN_MED_FEEDING_GAP, 5)
        plans = single_pet_plans(sts=[feed, med])
        conflicts = detect_conflicts(plans, owner, [])
        mfg = [c for c in conflicts if c.conflict_type == "med_feeding_gap"]
        assert len(mfg) == 0

    def test_suggested_fix_mentions_correct_time(self):
        owner = make_owner()
        feed = make_st(TaskType.FEEDING, "Feeding", 480, 15)        # ends 8:15
        med  = make_st(TaskType.MEDICATION, "Medication", 495, 5)   # starts 8:15
        plans = single_pet_plans(sts=[feed, med])
        conflicts = detect_conflicts(plans, owner, [])
        mfg = [c for c in conflicts if c.conflict_type == "med_feeding_gap"]
        assert len(mfg) == 1
        # safe start = 8:15 + 10 min = 8:25
        assert "08:25" in mfg[0].suggested_fix

    def test_feeding_before_medication_no_false_positive(self):
        """Medication well after feeding should produce no conflict."""
        owner = make_owner()
        feed = make_st(TaskType.FEEDING, "Feeding", 480, 15)        # 8:00–8:15
        med  = make_st(TaskType.MEDICATION, "Medication", 540, 5)   # 9:00 — 45 min later
        plans = single_pet_plans(sts=[feed, med])
        conflicts = detect_conflicts(plans, owner, [])
        mfg = [c for c in conflicts if c.conflict_type == "med_feeding_gap"]
        assert len(mfg) == 0


# ---------------------------------------------------------------------------
# Fix #4: Enforce minimum gap between care task occurrences
# ---------------------------------------------------------------------------

class TestCareTaskGapConstants:
    def test_feeding_gap_is_at_least_4_hours(self):
        assert _MIN_CARE_TASK_GAP[TaskType.FEEDING] >= 4 * 60

    def test_medication_gap_is_at_least_4_hours(self):
        assert _MIN_CARE_TASK_GAP[TaskType.MEDICATION] >= 4 * 60

    def test_litter_box_gap_is_at_least_2_hours(self):
        assert _MIN_CARE_TASK_GAP[TaskType.LITTER_BOX] >= 2 * 60

    def test_misting_gap_is_at_least_2_hours(self):
        assert _MIN_CARE_TASK_GAP[TaskType.MISTING] >= 2 * 60


# ---------------------------------------------------------------------------
# Fix #5: Feeding frequency scales by age group
# ---------------------------------------------------------------------------

class TestFeedingFrequencyByAge:
    def test_puppy_gets_more_feedings_than_adult(self):
        _, freq_puppy = _apply(15, 2, TaskType.FEEDING, "medium", "puppy")
        _, freq_adult = _apply(15, 2, TaskType.FEEDING, "medium", "adult")
        assert freq_puppy > freq_adult

    def test_adult_feeding_frequency_unchanged(self):
        _, freq = _apply(15, 2, TaskType.FEEDING, "medium", "adult")
        assert freq == 2

    def test_senior_gets_more_feedings_than_adult(self):
        _, freq_senior = _apply(15, 2, TaskType.FEEDING, "medium", "senior")
        _, freq_adult  = _apply(15, 2, TaskType.FEEDING, "medium", "adult")
        assert freq_senior >= freq_adult

    def test_feeding_duration_unaffected_by_age(self):
        dur_puppy, _ = _apply(15, 2, TaskType.FEEDING, "medium", "puppy")
        dur_adult, _ = _apply(15, 2, TaskType.FEEDING, "medium", "adult")
        assert dur_puppy == dur_adult == 15

    def test_feeding_frequency_unaffected_by_energy(self):
        _, freq_hi  = _apply(15, 2, TaskType.FEEDING, "very_high", "adult")
        _, freq_low = _apply(15, 2, TaskType.FEEDING, "low", "adult")
        assert freq_hi == freq_low == 2

    def test_feeding_frequency_never_below_one(self):
        _, freq = _apply(15, 1, TaskType.FEEDING, "medium", "puppy")
        assert freq >= 1

    def test_age_feeding_frequency_mult_constants(self):
        assert AGE_FEEDING_FREQUENCY_MULT["puppy"] > AGE_FEEDING_FREQUENCY_MULT["adult"]
        assert AGE_FEEDING_FREQUENCY_MULT["adult"] == 1.0
        assert AGE_FEEDING_FREQUENCY_MULT["senior"] >= AGE_FEEDING_FREQUENCY_MULT["adult"]


# ---------------------------------------------------------------------------
# Fix #6: Window violation detection (earliest/latest per task)
# ---------------------------------------------------------------------------

class TestWindowViolationDetection:
    def test_task_before_earliest_detected(self):
        owner = make_owner()
        task = Task(TaskType.WALK, name="Walk", duration_minutes=30,
                    earliest=time(10, 0))
        st_early = ScheduledTask(task, time(8, 0), time(8, 30), "test")  # before earliest
        plans = single_pet_plans(sts=[st_early])
        conflicts = detect_conflicts(plans, owner, [])
        wv = [c for c in conflicts if c.conflict_type == "window_violation"]
        assert len(wv) == 1
        assert "before its earliest" in wv[0].reason

    def test_task_after_latest_detected(self):
        owner = make_owner()
        task = Task(TaskType.MEDICATION, name="Medication", duration_minutes=5,
                    latest=time(9, 0))
        st_late = ScheduledTask(task, time(9, 0), time(9, 5), "test")  # ends past latest
        plans = single_pet_plans(sts=[st_late])
        conflicts = detect_conflicts(plans, owner, [])
        wv = [c for c in conflicts if c.conflict_type == "window_violation"]
        assert len(wv) == 1
        assert "after its latest" in wv[0].reason

    def test_task_within_window_no_violation(self):
        owner = make_owner()
        task = Task(TaskType.WALK, name="Walk", duration_minutes=30,
                    earliest=time(8, 0), latest=time(12, 0))
        st_ok = ScheduledTask(task, time(9, 0), time(9, 30), "test")
        plans = single_pet_plans(sts=[st_ok])
        conflicts = detect_conflicts(plans, owner, [])
        wv = [c for c in conflicts if c.conflict_type == "window_violation"]
        assert len(wv) == 0

    def test_task_without_window_constraints_no_violation(self):
        owner = make_owner()
        task = Task(TaskType.FEEDING, name="Feeding", duration_minutes=15)
        st = ScheduledTask(task, time(8, 0), time(8, 15), "test")
        plans = single_pet_plans(sts=[st])
        conflicts = detect_conflicts(plans, owner, [])
        wv = [c for c in conflicts if c.conflict_type == "window_violation"]
        assert len(wv) == 0

    def test_suggested_fix_mentions_earliest_time(self):
        owner = make_owner()
        task = Task(TaskType.WALK, name="Walk", duration_minutes=30,
                    earliest=time(10, 0))
        st_early = ScheduledTask(task, time(8, 0), time(8, 30), "test")
        plans = single_pet_plans(sts=[st_early])
        conflicts = detect_conflicts(plans, owner, [])
        wv = [c for c in conflicts if c.conflict_type == "window_violation"]
        assert "10:00" in wv[0].suggested_fix


# ---------------------------------------------------------------------------
# Coverage window suggestions
# ---------------------------------------------------------------------------

def _make_split_owner(morning_end=time(9, 0), evening_start=time(17, 0)):
    """Owner available 8–9 and 17–20 — big midday gap."""
    o = Owner("Jordan")
    o.add_window(time(8, 0), morning_end)
    o.add_window(evening_start, time(20, 0))
    return o


class TestSuggestCoverageWindows:
    def test_feeding_gap_produces_pet_sitter_suggestion(self):
        owner = _make_split_owner()
        dog = Pet("Buddy", "dog")
        # Schedule feedings at 8:00 and 18:00 — 9-hour gap exceeds 8h threshold.
        feed1 = make_st(TaskType.FEEDING, "Feeding", 480, 15)   # 8:00–8:15
        feed2 = make_st(TaskType.FEEDING, "Feeding", 18 * 60, 15)  # 18:00–18:15
        plan = DailyPlan()
        plan.scheduled.extend([feed1, feed2])
        plans = {"Buddy": plan}
        owner.add_pet(dog)
        suggestions = suggest_coverage_windows(plans, owner, [dog])
        pet_sitters = [s for s in suggestions if s.service_type == "pet_sitter"]
        assert len(pet_sitters) >= 1
        s = pet_sitters[0]
        assert s.pet_name == "Buddy"
        assert "Feeding" in s.tasks

    def test_walk_gap_in_unavailability_block_produces_dog_walker(self):
        owner = _make_split_owner()  # big 8h midday gap
        dog = Pet("Buddy", "dog")
        # Walk before and after the unavailability block.
        walk1 = make_st(TaskType.WALK, "Walk", 480, 30)     # 8:00–8:30
        walk2 = make_st(TaskType.WALK, "Walk", 17 * 60, 30) # 17:00–17:30
        plan = DailyPlan()
        plan.scheduled.extend([walk1, walk2])
        plans = {"Buddy": plan}
        owner.add_pet(dog)
        suggestions = suggest_coverage_windows(plans, owner, [dog])
        walkers = [s for s in suggestions if s.service_type == "dog_walker"]
        assert len(walkers) >= 1
        w = walkers[0]
        assert w.pet_name == "Buddy"

    def test_coverage_window_times_fall_within_gap(self):
        """Suggested start/end must be inside the gap, not outside it."""
        owner = _make_split_owner(morning_end=time(9, 0), evening_start=time(17, 0))
        dog = Pet("Buddy", "dog")
        feed1 = make_st(TaskType.FEEDING, "Feeding", 480, 15)
        feed2 = make_st(TaskType.FEEDING, "Feeding", 17 * 60, 15)
        plan = DailyPlan()
        plan.scheduled.extend([feed1, feed2])
        plans = {"Buddy": plan}
        owner.add_pet(dog)
        suggestions = suggest_coverage_windows(plans, owner, [dog])
        gap_start_mins = _mins(time(9, 0))
        gap_end_mins   = _mins(time(17, 0))
        for s in suggestions:
            s_start = int(s.start[:2]) * 60 + int(s.start[3:])
            s_end   = int(s.end[:2]) * 60 + int(s.end[3:])
            assert s_start >= gap_start_mins, f"Coverage starts before gap: {s.start}"
            assert s_end   <= gap_end_mins,   f"Coverage ends after gap: {s.end}"

    def test_no_suggestions_when_no_gaps(self):
        """Continuous single-window owner with well-spaced tasks needs no coverage."""
        owner = make_owner()  # 8am–8pm, no gap
        dog = Pet("Buddy", "dog")
        feed1 = make_st(TaskType.FEEDING, "Feeding", 480, 15)   # 8:00
        feed2 = make_st(TaskType.FEEDING, "Feeding", 720, 15)   # 12:00 — 3h45m apart, fine
        plan = DailyPlan()
        plan.scheduled.extend([feed1, feed2])
        plans = {"Buddy": plan}
        owner.add_pet(dog)
        suggestions = suggest_coverage_windows(plans, owner, [dog])
        assert not suggestions

    def test_coverage_windows_have_required_fields(self):
        owner = _make_split_owner()
        dog = Pet("Buddy", "dog")
        feed1 = make_st(TaskType.FEEDING, "Feeding", 480, 15)
        feed2 = make_st(TaskType.FEEDING, "Feeding", 18 * 60, 15)
        plan = DailyPlan()
        plan.scheduled.extend([feed1, feed2])
        plans = {"Buddy": plan}
        owner.add_pet(dog)
        for s in suggest_coverage_windows(plans, owner, [dog]):
            assert s.service_type in {"dog_walker", "pet_sitter", "owner_window"}
            assert ":" in s.start and ":" in s.end
            assert isinstance(s.tasks, list)
            assert isinstance(s.reason, str) and len(s.reason) > 0

    def test_no_duplicate_suggestions(self):
        owner = _make_split_owner()
        dog = Pet("Buddy", "dog")
        feed1 = make_st(TaskType.FEEDING, "Feeding", 480, 15)
        feed2 = make_st(TaskType.FEEDING, "Feeding", 18 * 60, 15)
        plan = DailyPlan()
        plan.scheduled.extend([feed1, feed2])
        plans = {"Buddy": plan}
        owner.add_pet(dog)
        suggestions = suggest_coverage_windows(plans, owner, [dog])
        keys = [(s.service_type, s.pet_name, s.start, s.end) for s in suggestions]
        assert len(keys) == len(set(keys)), "Duplicate coverage suggestions found"


class TestPetTaskDefaults:
    """Verify the task-default callback logic — mirrors _reset_tasks_for_type in app.py."""
    def _defaults_for(self, pet_type: str):
        return list(PET_TASK_DEFAULTS.get(pet_type, [TaskType.FEEDING]))

    def test_fish_has_no_walk(self):
        assert TaskType.WALK not in self._defaults_for("fish")

    def test_fish_has_no_fetch(self):
        assert TaskType.FETCH not in self._defaults_for("fish")

    def test_fish_has_feeding_and_tank_maintenance(self):
        defaults = self._defaults_for("fish")
        assert TaskType.FEEDING in defaults
        assert TaskType.TANK_MAINTENANCE in defaults

    def test_cat_has_no_walk(self):
        assert TaskType.WALK not in self._defaults_for("cat")

    def test_cat_has_litter_box(self):
        assert TaskType.LITTER_BOX in self._defaults_for("cat")

    def test_dog_has_walk(self):
        assert TaskType.WALK in self._defaults_for("dog")

    def test_dog_has_fetch(self):
        assert TaskType.FETCH in self._defaults_for("dog")

    def test_snake_has_misting(self):
        assert TaskType.MISTING in self._defaults_for("snake")

    def test_snake_has_no_walk(self):
        assert TaskType.WALK not in self._defaults_for("snake")

    def test_all_pet_types_have_feeding(self):
        for pet_type in ["dog", "cat", "rabbit", "bird", "snake", "iguana", "fish", "other"]:
            assert TaskType.FEEDING in self._defaults_for(pet_type), \
                f"{pet_type} defaults missing FEEDING"
