"""
PawPal+ Agentic Demo — 6 Scenarios
====================================
Demonstrates the conflict-detection → AI repair loop and edge-case
guardrails across six scenarios of increasing complexity.

Scenarios
---------
1. Simple overlap          — walk and feeding overlap; resolved in one pass
2. Multi-pet cascade       — two pets, two separate overlaps; one fix per iteration
3. Dependency violation    — medication scheduled before its feeding dependency
4. Post-feeding gap        — vigorous activity too soon after eating (gastric torsion risk)
5. Medication-feeding gap  — medication given before food has settled (absorption rule)
6. Unresolvable gap        — midday gap the owner can't cover; system suggests a pet sitter

Run:
    python demo_agent.py
"""

from datetime import time

from models import Owner, Pet, Task, TaskType, DailyPlan, ScheduledTask, _to_time, _mins
from conflict_detector import detect_conflicts, recommend_service, suggest_coverage_windows
from agent import ScheduleAgent


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DIVIDER = "=" * 62
SUBDIV  = "-" * 62


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
    """Run the full detect → AI repair → verify loop and print results."""
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
    agent = ScheduleAgent()
    plans, history, coverage = agent.fix_schedule(plans, owner, owner.pets)

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
            print(f"    [{c.conflict_type.upper()}] {c.reason}")
        rec = recommend_service(remaining)
        if rec:
            print(f"\n  Recommendation: {rec.replace('**', '')}")
    else:
        print(f"\n  All conflicts resolved in {len(history)} iteration(s).")

    if coverage:
        print(f"\n  Coverage window suggestions ({len(coverage)}):")
        for cw in coverage:
            svc = cw.service_type.replace("_", " ").title()
            print(f"    ->{svc} for {cw.pet_name}: {cw.start}–{cw.end}")
            print(f"      {cw.reason}")

    print()


def run_coverage_scenario(title: str, description: str, plans: dict, owner: Owner) -> None:
    """
    Runner for scenarios where the conflict cannot be fixed within the owner's
    hours. Skips the AI repair loop and goes straight to coverage suggestions.
    """
    print(DIVIDER)
    print(f"  {title}")
    print(SUBDIV)
    print(f"  {description}")
    print(DIVIDER)

    print("\nSchedule:")
    print(format_schedule(plans))

    conflicts = detect_conflicts(plans, owner, owner.pets)
    print(f"\nConflicts detected ({len(conflicts)}):")
    for c in conflicts:
        print(f"  [{c.conflict_type.upper()}] {c.reason}")

    print("\n  These conflicts cannot be resolved within the owner's available hours.")
    print("  Skipping AI repair — computing coverage window suggestions instead.")

    coverage = suggest_coverage_windows(plans, owner, owner.pets)
    if coverage:
        print(f"\nCoverage window suggestions ({len(coverage)}):")
        for cw in coverage:
            svc = cw.service_type.replace("_", " ").title()
            print(f"  -> {svc} for {cw.pet_name}: {cw.start}-{cw.end}")
            print(f"    {cw.reason}")
    else:
        print("\n  No coverage suggestions generated.")

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

    walk     = Task(TaskType.WALK,      name="Morning Walk", duration_minutes=30, frequency=1)
    feeding  = Task(TaskType.FEEDING,   name="Feeding",      duration_minutes=15, frequency=1)
    feeding2 = Task(TaskType.FEEDING,   name="Feeding",      duration_minutes=15, frequency=1)
    litter   = Task(TaskType.LITTER_BOX, name="Litter box",  duration_minutes=10, frequency=1)

    mochi_plan = DailyPlan()
    mochi_plan.scheduled.append(ScheduledTask(walk,    _to_time(480), _to_time(510), "scheduled"))
    mochi_plan.scheduled.append(ScheduledTask(feeding, _to_time(500), _to_time(515), "scheduled"))

    luna_plan = DailyPlan()
    luna_plan.scheduled.append(ScheduledTask(feeding2, _to_time(600), _to_time(615), "scheduled"))
    luna_plan.scheduled.append(ScheduledTask(litter,   _to_time(610), _to_time(620), "scheduled"))

    return {"Mochi": mochi_plan, "Luna": luna_plan}, owner


# ---------------------------------------------------------------------------
# Scenario 3 — Dependency violation (medication must follow feeding)
# ---------------------------------------------------------------------------

def scenario_3() -> tuple:
    """
    Sam's dog Max needs medication after eating — Medication depends on Feeding.
    The schedule has Medication at 08:00 but Feeding isn't until 09:00.
    The correct fix is to move Medication to after Feeding ends, not to move
    Feeding earlier — the prompt explicitly constrains this.
    """
    owner = Owner(name="Sam")
    owner.add_window(time(8, 0), time(18, 0))
    max_pet = Pet(name="Max", pet_type="dog")
    owner.add_pet(max_pet)

    feeding    = Task(TaskType.FEEDING,    name="Feeding",    duration_minutes=15, frequency=1)
    medication = Task(TaskType.MEDICATION, name="Medication", duration_minutes=5,
                      frequency=1, dependencies=[feeding])

    plan = DailyPlan()
    plan.scheduled.append(ScheduledTask(medication, _to_time(480), _to_time(485), "scheduled"))
    plan.scheduled.append(ScheduledTask(feeding,    _to_time(540), _to_time(555), "scheduled"))

    return {"Max": plan}, owner


# ---------------------------------------------------------------------------
# Scenario 4 — Post-feeding gap (gastric torsion / bloat risk)
# ---------------------------------------------------------------------------

def scenario_4() -> tuple:
    """
    Riley's dog Nova is scheduled for a walk only 5 minutes after feeding ends.
    Vigorous activity within 30 minutes of eating can cause gastric dilatation-
    volvulus (bloat) in dogs — a life-threatening condition.
    The agent moves the walk to at least 30 minutes after feeding.
    """
    owner = Owner(name="Riley")
    owner.add_window(time(8, 0), time(18, 0))
    nova = Pet(name="Nova", pet_type="dog")
    owner.add_pet(nova)

    feeding = Task(TaskType.FEEDING, name="Feeding",      duration_minutes=15, frequency=1)
    walk    = Task(TaskType.WALK,    name="Morning Walk", duration_minutes=30, frequency=1)

    plan = DailyPlan()
    plan.scheduled.append(ScheduledTask(feeding, _to_time(480), _to_time(495), "scheduled"))
    # Walk starts only 5 min after feeding ends — inside the 30-min post-feeding rest window.
    plan.scheduled.append(ScheduledTask(walk, _to_time(500), _to_time(530), "scheduled"))

    return {"Nova": plan}, owner


# ---------------------------------------------------------------------------
# Scenario 5 — Medication-feeding gap (absorption rule)
# ---------------------------------------------------------------------------

def scenario_5() -> tuple:
    """
    Sam's cat Miso is on medication that must be given with food, but needs
    at least 10 minutes for the food to settle before the medication is absorbed
    properly. The schedule has Medication starting 1 minute after Feeding ends.
    The agent moves Medication to at least 10 minutes after feeding.
    """
    owner = Owner(name="Sam")
    owner.add_window(time(8, 0), time(18, 0))
    miso = Pet(name="Miso", pet_type="cat")
    owner.add_pet(miso)

    feeding    = Task(TaskType.FEEDING,    name="Feeding",    duration_minutes=15, frequency=1)
    medication = Task(TaskType.MEDICATION, name="Medication", duration_minutes=5,
                      frequency=1, dependencies=[feeding])

    plan = DailyPlan()
    plan.scheduled.append(ScheduledTask(feeding,    _to_time(540), _to_time(555), "scheduled"))
    # Medication starts 1 min after feeding ends — needs at least 10 min gap.
    plan.scheduled.append(ScheduledTask(medication, _to_time(556), _to_time(561), "scheduled"))

    return {"Miso": plan}, owner


# ---------------------------------------------------------------------------
# Scenario 6 — Unresolvable gap: coverage window suggestion
# ---------------------------------------------------------------------------

def scenario_6() -> tuple:
    """
    Jordan is only available 07:00–09:00 and 18:00–20:00.
    Buddy needs two feedings a day, but the 11-hour midday gap between
    them exceeds the 8-hour recommended maximum. No slot exists within
    Jordan's hours to close this gap.

    Rather than silently leaving the conflict, PawPal+ computes a specific
    time window where a pet sitter could handle the midday feeding.
    """
    owner = Owner(name="Jordan")
    owner.add_window(time(7, 0), time(9, 0))
    owner.add_window(time(18, 0), time(20, 0))
    buddy = Pet(name="Buddy", pet_type="dog")
    owner.add_pet(buddy)

    feeding1 = Task(TaskType.FEEDING, name="Morning Feeding", duration_minutes=15, frequency=1)
    feeding2 = Task(TaskType.FEEDING, name="Evening Feeding", duration_minutes=15, frequency=1)

    plan = DailyPlan()
    plan.scheduled.append(ScheduledTask(feeding1, _to_time(7 * 60 + 15), _to_time(7 * 60 + 30),  "scheduled"))
    plan.scheduled.append(ScheduledTask(feeding2, _to_time(18 * 60 + 30), _to_time(18 * 60 + 45), "scheduled"))

    return {"Buddy": plan}, owner


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
        "SCENARIO 1 — Simple overlap",
        "Alex's dog Buddy: walk and feeding overlap by 10 minutes. One fix.",
        plans, owner,
    )

    plans, owner = scenario_2()
    run_scenario(
        "SCENARIO 2 — Multi-pet cascade",
        "Jordan's dog and cat each have a separate overlap. One fix per iteration.",
        plans, owner,
    )

    plans, owner = scenario_3()
    run_scenario(
        "SCENARIO 3 — Dependency violation",
        "Sam's dog Max: medication scheduled before its feeding dependency.",
        plans, owner,
    )

    plans, owner = scenario_4()
    run_scenario(
        "SCENARIO 4 — Post-feeding gap (gastric torsion risk)",
        "Riley's dog Nova: walk scheduled 5 min after feeding. Must wait 30 min.",
        plans, owner,
    )

    plans, owner = scenario_5()
    run_scenario(
        "SCENARIO 5 — Medication-feeding gap (absorption rule)",
        "Sam's cat Miso: medication given 1 min after feeding. Must wait 10 min.",
        plans, owner,
    )

    plans, owner = scenario_6()
    run_coverage_scenario(
        "SCENARIO 6 — Unresolvable gap: coverage window suggestion",
        "Jordan's dog Buddy: 11-hour feeding gap that no schedule change can fix.",
        plans, owner,
    )


if __name__ == "__main__":
    main()
