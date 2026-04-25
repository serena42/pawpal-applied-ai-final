"""
PawPal+ Agentic Demo — 3 Scenarios
====================================
Demonstrates the conflict-detection → AI repair loop across three scenarios
of increasing complexity.

Run:
    python demo_agent.py
"""

from datetime import time

from models import Owner, Pet, Task, TaskType, DailyPlan, ScheduledTask, _to_time, _mins
from conflict_detector import detect_conflicts
from agent import ScheduleAgent


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DIVIDER  = "=" * 62
SUBDIV   = "-" * 62


def format_schedule(plans: dict) -> str:
    rows = sorted(
        [(pet, st) for pet, plan in plans.items() for st in plan.scheduled],
        key=lambda x: _mins(x[1].start_time),
    )
    if not rows:
        return "  (no tasks scheduled)"
    return "\n".join(
        f"  {st.start_time.strftime('%H:%M')}–{st.end_time.strftime('%H:%M')}: "
        f"{st.task.name} ({pet})"
        for pet, st in rows
    )


def run_scenario(title: str, description: str, plans: dict, owner: Owner) -> None:
    print(DIVIDER)
    print(f"  {title}")
    print(SUBDIV)
    print(f"  {description}")
    print(DIVIDER)

    print("\nInitial schedule:")
    print(format_schedule(plans))

    conflicts = detect_conflicts(plans, owner, owner.pets)

    if not conflicts:
        print("\nNo conflicts detected — schedule is already valid.\n")
        return

    print(f"\nConflicts detected ({len(conflicts)}):")
    for c in conflicts:
        print(f"  [{c.conflict_type.upper()}] {c.reason}")

    print("\nAgent repair loop:")
    agent  = ScheduleAgent()
    plans, history = agent.fix_schedule(plans, owner, owner.pets)

    for step in history:
        print(f"  Iteration {step['iteration'] + 1}: "
              f"{step['conflicts_found']} conflict(s) found")
        print(f"    AI suggests: {step['claude_suggestion']}")

    remaining = detect_conflicts(plans, owner, owner.pets)
    print(f"\nFinal schedule:")
    print(format_schedule(plans))

    if remaining:
        print(f"\n  WARNING: {len(remaining)} conflict(s) unresolved after "
              f"{len(history)} iteration(s).")
        for c in remaining:
            print(f"     [{c.conflict_type.upper()}] {c.reason}")
    else:
        print(f"\n  All conflicts resolved in {len(history)} iteration(s).")

    print()


# ---------------------------------------------------------------------------
# Scenario 1 — Simple single-pet overlap
# ---------------------------------------------------------------------------

def scenario_1() -> tuple:
    """
    Alex has one dog, Buddy. Walk runs 08:00–08:30 but Feeding
    was accidentally scheduled at 08:20, overlapping the walk by 10 minutes.
    One conflict, resolved in one iteration.
    """
    owner = Owner(name="Alex")
    owner.add_window(time(8, 0), time(18, 0))
    buddy = Pet(name="Buddy", pet_type="dog")
    owner.add_pet(buddy)

    walk    = Task(TaskType.WALK,    name="Morning Walk", duration_minutes=30, frequency=1)
    feeding = Task(TaskType.FEEDING, name="Feeding",      duration_minutes=15, frequency=1)

    plan = DailyPlan()
    plan.scheduled.append(ScheduledTask(walk,    _to_time(480), _to_time(510), "scheduled"))
    # Overlap: Feeding starts at 08:20, walk ends at 08:30.
    plan.scheduled.append(ScheduledTask(feeding, _to_time(500), _to_time(515), "scheduled"))

    return {"Buddy": plan}, owner


# ---------------------------------------------------------------------------
# Scenario 2 — Multi-pet, multi-conflict cascade
# ---------------------------------------------------------------------------

def scenario_2() -> tuple:
    """
    Jordan has Mochi (dog) and Luna (cat). Two separate overlaps exist —
    one for each pet — and the agent resolves them one per iteration.
    """
    owner = Owner(name="Jordan")
    owner.add_window(time(8, 0), time(18, 0))
    mochi = Pet(name="Mochi", pet_type="dog")
    luna  = Pet(name="Luna",  pet_type="cat")
    owner.add_pet(mochi)
    owner.add_pet(luna)

    walk    = Task(TaskType.WALK,     name="Morning Walk", duration_minutes=30, frequency=1)
    feeding = Task(TaskType.FEEDING,  name="Feeding",      duration_minutes=15, frequency=1)
    feeding2 = Task(TaskType.FEEDING,  name="Feeding",     duration_minutes=15, frequency=1)
    litter  = Task(TaskType.LITTER_BOX, name="Litter box", duration_minutes=10, frequency=1)

    mochi_plan = DailyPlan()
    mochi_plan.scheduled.append(ScheduledTask(walk,    _to_time(480), _to_time(510), "scheduled"))
    # Overlap: Feeding starts 10 min before walk ends.
    mochi_plan.scheduled.append(ScheduledTask(feeding, _to_time(500), _to_time(515), "scheduled"))

    luna_plan = DailyPlan()
    luna_plan.scheduled.append(ScheduledTask(feeding2, _to_time(600), _to_time(615), "scheduled"))
    # Overlap: Litter box starts 5 min before feeding ends.
    luna_plan.scheduled.append(ScheduledTask(litter,  _to_time(610), _to_time(620), "scheduled"))

    return {"Mochi": mochi_plan, "Luna": luna_plan}, owner


# ---------------------------------------------------------------------------
# Scenario 3 — Dependency violation (medication must follow feeding)
# ---------------------------------------------------------------------------

def scenario_3() -> tuple:
    """
    Sam's dog Max needs medication after eating — Medication depends on Feeding.
    The schedule has Medication at 08:00 but Feeding isn't until 09:00,
    violating the dependency. The correct fix is to move Medication to after
    Feeding ends (09:15), not to move Feeding earlier.
    """
    owner = Owner(name="Sam")
    owner.add_window(time(8, 0), time(18, 0))
    max_pet = Pet(name="Max", pet_type="dog")
    owner.add_pet(max_pet)

    feeding    = Task(TaskType.FEEDING,    name="Feeding",    duration_minutes=15, frequency=1)
    # Medication declares Feeding as a dependency (must come after feeding).
    medication = Task(TaskType.MEDICATION, name="Medication", duration_minutes=5,
                      frequency=1, dependencies=[feeding])

    plan = DailyPlan()
    # Violation: Medication at 08:00, Feeding not until 09:00.
    # Medication must be AFTER Feeding ends (09:15).
    plan.scheduled.append(ScheduledTask(medication, _to_time(480), _to_time(485), "scheduled"))
    plan.scheduled.append(ScheduledTask(feeding,    _to_time(540), _to_time(555), "scheduled"))

    return {"Max": plan}, owner


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(DIVIDER)
    print("  PAWPAL+ — AGENTIC CONFLICT DETECTION & REPAIR DEMO")
    print(DIVIDER)
    print()

    plans, owner = scenario_1()
    run_scenario(
        "SCENARIO 1 — Simple single-pet overlap",
        "Alex's dog Buddy has a walk/feeding time clash. One conflict, one fix.",
        plans, owner,
    )

    plans, owner = scenario_2()
    run_scenario(
        "SCENARIO 2 — Multi-pet cascade",
        "Jordan's dog and cat each have an overlap. Agent resolves them in sequence.",
        plans, owner,
    )

    plans, owner = scenario_3()
    run_scenario(
        "SCENARIO 3 — Dependency violation (edge case)",
        "Sam's dog Max needs medication AFTER eating. Schedule has them backwards.",
        plans, owner,
    )


if __name__ == "__main__":
    main()
