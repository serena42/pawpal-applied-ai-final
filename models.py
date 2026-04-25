from __future__ import annotations
from datetime import time
from enum import Enum
from typing import Optional


class TaskType(Enum):
    # Core care
    WALK           = "walk"
    FEEDING        = "feeding"
    MEDICATION     = "medication"
    GROOMING       = "grooming"
    # Enrichment
    ENRICHMENT     = "enrichment"
    FETCH          = "fetch"
    LASER_POINTER  = "laser pointer"
    PLAYTIME       = "playtime"
    TRAINING       = "training"
    FORAGING       = "foraging"
    SOCIALIZING    = "socializing"
    # Hygiene / maintenance
    LITTER_BOX     = "litter box"
    TEETH_BRUSHING = "teeth brushing"
    NAIL_TRIM      = "nail trim"
    BATH           = "bath"
    # Reptile / fish specific
    MISTING        = "misting"
    UV_CHECK       = "uv check"
    TANK_MAINTENANCE = "tank maintenance"
    # Catch-all
    OTHER          = "other"


# Default values per task type: (duration_minutes, frequency_per_day, priority)
_TASK_DEFAULTS: dict[TaskType, tuple[int, int, int]] = {
    TaskType.WALK:             (30, 3, 1),
    TaskType.FEEDING:          (15, 2, 1),
    TaskType.MEDICATION:       (5,  1, 1),
    TaskType.GROOMING:         (30, 1, 3),
    TaskType.ENRICHMENT:       (20, 1, 2),
    TaskType.FETCH:            (20, 2, 2),
    TaskType.LASER_POINTER:    (10, 2, 3),
    TaskType.PLAYTIME:         (20, 2, 2),
    TaskType.TRAINING:         (15, 1, 2),
    TaskType.FORAGING:         (15, 1, 2),
    TaskType.SOCIALIZING:      (20, 3, 1),
    TaskType.LITTER_BOX:       (10, 2, 1),
    TaskType.TEETH_BRUSHING:   (5,  1, 3),
    TaskType.NAIL_TRIM:        (10, 1, 3),
    TaskType.BATH:             (30, 1, 3),
    TaskType.MISTING:          (5,  2, 1),
    TaskType.UV_CHECK:         (5,  1, 1),
    TaskType.TANK_MAINTENANCE: (20, 1, 2),
    TaskType.OTHER:            (15, 1, 2),
}

# Emoji icon per task type — used in both CLI and Streamlit output.
TASK_EMOJI: dict[TaskType, str] = {
    TaskType.WALK:             "🦮",
    TaskType.FEEDING:          "🍽️",
    TaskType.MEDICATION:       "💊",
    TaskType.GROOMING:         "✂️",
    TaskType.ENRICHMENT:       "🧩",
    TaskType.FETCH:            "🎾",
    TaskType.LASER_POINTER:    "🔴",
    TaskType.PLAYTIME:         "🎮",
    TaskType.TRAINING:         "🎓",
    TaskType.FORAGING:         "🌿",
    TaskType.SOCIALIZING:      "👥",
    TaskType.LITTER_BOX:       "🪣",
    TaskType.TEETH_BRUSHING:   "🦷",
    TaskType.NAIL_TRIM:        "💅",
    TaskType.BATH:             "🛁",
    TaskType.MISTING:          "💦",
    TaskType.UV_CHECK:         "☀️",
    TaskType.TANK_MAINTENANCE: "🐠",
    TaskType.OTHER:            "📋",
}

# Emoji icon per pet type.
PET_EMOJI: dict[str, str] = {
    "dog":    "🐕",
    "cat":    "🐈",
    "rabbit": "🐇",
    "bird":   "🐦",
    "snake":  "🐍",
    "iguana": "🦎",
    "fish":   "🐟",
    "other":  "🐾",
}

# Energy and age adjustment multipliers applied to activity tasks.
ENERGY_DURATION_MULT: dict[str, float] = {
    "low":       0.8,
    "medium":    1.0,
    "high":      1.2,
    "very_high": 1.5,
}

AGE_DURATION_MULT: dict[str, float] = {
    "puppy":  0.75,
    "adult":  1.0,
    "senior": 0.8,
}

AGE_FREQUENCY_MULT: dict[str, float] = {
    "puppy":  1.5,
    "adult":  1.0,
    "senior": 0.8,
}

ENERGY_FREQUENCY_MULT: dict[str, float] = {
    "low":       0.8,
    "medium":    1.0,
    "high":      1.2,
    "very_high": 1.5,
}

# Only exercise/enrichment tasks scale with energy and age; care tasks do not.
ACTIVITY_TASKS: frozenset = frozenset({
    TaskType.WALK, TaskType.FETCH, TaskType.PLAYTIME,
    TaskType.TRAINING, TaskType.ENRICHMENT, TaskType.SOCIALIZING,
})

# Physically vigorous tasks that risk bloat/gastric torsion if done too soon after feeding.
VIGOROUS_TASKS: frozenset = frozenset({
    TaskType.WALK, TaskType.FETCH, TaskType.PLAYTIME,
})

# Minutes of rest required after feeding before a vigorous activity may start.
POST_FEEDING_GAP: int = 30

# Minimum gap (minutes) required between consecutive occurrences of any activity task.
# Puppies need frequent short sessions; seniors need longer rests between.
_MIN_ACTIVITY_GAP: dict[str, int] = {
    "puppy":  60,   # 1 hour — puppies need frequent outings but shorter rests
    "adult":  180,  # 3 hours between activity sessions for adult dogs
    "senior": 240,  # 4 hours — fewer, more spaced sessions for seniors
}

# Suggested default tasks per pet type, shown pre-selected in the UI.
PET_TASK_DEFAULTS: dict[str, list[TaskType]] = {
    "dog":     [TaskType.WALK, TaskType.FEEDING, TaskType.TRAINING, TaskType.FETCH],
    "cat":     [TaskType.FEEDING, TaskType.LITTER_BOX, TaskType.LASER_POINTER, TaskType.PLAYTIME],
    "rabbit":  [TaskType.FEEDING, TaskType.ENRICHMENT, TaskType.FORAGING, TaskType.GROOMING],
    "bird":    [TaskType.FEEDING, TaskType.SOCIALIZING, TaskType.ENRICHMENT],
    "snake":   [TaskType.FEEDING, TaskType.MISTING, TaskType.UV_CHECK],
    "iguana":  [TaskType.FEEDING, TaskType.MISTING, TaskType.UV_CHECK, TaskType.GROOMING],
    "fish":    [TaskType.FEEDING, TaskType.TANK_MAINTENANCE],
    "other":   [TaskType.FEEDING, TaskType.ENRICHMENT],
}


class Task:
    def __init__(
        self,
        task_type: TaskType,
        name: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        frequency: Optional[int] = None,
        priority: Optional[int] = None,
        earliest: Optional[time] = None,
        latest: Optional[time] = None,
        dependencies: Optional[list[Task]] = None,
    ):
        defaults = _TASK_DEFAULTS[task_type]
        self.task_type = task_type
        self.name = name or task_type.value.capitalize()
        self.duration_minutes = duration_minutes if duration_minutes is not None else defaults[0]
        self.frequency = frequency if frequency is not None else defaults[1]
        self.priority = priority if priority is not None else defaults[2]
        self.earliest = earliest
        self.latest = latest
        self.dependencies: list[Task] = dependencies or []
        self.completed: bool = False

    def mark_complete(self) -> None:
        self.completed = True

    def __repr__(self) -> str:
        status = "✓" if self.completed else "○"
        return f"Task({self.name}, {self.frequency}x/day, {self.duration_minutes}min, priority={self.priority}, {status})"


class AvailabilityWindow:
    def __init__(self, start: time, end: time):
        self.start = start
        self.end = end

    def duration_minutes(self) -> int:
        start_mins = self.start.hour * 60 + self.start.minute
        end_mins = self.end.hour * 60 + self.end.minute
        return end_mins - start_mins

    def __repr__(self) -> str:
        return f"AvailabilityWindow({self.start} - {self.end})"


class Owner:
    def __init__(self, name: str):
        self.name = name
        self.availability_windows: list[AvailabilityWindow] = []
        self.pets: list[Pet] = []

    def add_window(self, start: time, end: time) -> None:
        self.availability_windows.append(AvailabilityWindow(start, end))

    def add_pet(self, pet: Pet) -> None:
        self.pets.append(pet)

    def __repr__(self) -> str:
        return f"Owner({self.name}, {len(self.availability_windows)} windows, {len(self.pets)} pets)"


class Pet:
    def __init__(self, name: str, pet_type: str, energy_level: str = "medium", age_group: str = "adult"):
        self.name = name
        self.pet_type = pet_type
        self.energy_level = energy_level
        self.age_group = age_group
        self.tasks: list[Task] = []

    def add_task(self, task: Task) -> None:
        self.tasks.append(task)

    def list_tasks(self) -> list[Task]:
        """Return tasks sorted by priority (1 = highest)."""
        return sorted(self.tasks, key=lambda t: t.priority)

    def __repr__(self) -> str:
        return f"Pet({self.name}, {self.pet_type}, {self.energy_level}, {self.age_group}, {len(self.tasks)} tasks)"


class ScheduledTask:
    def __init__(self, task: Task, start_time: time, end_time: time, reason: str):
        self.task = task
        self.start_time = start_time
        self.end_time = end_time
        self.reason = reason

    def __repr__(self) -> str:
        return f"ScheduledTask({self.task.name}, {self.start_time} - {self.end_time})"


class DailyPlan:
    def __init__(self):
        self.scheduled: list[ScheduledTask] = []
        self.warnings: list[str] = []

    def display(self) -> None:
        pass  # TODO: implement display logic

    def __repr__(self) -> str:
        return f"DailyPlan({len(self.scheduled)} tasks, {len(self.warnings)} warnings)"


def _mins(t: time) -> int:
    """Convert a time object to minutes since midnight."""
    return t.hour * 60 + t.minute


def _to_time(mins: int) -> time:
    """Convert minutes since midnight to a time object."""
    return time(mins // 60, mins % 60)


# Maximum allowed gap (in minutes) between consecutive occurrences of a task type.
_GAP_THRESHOLDS: dict[TaskType, int] = {
    TaskType.FEEDING:    8 * 60,
    TaskType.MEDICATION: 13 * 60,
    TaskType.LITTER_BOX: 8 * 60,
    TaskType.MISTING:    10 * 60,
}


class Scheduler:
    def __init__(self, owner: Owner, pet: Pet):
        self.owner = owner
        self.pet = pet

    def generate_all_plans(self) -> dict[str, DailyPlan]:
        """Generate a plan for every pet attached to the owner, sharing busy slots."""
        shared_busy: list[tuple[int, int]] = []
        results = {}
        for pet in self.owner.pets:
            results[pet.name] = Scheduler(self.owner, pet).generate_plan(shared_busy)
        return results

    def generate_plan(self, shared_busy: Optional[list[tuple[int, int]]] = None) -> DailyPlan:
        plan = DailyPlan()
        ordered = self._sort_by_priority()

        if not self.owner.availability_windows:
            return plan

        windows = sorted(self.owner.availability_windows, key=lambda w: _mins(w.start))
        day_start = _mins(windows[0].start)
        day_end = _mins(windows[-1].end)
        day_span = day_end - day_start

        busy: list[tuple[int, int]] = shared_busy if shared_busy is not None else []

        for task in ordered:
            scheduled_count = 0
            interval = day_span // task.frequency if task.frequency > 1 else day_span
            # Minimum gap between consecutive occurrences of this task.
            min_gap = (
                _MIN_ACTIVITY_GAP.get(self.pet.age_group, 180)
                if task.task_type in ACTIVITY_TASKS else 0
            )
            # Earliest time the NEXT occurrence may start (enforces min_gap and window spread).
            advance_past: Optional[int] = None

            for i in range(task.frequency):
                target = day_start + i * interval
                if task.earliest:
                    target = max(target, _mins(task.earliest))

                # First try: respect advance_past (min-gap or window boundary).
                slot_start = None
                if advance_past is not None:
                    slot_start = self._find_slot(
                        max(target, advance_past), task.duration_minutes, busy,
                        latest_mins=_mins(task.latest) if task.latest else None,
                    )
                # Fallback: use original target, but reject any slot that would be
                # too close to an already-scheduled occurrence of the same task type.
                if slot_start is None:
                    candidate = self._find_slot(
                        target, task.duration_minutes, busy,
                        latest_mins=_mins(task.latest) if task.latest else None,
                    )
                    if candidate is not None:
                        too_close = any(
                            candidate < _mins(s.end_time) + min_gap
                            and s.task.task_type == task.task_type
                            for s in plan.scheduled
                        )
                        if not too_close:
                            slot_start = candidate

                # Post-feeding gap: push vigorous tasks past the rest window.
                if slot_start is not None:
                    for _ in range(len(plan.scheduled) + 1):
                        ok_from = self._post_feeding_ok_from(
                            slot_start, task.task_type, plan.scheduled
                        )
                        if ok_from is None:
                            break
                        slot_start = self._find_slot(
                            ok_from, task.duration_minutes, busy,
                            latest_mins=_mins(task.latest) if task.latest else None,
                        )
                        if slot_start is None:
                            break

                if slot_start is not None:
                    slot_end = slot_start + task.duration_minutes
                    dep_names = ", ".join(d.name for d in task.dependencies)
                    reason = f"Scheduled at {_to_time(slot_start).strftime('%H:%M')}."
                    if dep_names:
                        reason += f" Follows dependency: {dep_names}."
                    plan.scheduled.append(
                        ScheduledTask(task, _to_time(slot_start), _to_time(slot_end), reason)
                    )
                    busy.append((slot_start, slot_end))
                    busy.sort()
                    scheduled_count += 1
                    # For activity tasks: next occurrence must start at least min_gap later.
                    # For other tasks: advance past the current window to spread across windows.
                    if task.task_type in ACTIVITY_TASKS and min_gap > 0:
                        advance_past = slot_end + min_gap
                    else:
                        for w in windows:
                            if _mins(w.start) <= slot_start < _mins(w.end):
                                advance_past = _mins(w.end)
                                break

            missed = task.frequency - scheduled_count
            if missed > 0:
                plan.warnings.append(
                    f"'{task.name}': only {scheduled_count} of {task.frequency} occurrences "
                    f"scheduled — not enough availability windows."
                )

        plan.warnings.extend(self._check_gaps(plan.scheduled))
        return plan

    def _find_slot(
        self,
        target_mins: int,
        duration: int,
        busy: list[tuple[int, int]],
        latest_mins: Optional[int] = None,
    ) -> Optional[int]:
        """Return the earliest free start time at or after target_mins that fits in a window."""
        windows = sorted(self.owner.availability_windows, key=lambda w: _mins(w.start))
        for window in windows:
            w_start = _mins(window.start)
            w_end = _mins(window.end)
            start = max(target_mins, w_start)
            if start >= w_end:
                continue
            while start + duration <= w_end:
                end = start + duration
                if latest_mins is not None and end > latest_mins:
                    break
                conflict = next((b for b in busy if b[0] < end and b[1] > start), None)
                if conflict is None:
                    return start
                start = conflict[1]
        return None

    def _urgency_score(self, task: Task) -> float:
        """Composite urgency score — higher means schedule sooner.

        Priority is the dominant factor (weight 10 per level).
        Frequency breaks ties: a task needed 3x/day competes harder for slots
        than one needed 1x/day and should be scheduled first.
        Duration applies a small penalty so shorter tasks of equal urgency are
        preferred — they fit in more gaps and leave larger blocks free.
        """
        priority_weight  = (6 - task.priority) * 10   # 10–50; priority 1 → 50
        frequency_weight = task.frequency * 2          # more occurrences = more urgent
        duration_penalty = task.duration_minutes * 0.1 # shorter tasks fit more places
        return priority_weight + frequency_weight - duration_penalty

    def _sort_by_priority(self) -> list[Task]:
        """Return pet tasks sorted by urgency score with dependencies resolved via topological sort."""
        pet_task_ids = {id(t) for t in self.pet.tasks}
        by_priority = sorted(self.pet.tasks, key=self._urgency_score, reverse=True)

        ordered: list[Task] = []
        visited: set[int] = set()

        def visit(task: Task) -> None:
            if id(task) in visited:
                return
            visited.add(id(task))
            for dep in task.dependencies:
                if id(dep) in pet_task_ids:
                    visit(dep)
            ordered.append(task)

        for task in by_priority:
            visit(task)

        return ordered

    def _post_feeding_ok_from(
        self, slot_start: int, task_type: TaskType, scheduled: list
    ) -> Optional[int]:
        """If slot_start is within POST_FEEDING_GAP of any feeding end, return earliest OK start."""
        if task_type not in VIGOROUS_TASKS:
            return None
        for st in scheduled:
            if st.task.task_type == TaskType.FEEDING:
                feed_end = _mins(st.end_time)
                if feed_end <= slot_start < feed_end + POST_FEEDING_GAP:
                    return feed_end + POST_FEEDING_GAP
        return None

    def _fits_in_window(self, task: Task, window: AvailabilityWindow, start_time: time) -> bool:
        """Return True if task can start at start_time and finish within the window."""
        start = _mins(start_time)
        end = start + task.duration_minutes
        if start < _mins(window.start) or end > _mins(window.end):
            return False
        if task.latest and end > _mins(task.latest):
            return False
        return True

    def _check_gaps(self, scheduled: list[ScheduledTask]) -> list[str]:
        """Return warnings for task types whose consecutive occurrences are too far apart."""
        warnings: list[str] = []

        by_type: dict[TaskType, list[ScheduledTask]] = {}
        for st in scheduled:
            by_type.setdefault(st.task.task_type, []).append(st)

        for task_type, occurrences in by_type.items():
            occurrences.sort(key=lambda st: _mins(st.start_time))
            threshold = _GAP_THRESHOLDS.get(task_type)
            for i in range(len(occurrences) - 1):
                gap = _mins(occurrences[i + 1].start_time) - _mins(occurrences[i].end_time)
                if threshold is not None and gap > threshold:
                    warnings.append(
                        f"'{task_type.value.capitalize()}' gap of {gap // 60}h {gap % 60}m "
                        f"between occurrences {i + 1} and {i + 2} — consider spacing them more evenly."
                    )
                if gap == 0 and len(occurrences) > 1:
                    warnings.append(
                        f"'{task_type.value.capitalize()}' occurrences {i + 1} and {i + 2} are "
                        f"back-to-back — add a midday availability window to spread them out."
                    )

        return warnings
