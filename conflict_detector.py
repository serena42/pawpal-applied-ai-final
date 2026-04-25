from dataclasses import dataclass, field
from models import _mins, _GAP_THRESHOLDS


@dataclass
class Conflict:
    conflict_type: str  # "overlap", "dependency", "timeout", "outside_window", "gap"
    reason: str
    suggested_fix: str
    task_keys: tuple = field(default_factory=tuple)


def _t(t) -> str:
    return t.strftime("%H:%M")


def _overlap(st1, st2) -> bool:
    return _mins(st1.start_time) < _mins(st2.end_time) and _mins(st2.start_time) < _mins(st1.end_time)


def _in_any_window(windows, start_mins: int, end_mins: int) -> bool:
    for w in windows:
        if _mins(w.start) <= start_mins and end_mins <= _mins(w.end):
            return True
    return False


def detect_conflicts(plans: dict, owner, pets) -> list:
    """
    Return list of Conflict objects for a multi-pet schedule.

    plans: dict[pet_name, DailyPlan] — output of Scheduler.generate_all_plans()
    Detects: overlap, dependency violation, timeout, outside availability window, recurrence gap.
    """
    conflicts = []

    # Flatten all scheduled tasks with pet context.
    all_tasks = [
        (pet_name, st)
        for pet_name, plan in plans.items()
        for st in plan.scheduled
    ]

    # 1. Overlap: any two tasks occupying the same time slot.
    for i, (p1, st1) in enumerate(all_tasks):
        for p2, st2 in all_tasks[i + 1:]:
            if _overlap(st1, st2):
                conflicts.append(Conflict(
                    conflict_type="overlap",
                    reason=(
                        f"{st1.task.name} ({p1}, {_t(st1.start_time)}–{_t(st1.end_time)}) "
                        f"overlaps {st2.task.name} ({p2}, {_t(st2.start_time)}–{_t(st2.end_time)})"
                    ),
                    suggested_fix=f"Move {st2.task.name} to {_t(st1.end_time)} or later",
                    task_keys=((p1, st1.task.name), (p2, st2.task.name)),
                ))

    # 2. Dependency violations: task scheduled before a dependency finishes.
    task_lookup = {(p, id(st.task)): st for p, st in all_tasks}
    for pet_name, st in all_tasks:
        for dep in st.task.dependencies:
            dep_st = task_lookup.get((pet_name, id(dep)))
            if dep_st and _mins(dep_st.end_time) > _mins(st.start_time):
                conflicts.append(Conflict(
                    conflict_type="dependency",
                    reason=(
                        f"{st.task.name} ({pet_name}) starts at {_t(st.start_time)} "
                        f"before dependency {dep_st.task.name} ends at {_t(dep_st.end_time)}"
                    ),
                    suggested_fix=f"Move {st.task.name} to after {_t(dep_st.end_time)}",
                    task_keys=((pet_name, dep_st.task.name), (pet_name, st.task.name)),
                ))

    # 3. Timeout: task ends after all availability windows close.
    if owner.availability_windows:
        owner_end_mins = max(_mins(w.end) for w in owner.availability_windows)
        for pet_name, st in all_tasks:
            if _mins(st.end_time) > owner_end_mins:
                from models import _to_time
                conflicts.append(Conflict(
                    conflict_type="timeout",
                    reason=(
                        f"{st.task.name} ({pet_name}) ends at {_t(st.end_time)}, "
                        f"past last availability window end {_t(_to_time(owner_end_mins))}"
                    ),
                    suggested_fix=f"Move {st.task.name} earlier in the day",
                    task_keys=((pet_name, st.task.name),),
                ))

    # 4. Outside availability windows: task scheduled in a gap between windows.
    if owner.availability_windows:
        window_str = ", ".join(f"{_t(w.start)}-{_t(w.end)}" for w in owner.availability_windows)
        for pet_name, st in all_tasks:
            start = _mins(st.start_time)
            end = _mins(st.end_time)
            if not _in_any_window(owner.availability_windows, start, end):
                conflicts.append(Conflict(
                    conflict_type="outside_window",
                    reason=(
                        f"{st.task.name} ({pet_name}) at {_t(st.start_time)}–{_t(st.end_time)} "
                        f"falls outside any availability window"
                    ),
                    suggested_fix=f"Move {st.task.name} to within an available window: {window_str}",
                    task_keys=((pet_name, st.task.name),),
                ))

    # 5. Recurrence gap: consecutive occurrences too far apart.
    for pet_name, plan in plans.items():
        by_type: dict = {}
        for st in plan.scheduled:
            by_type.setdefault(st.task.task_type, []).append(st)

        for task_type, occs in by_type.items():
            threshold = _GAP_THRESHOLDS.get(task_type)
            if threshold is None or len(occs) < 2:
                continue
            occs.sort(key=lambda s: _mins(s.start_time))
            for i in range(len(occs) - 1):
                gap = _mins(occs[i + 1].start_time) - _mins(occs[i].end_time)
                if gap > threshold:
                    conflicts.append(Conflict(
                        conflict_type="gap",
                        reason=(
                            f"{task_type.value.capitalize()} for {pet_name}: "
                            f"gap of {gap // 60}h {gap % 60}m between occurrences exceeds "
                            f"max {threshold // 60}h"
                        ),
                        suggested_fix=f"Move the later {task_type.value} occurrence earlier",
                        task_keys=(
                            (pet_name, occs[i].task.name),
                            (pet_name, occs[i + 1].task.name),
                        ),
                    ))

    return conflicts
