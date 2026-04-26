"""
PawPal+ Evaluation Script
=========================
Tests the scheduling pipeline and coverage-window engine on 6 predefined
scenarios. No API key required — evaluates the rule-based components only.

Run:
    python eval_coverage.py
"""

from datetime import time
from models import Owner, Pet, Task, TaskType, Scheduler
from conflict_detector import detect_conflicts, suggest_coverage_windows

DIVIDER = "=" * 60
results: list[bool] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    suffix = f"  (got: {detail})" if detail and not condition else ""
    print(f"  [{status}] {label}{suffix}")
    results.append(condition)
    return condition


def _make_owner(name, windows, pets_spec):
    """
    windows:   list of (start_h, start_m, end_h, end_m)
    pets_spec: list of (name, pet_type, age_group, [(TaskType, duration, frequency), ...])
    """
    owner = Owner(name=name)
    for sh, sm, eh, em in windows:
        owner.add_window(time(sh, sm), time(eh, em))
    for pet_name, pet_type, age_group, task_specs in pets_spec:
        pet = Pet(name=pet_name, pet_type=pet_type, age_group=age_group)
        for tt, dur, freq in task_specs:
            pet.add_task(Task(tt, duration_minutes=dur, frequency=freq))
        owner.add_pet(pet)
    return owner


def _run(owner):
    plans    = Scheduler(owner, owner.pets[0]).generate_all_plans()
    conflicts = detect_conflicts(plans, owner, owner.pets)
    coverage  = suggest_coverage_windows(plans, owner, owner.pets)
    return plans, conflicts, coverage


# ---------------------------------------------------------------------------
# Case 1 — Commuter's dog: narrow windows, dropped walk + feeding gap
# ---------------------------------------------------------------------------
print(DIVIDER)
print("  Case 1: Commuter's dog (2 windows, Rex needs 3 walks)")
print(DIVIDER)
owner = _make_owner("Morgan", [(7, 0, 9, 0), (18, 0, 19, 30)], [
    ("Rex", "dog", "adult", [
        (TaskType.WALK,    30, 3),
        (TaskType.FEEDING, 15, 2),
    ]),
])
plans, conflicts, coverage = _run(owner)

check("feeding gap conflict detected",
      any(c.conflict_type == "gap" and "Rex" in c.reason for c in conflicts))
check("dog_walker coverage suggested",
      any(cw.service_type == "dog_walker" for cw in coverage))
check("pet_sitter coverage suggested",
      any(cw.service_type == "pet_sitter" for cw in coverage))
check("dropped walk coverage is midday (11:00-15:00)",
      any(cw.service_type == "dog_walker" and "11:00" <= cw.start <= "15:00"
          for cw in coverage),
      str([cw.start for cw in coverage if cw.service_type == "dog_walker"]))
print()

# ---------------------------------------------------------------------------
# Case 2 — Control: wide window, everything fits, no coverage needed
# ---------------------------------------------------------------------------
print(DIVIDER)
print("  Case 2: Control (07:00-20:00, Scout needs 2 walks + 2 feedings)")
print(DIVIDER)
owner = _make_owner("Sam", [(7, 0, 20, 0)], [
    ("Scout", "dog", "adult", [
        (TaskType.WALK,    30, 2),
        (TaskType.FEEDING, 15, 2),
    ]),
])
plans, conflicts, coverage = _run(owner)

check("all tasks scheduled (no warnings)",
      all(not plan.warnings for plan in plans.values()),
      str([w for p in plans.values() for w in p.warnings]))
check("no conflicts", len(conflicts) == 0,
      str([c.conflict_type for c in conflicts]))
check("no coverage suggestions needed", len(coverage) == 0,
      str([(cw.service_type, cw.start) for cw in coverage]))
print()

# ---------------------------------------------------------------------------
# Case 3 — Tight feeding gap: feedings scheduled but 12 h apart
# ---------------------------------------------------------------------------
print(DIVIDER)
print("  Case 3: Tight feeding gap (Jordan, 07:00-08:00 and 20:00-21:00)")
print(DIVIDER)
owner = _make_owner("Jordan", [(7, 0, 8, 0), (20, 0, 21, 0)], [
    ("Buddy", "dog", "adult", [(TaskType.FEEDING, 15, 2)]),
])
_, conflicts, coverage = _run(owner)

check("gap conflict detected",
      any(c.conflict_type == "gap" for c in conflicts))
check("pet_sitter suggested",
      any(cw.service_type == "pet_sitter" for cw in coverage))
check("suggested slot is midday (12:00-15:00)",
      any("12:00" <= cw.start <= "15:00" for cw in coverage),
      str([cw.start for cw in coverage]))
print()

# ---------------------------------------------------------------------------
# Case 4 — Puppy's demands: dropped walk AND feeding both get coverage
# ---------------------------------------------------------------------------
print(DIVIDER)
print("  Case 4: Puppy (Riley, Luna needs 4 walks + 3 feedings)")
print(DIVIDER)
owner = _make_owner("Riley", [(7, 0, 9, 0), (18, 0, 20, 0)], [
    ("Luna", "dog", "puppy", [
        (TaskType.WALK,    20, 4),
        (TaskType.FEEDING, 15, 3),
    ]),
])
plans, conflicts, coverage = _run(owner)

walk_warn = [w for p in plans.values() for w in p.warnings if "Walk" in w]
feed_warn = [w for p in plans.values() for w in p.warnings if "Feeding" in w]
check("walk occurrence dropped by scheduler",   bool(walk_warn), str(walk_warn))
check("feeding occurrence dropped by scheduler", bool(feed_warn), str(feed_warn))
check("dog_walker coverage for dropped walk",
      any(cw.service_type == "dog_walker" for cw in coverage))
check("pet_sitter coverage names the dropped feeding",
      any(cw.service_type == "pet_sitter" and "Feeding" in " ".join(cw.tasks)
          for cw in coverage),
      str([(cw.service_type, cw.tasks) for cw in coverage]))
print()

# ---------------------------------------------------------------------------
# Case 5 — Service-type routing: walk→dog_walker, feeding→pet_sitter
# ---------------------------------------------------------------------------
print(DIVIDER)
print("  Case 5: Service-type routing (walk -> dog_walker, feeding -> pet_sitter)")
print(DIVIDER)
owner = _make_owner("Alex", [(7, 0, 9, 0), (18, 0, 19, 0)], [
    ("Max", "dog", "adult", [
        (TaskType.WALK,    30, 3),
        (TaskType.FEEDING, 15, 2),
    ]),
])
_, _, coverage = _run(owner)

walk_cvg = [cw for cw in coverage if "Walk" in " ".join(cw.tasks)]
feed_cvg = [cw for cw in coverage if "Feeding" in " ".join(cw.tasks)]
check("dropped walk -> dog_walker",
      all(cw.service_type == "dog_walker" for cw in walk_cvg),
      str([cw.service_type for cw in walk_cvg]))
check("dropped/gap feeding -> pet_sitter",
      all(cw.service_type == "pet_sitter" for cw in feed_cvg),
      str([cw.service_type for cw in feed_cvg]))
print()

# ---------------------------------------------------------------------------
# Case 6 — Multi-pet: each pet gets independent coverage suggestions
# ---------------------------------------------------------------------------
print(DIVIDER)
print("  Case 6: Multi-pet (Taylor, dog + cat, shared busy slots)")
print(DIVIDER)
owner = _make_owner("Taylor", [(7, 0, 9, 0), (17, 30, 19, 0)], [
    ("Buddy", "dog", "adult", [
        (TaskType.WALK,    30, 3),
        (TaskType.FEEDING, 15, 2),
    ]),
    ("Miso", "cat", "adult", [
        (TaskType.FEEDING,    15, 2),
        (TaskType.LITTER_BOX, 10, 2),
    ]),
])
_, conflicts, coverage = _run(owner)

pet_names = {cw.pet_name for cw in coverage}
check("Buddy receives coverage suggestion", "Buddy" in pet_names)
check("Miso receives coverage suggestion",  "Miso"  in pet_names)
check("3+ gap conflicts detected (Buddy feeding, Miso feeding, Miso litter)",
      len(conflicts) >= 3, f"{len(conflicts)} found")
print()

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
passed = sum(results)
total  = len(results)
print(DIVIDER)
print(f"  {passed}/{total} checks passed"
      + ("  -- ALL PASS" if passed == total else f"  -- {total - passed} FAILED"))
print(DIVIDER)
