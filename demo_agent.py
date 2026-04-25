"""
PawPal+ Agentic Demo
====================
Demonstrates the conflict-detection → AI repair loop.

Scenario
--------
Jordan has a wide daily window (8 AM–6 PM). The initial schedule contains
two deliberate time-overlap conflicts so the agent has clear, solvable
problems to work through across 2–3 visible iterations.

Run:
    export GEMINI_API_KEY=<your-key>
    python demo_agent.py
"""

from datetime import time

from models import Owner, Pet, Task, TaskType, DailyPlan, ScheduledTask, _to_time, _mins
from conflict_detector import detect_conflicts
from agent import ScheduleAgent


# ---------------------------------------------------------------------------
# Demo scenario
# ---------------------------------------------------------------------------

def load_demo_owner() -> Owner:
    owner = Owner(name="Jordan")
    owner.add_window(time(8, 0), time(18, 0))   # wide 10-hour window
    mochi = Pet(name="Mochi", pet_type="dog")
    luna  = Pet(name="Luna",  pet_type="cat")
    owner.add_pet(mochi)
    owner.add_pet(luna)
    return owner


def build_conflicted_plans(owner) -> dict:
    """
    Build a manually crafted schedule with two deliberate overlaps:
      [Mochi] Morning Walk 08:00–08:30 overlaps Feeding 08:20–08:35
      [Luna]  Feeding 10:00–10:15 overlaps Litter box 10:10–10:20
    The agent's job is to move the later task in each pair to clear the overlap.
    """
    mochi_plan = DailyPlan()
    walk    = Task(TaskType.WALK,    name="Morning Walk", duration_minutes=30, frequency=1)
    feeding = Task(TaskType.FEEDING, name="Feeding",      duration_minutes=15, frequency=1)
    # Deliberate overlap: Feeding starts at 08:20 while Walk runs until 08:30.
    mochi_plan.scheduled.append(ScheduledTask(walk,    _to_time(480), _to_time(510), "scheduled"))
    mochi_plan.scheduled.append(ScheduledTask(feeding, _to_time(500), _to_time(515), "scheduled"))

    luna_plan = DailyPlan()
    feeding2 = Task(TaskType.FEEDING,   name="Feeding",   duration_minutes=15, frequency=1)
    litter   = Task(TaskType.LITTER_BOX, name="Litter box", duration_minutes=10, frequency=1)
    # Deliberate overlap: Litter box starts at 10:10 while Feeding runs until 10:15.
    luna_plan.scheduled.append(ScheduledTask(feeding2, _to_time(600), _to_time(615), "scheduled"))
    luna_plan.scheduled.append(ScheduledTask(litter,   _to_time(610), _to_time(620), "scheduled"))

    return {"Mochi": mochi_plan, "Luna": luna_plan}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

def main():
    DIVIDER = "=" * 62

    owner = load_demo_owner()
    plans = build_conflicted_plans(owner)

    print(DIVIDER)
    print("PAWPAL+ AGENTIC CONFLICT REPAIR DEMO")
    print(DIVIDER)
    print(f"Owner: {owner.name}")
    print("Availability: " + ", ".join(
        f"{w.start.strftime('%H:%M')}–{w.end.strftime('%H:%M')}"
        for w in owner.availability_windows
    ))
    print()

    print(DIVIDER)
    print("INITIAL SCHEDULE  (contains deliberate conflicts)")
    print(DIVIDER)
    print(format_schedule(plans))
    print()

    # Rule-based detection (no API call).
    conflicts = detect_conflicts(plans, owner, owner.pets)

    if not conflicts:
        print("No conflicts detected — nothing for the agent to fix.")
        return

    print(DIVIDER)
    print(f"CONFLICTS DETECTED  ({len(conflicts)} found)")
    print(DIVIDER)
    for c in conflicts:
        print(f"  [{c.conflict_type.upper()}] {c.reason}")
        print(f"    Suggested fix: {c.suggested_fix}")
    print()

    # Agentic repair loop (Gemini API).
    print(DIVIDER)
    print("AGENT REPAIR LOOP  (AI proposes fixes, detector validates)")
    print(DIVIDER)

    agent = ScheduleAgent()
    plans, history = agent.fix_schedule(plans, owner, owner.pets)

    if not history:
        print("  Agent exited immediately — no conflicts to fix.")
    else:
        for step in history:
            print(f"  Iteration {step['iteration'] + 1}:")
            print(f"    Conflicts found : {step['conflicts_found']}")
            print(f"    AI suggests     : {step['claude_suggestion']}")
        print()

    # Final validation.
    remaining = detect_conflicts(plans, owner, owner.pets)

    print(DIVIDER)
    print("FINAL SCHEDULE  (after agent repairs)")
    print(DIVIDER)
    print(format_schedule(plans))
    print()

    if remaining:
        print(f"  [{len(remaining)} conflict(s) remain after {len(history)} iteration(s)]")
        for c in remaining:
            print(f"  [{c.conflict_type.upper()}] {c.reason}")
    else:
        print(f"  All conflicts resolved in {len(history)} iteration(s).")


if __name__ == "__main__":
    main()
