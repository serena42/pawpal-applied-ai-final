"""
Unit tests for conflict_detector.py and agent.py (fix-application logic only).
API-calling methods are not tested here — they require a live key.

Run:
    pytest test_agent.py -v
"""

import pytest
from datetime import time

from models import Owner, Pet, Task, TaskType, DailyPlan, ScheduledTask, _to_time
from conflict_detector import detect_conflicts, Conflict
from agent import ScheduleAgent


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
