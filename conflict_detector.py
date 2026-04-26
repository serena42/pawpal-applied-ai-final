import re
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


@dataclass
class CoverageWindow:
    """A specific time slot where an external service would resolve scheduling issues."""
    service_type: str   # "dog_walker" | "pet_sitter" | "owner_window"
    pet_name: str
    start: str          # "HH:MM"
    end: str            # "HH:MM"
    tasks: list
    reason: str


def suggest_coverage_windows(plans: dict, owner, pets) -> list[CoverageWindow]:
    """
    Compute specific time windows where a pet sitter, dog walker, or owner
    availability expansion would resolve unresolvable conflicts.

    Scans for:
    - Gap violations between recurring care task occurrences (too long between feedings etc.)
    - Walk/activity gaps that fall entirely inside an owner unavailability block
    - Tasks dropped from warnings (couldn't be scheduled at all)
    """
    pet_map = {p.name: p for p in (pets or [])}
    suggestions: list[CoverageWindow] = []
    seen: set = set()

    # Build the list of gaps between owner availability windows.
    owner_windows = sorted(owner.availability_windows, key=lambda w: _mins(w.start))
    unavail_blocks = []
    for i in range(len(owner_windows) - 1):
        unavail_blocks.append((_mins(owner_windows[i].end), _mins(owner_windows[i + 1].start)))

    def _add(cw: CoverageWindow) -> None:
        key = (cw.service_type, cw.pet_name, cw.start, cw.end)
        if key not in seen:
            seen.add(key)
            suggestions.append(cw)

    for pet_name, plan in plans.items():
        by_type: dict = {}
        for s in plan.scheduled:
            by_type.setdefault(s.task.task_type, []).append(s)

        # 1. Gap conflicts: two occurrences of the same task type too far apart.
        for task_type, occs in by_type.items():
            threshold = _GAP_THRESHOLDS.get(task_type)
            if threshold is None or len(occs) < 2:
                continue
            occs.sort(key=lambda s: _mins(s.start_time))
            for i in range(len(occs) - 1):
                gap_start = _mins(occs[i].end_time)
                gap_end   = _mins(occs[i + 1].start_time)
                gap       = gap_end - gap_start
                if gap <= threshold:
                    continue

                task_dur = occs[i].task.duration_minutes
                buf      = 30
                # Place the coverage window in the middle of the gap.
                ideal_start = gap_start + max(buf, (gap - task_dur - buf) // 2)
                ideal_end   = min(gap_end - buf, ideal_start + task_dur + buf)
                # Clamp to a realistic range.
                ideal_start = max(gap_start + buf, ideal_start)
                ideal_end   = min(gap_end - buf, ideal_end)
                if ideal_end <= ideal_start:
                    ideal_start = gap_start + buf
                    ideal_end   = min(gap_end, ideal_start + task_dur + buf)

                is_walk   = task_type == TaskType.WALK
                service   = "dog_walker" if is_walk else "pet_sitter"
                label     = task_type.value.capitalize()
                gap_h, gap_m = gap // 60, gap % 60
                gap_str   = f"{gap_h}h" + (f" {gap_m}m" if gap_m else "")

                _add(CoverageWindow(
                    service_type=service,
                    pet_name=pet_name,
                    start=_to_time(ideal_start).strftime("%H:%M"),
                    end=_to_time(ideal_end).strftime("%H:%M"),
                    tasks=[label],
                    reason=(
                        f"{label} for {pet_name} has a {gap_str} gap between occurrences "
                        f"(max recommended {threshold // 60}h). "
                        f"A {'dog walker' if is_walk else 'pet sitter'} visiting from "
                        f"{_to_time(ideal_start).strftime('%H:%M')} to "
                        f"{_to_time(ideal_end).strftime('%H:%M')} would close it."
                    ),
                ))

        # 2. Walk/activity gaps inside unavailability blocks.
        # Skip if the scheduler already dropped walk occurrences — section 3
        # generates a slot for each missing occurrence, making this redundant.
        walk_task_names = {s.task.name for s in by_type.get(TaskType.WALK, [])}
        _dropped_walk = any(
            re.search(rf"'{re.escape(n)}': only \d+ of \d+ occurrences scheduled", w)
            for w in plan.warnings
            for n in walk_task_names
        )
        walk_occs = sorted(by_type.get(TaskType.WALK, []), key=lambda s: _mins(s.start_time))
        for block_start, block_end in unavail_blocks if not _dropped_walk else []:
            # Is there a walk on either side of this unavailability block?
            before = [s for s in walk_occs if _mins(s.end_time) <= block_start]
            after  = [s for s in walk_occs if _mins(s.start_time) >= block_end]
            if not before or not after:
                continue
            gap = block_end - block_start
            if gap < 30:
                continue
            mid   = (block_start + block_end) // 2
            cstart = max(block_start + 15, mid - 25)
            cend   = min(block_end - 15, cstart + 50)
            _add(CoverageWindow(
                service_type="dog_walker",
                pet_name=pet_name,
                start=_to_time(cstart).strftime("%H:%M"),
                end=_to_time(cend).strftime("%H:%M"),
                tasks=["Walk"],
                reason=(
                    f"A midday walk for {pet_name} isn't covered during your unavailability "
                    f"({_to_time(block_start).strftime('%H:%M')}–{_to_time(block_end).strftime('%H:%M')}). "
                    f"A dog walker from {_to_time(cstart).strftime('%H:%M')} to "
                    f"{_to_time(cend).strftime('%H:%M')} fills the gap."
                ),
            ))

        # 3. Dropped tasks — one specific coverage window per dropped occurrence.
        #    Parse each "only M of N occurrences scheduled" warning, find the scheduled
        #    occurrences of that task, locate the largest gap between them, and place
        #    the suggested coverage slot at the midpoint of that gap.
        _drop_pat = re.compile(r"'([^']+)': only (\d+) of (\d+) occurrences scheduled")
        for warn in plan.warnings:
            match = _drop_pat.search(warn)
            if match is None:
                continue
            task_name_w = match.group(1)
            scheduled_n = int(match.group(2))
            needed_n    = int(match.group(3))
            dropped_n   = needed_n - scheduled_n
            if dropped_n <= 0:
                continue

            matched_occs = [st for st in plan.scheduled if st.task.name == task_name_w]
            if not matched_occs:
                continue  # dropped completely — no anchors to place the window against

            task_type_d = matched_occs[0].task.task_type
            task_dur_d  = matched_occs[0].task.duration_minutes
            is_walk_d   = task_type_d == TaskType.WALK
            service_d   = "dog_walker" if is_walk_d else "pet_sitter"

            occs_sorted = sorted(matched_occs, key=lambda s: _mins(s.start_time))
            day_s = _mins(owner_windows[0].start) if owner_windows else 0
            day_e = _mins(owner_windows[-1].end)  if owner_windows else 1440

            # Gaps: before first occurrence, between pairs, after last.
            gap_list: list[tuple[int, int]] = []
            prev = day_s
            for occ in occs_sorted:
                gap_list.append((prev, _mins(occ.start_time)))
                prev = _mins(occ.end_time)
            gap_list.append((prev, day_e))

            for _ in range(dropped_n):
                if not gap_list:
                    break
                g_start, g_end = max(gap_list, key=lambda g: g[1] - g[0])
                if g_end - g_start < task_dur_d + 30:
                    break

                ideal_start = max(g_start + 15, (g_start + g_end) // 2 - task_dur_d // 2)
                ideal_end   = min(g_end - 15, ideal_start + task_dur_d + 30)
                if ideal_end <= ideal_start:
                    break

                _add(CoverageWindow(
                    service_type=service_d,
                    pet_name=pet_name,
                    start=_to_time(ideal_start).strftime("%H:%M"),
                    end=_to_time(ideal_end).strftime("%H:%M"),
                    tasks=[task_name_w],
                    reason=(
                        f"{task_name_w} for {pet_name}: {dropped_n} of {needed_n} daily "
                        f"occurrence(s) couldn't fit in the available windows. "
                        f"A {'dog walker' if is_walk_d else 'pet sitter'} from "
                        f"{_to_time(ideal_start).strftime('%H:%M')} to "
                        f"{_to_time(ideal_end).strftime('%H:%M')} covers the missing occurrence."
                    ),
                ))

                # Split the used gap around the new slot for subsequent iterations.
                gap_list.remove((g_start, g_end))
                if ideal_start - 10 > g_start:
                    gap_list.append((g_start, ideal_start - 10))
                if g_end > ideal_end + 10:
                    gap_list.append((ideal_end + 10, g_end))

    return suggestions
