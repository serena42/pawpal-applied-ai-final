from dataclasses import dataclass, field
from models import _mins, _to_time, _GAP_THRESHOLDS, _MIN_ACTIVITY_GAP, ACTIVITY_TASKS, VIGOROUS_TASKS, POST_FEEDING_GAP, TaskType, _MIN_MED_FEEDING_GAP


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

    # 6. Window violation: task scheduled outside its own earliest/latest constraints.
    for pet_name, st in all_tasks:
        task = st.task
        if task.earliest and _mins(st.start_time) < _mins(task.earliest):
            conflicts.append(Conflict(
                conflict_type="window_violation",
                reason=(
                    f"{task.name} ({pet_name}) starts at {_t(st.start_time)}, "
                    f"before its earliest allowed time {_t(task.earliest)}"
                ),
                suggested_fix=f"Move {task.name} to {_t(task.earliest)} or later",
                task_keys=((pet_name, task.name),),
            ))
        if task.latest and _mins(st.end_time) > _mins(task.latest):
            conflicts.append(Conflict(
                conflict_type="window_violation",
                reason=(
                    f"{task.name} ({pet_name}) ends at {_t(st.end_time)}, "
                    f"after its latest allowed time {_t(task.latest)}"
                ),
                suggested_fix=f"Move {task.name} earlier so it finishes by {_t(task.latest)}",
                task_keys=((pet_name, task.name),),
            ))

    # 7. Medication too soon after feeding.
    for pet_name, plan in plans.items():
        feedings   = [st for st in plan.scheduled if st.task.task_type == TaskType.FEEDING]
        meds       = [st for st in plan.scheduled if st.task.task_type == TaskType.MEDICATION]
        for feed_st in feedings:
            feed_end = _mins(feed_st.end_time)
            for med_st in meds:
                med_start = _mins(med_st.start_time)
                if feed_end <= med_start < feed_end + _MIN_MED_FEEDING_GAP:
                    gap_min = med_start - feed_end
                    ok_time = _to_time(feed_end + _MIN_MED_FEEDING_GAP).strftime("%H:%M")
                    conflicts.append(Conflict(
                        conflict_type="med_feeding_gap",
                        reason=(
                            f"{med_st.task.name} ({pet_name}) starts at {_t(med_st.start_time)}, "
                            f"only {gap_min} min after {feed_st.task.name} ends at {_t(feed_st.end_time)} "
                            f"— allow at least {_MIN_MED_FEEDING_GAP} min for food to settle"
                        ),
                        suggested_fix=f"Move {med_st.task.name} to {ok_time} or later",
                        task_keys=((pet_name, feed_st.task.name), (pet_name, med_st.task.name)),
                    ))

    # 7. Post-feeding gap: vigorous activity starting within POST_FEEDING_GAP of feeding end.
    for pet_name, plan in plans.items():
        feedings = [st for st in plan.scheduled if st.task.task_type == TaskType.FEEDING]
        vigorous = [st for st in plan.scheduled if st.task.task_type in VIGOROUS_TASKS]
        for feed_st in feedings:
            feed_end = _mins(feed_st.end_time)
            for act_st in vigorous:
                act_start = _mins(act_st.start_time)
                if feed_end <= act_start < feed_end + POST_FEEDING_GAP:
                    gap_min = act_start - feed_end
                    ok_time = _to_time(feed_end + POST_FEEDING_GAP).strftime("%H:%M")
                    conflicts.append(Conflict(
                        conflict_type="post_feeding_gap",
                        reason=(
                            f"{act_st.task.name} ({pet_name}) starts at {_t(act_st.start_time)}, "
                            f"only {gap_min} min after {feed_st.task.name} ends at {_t(feed_st.end_time)} "
                            f"— vigorous activity too soon after eating risks gastric torsion"
                        ),
                        suggested_fix=f"Move {act_st.task.name} to {ok_time} or later",
                        task_keys=((pet_name, feed_st.task.name), (pet_name, act_st.task.name)),
                    ))

    return conflicts


@dataclass
class SuggestedSlot:
    pet_name: str
    task_name: str
    earliest: str   # "HH:MM" — earliest time the slot is useful
    latest: str     # "HH:MM" — latest time the slot is useful
    suggested: str  # "HH:MM" — midpoint recommendation
    reason: str


def detect_suggested_slots(plans: dict, pets: list = None) -> list[SuggestedSlot]:
    """
    Return suggested availability windows wherever same-type tasks violate the
    minimum inter-session gap. The recommended slot sits in the gap before the cluster.
    """
    pet_map = {p.name: p for p in (pets or [])}
    slots = []

    for pet_name, plan in plans.items():
        by_type: dict = {}
        for st in plan.scheduled:
            by_type.setdefault(st.task.task_type, []).append(st)

        pet = pet_map.get(pet_name)
        for task_type, occs in by_type.items():
            if len(occs) < 2:
                continue
            occs.sort(key=lambda s: _mins(s.start_time))

            # Determine required minimum gap for this task type / age group.
            if task_type in ACTIVITY_TASKS and pet:
                min_gap = _MIN_ACTIVITY_GAP.get(pet.age_group, 180)
            else:
                min_gap = 0

            for i in range(len(occs) - 1):
                actual_gap = _mins(occs[i + 1].start_time) - _mins(occs[i].end_time)
                if actual_gap >= min_gap:
                    continue  # gap is acceptable

                # Walk back to find the start of this violation cluster.
                j = i
                while j > 0 and (_mins(occs[j].start_time) - _mins(occs[j - 1].end_time)) < min_gap:
                    j -= 1
                cluster_block_start = _mins(occs[j].start_time)
                prev_end = _mins(occs[j - 1].end_time) if j > 0 else 0

                gap_before = cluster_block_start - prev_end
                if gap_before <= 0:
                    continue

                dur = occs[i].task.duration_minutes
                earliest_mins = prev_end + 30
                # Latest useful = must finish the session AND leave min_gap before the cluster.
                latest_mins = cluster_block_start - min_gap - dur
                if latest_mins <= earliest_mins:
                    continue

                suggested_mins = (earliest_mins + latest_mins) // 2
                gap_h, gap_m = min_gap // 60, min_gap % 60
                gap_str = f"{gap_h}h" if gap_m == 0 else f"{gap_h}h {gap_m}m"

                slots.append(SuggestedSlot(
                    pet_name=pet_name,
                    task_name=task_type.value.capitalize(),
                    earliest=_to_time(earliest_mins).strftime("%H:%M"),
                    latest=_to_time(latest_mins).strftime("%H:%M"),
                    suggested=_to_time(suggested_mins).strftime("%H:%M"),
                    reason=(
                        f"{task_type.value.capitalize()} sessions for {pet_name} are "
                        f"less than {gap_str} apart. A slot ending by "
                        f"{_to_time(latest_mins + dur).strftime('%H:%M')} would provide "
                        f"the needed spacing before the {_to_time(cluster_block_start).strftime('%H:%M')} session."
                    ),
                ))
                break  # one suggestion per task type per pet

    return slots


def recommend_service(conflicts: list) -> str | None:
    """
    Return a human-readable service recommendation based on unresolved conflicts,
    or None if no recommendation is needed.
    """
    if not conflicts:
        return None

    types = {c.conflict_type for c in conflicts}

    # Pull pet names and task names from the conflicts for a specific message.
    pet_names = []
    for c in conflicts:
        for key in c.task_keys:
            if key and key[0] not in pet_names:
                pet_names.append(key[0])
    pets_str = " and ".join(pet_names) if pet_names else "your pet(s)"

    walk_gap = any(
        c.conflict_type == "gap" and "walk" in c.reason.lower()
        for c in conflicts
    )
    feed_gap = any(
        c.conflict_type == "gap" and "feeding" in c.reason.lower()
        for c in conflicts
    )

    if walk_gap:
        return (
            f"A **dog walking service** could cover midday walks for {pets_str}, "
            "closing the gap between morning and evening sessions."
        )
    if feed_gap or "gap" in types:
        return (
            f"A **pet sitter** could stop by midday to handle feedings and check-ins "
            f"for {pets_str}, keeping recurring tasks within the recommended time window."
        )
    if "outside_window" in types or "timeout" in types:
        return (
            f"Some tasks fall outside your available hours. A **pet sitter** could "
            f"cover care for {pets_str} during the times you're unavailable."
        )
    if "overlap" in types:
        return (
            f"The schedule is too packed to resolve all overlaps. A **dog walker** "
            f"could take over some tasks for {pets_str} and free up time slots."
        )

    return (
        "Consider booking a **pet care service** to handle tasks that don't fit "
        "within your current availability."
    )
