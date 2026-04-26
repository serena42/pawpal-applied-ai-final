"""
PawPal+ Demo — Scheduling Pipeline & Coverage Suggestions
==========================================================
Shows the full pipeline across four realistic scenarios.

The deterministic scheduler places tasks within the owner's availability
windows. When it can't fit everything — too many occurrences, windows too
narrow, or recurring tasks ending up too far apart — the conflict detector
flags each issue and the coverage-window engine computes the minimum
external-help slots that would close each gap.

Scenarios
---------
1. Commuter's dog       — 2 narrow windows; 3rd walk dropped; multiple
                          coverage suggestions (dog walker + pet sitter)
2. Tight-gap feeding    — both feedings scheduled but 12 h apart, 4 h over
                          the 8-hour safe limit; pet sitter midday suggested
3. Two-pet household    — shared busy slots cause cascading gaps for dog and
                          cat; separate coverage windows computed for each
4. Puppy's high demands — Luna needs 4 walks + 3 feedings; only 3 walks and
                          2 feedings fit in two narrow windows

Run:
    python demo_agent.py
"""

import os
from datetime import time

from models import Owner, Pet, Task, TaskType, Scheduler, _mins
from conflict_detector import detect_conflicts, suggest_coverage_windows


def clear():
    os.system("cls" if os.name == "nt" else "clear")


DIVIDER = "=" * 62
SUBDIV  = "-" * 62


def format_schedule(plans: dict) -> str:
    rows = sorted(
        [(pet, st) for pet, plan in plans.items() for st in plan.scheduled],
        key=lambda x: _mins(x[1].start_time),
    )
    lines = []
    if not rows:
        lines.append("  (no tasks scheduled)")
    else:
        for pet, st in rows:
            lines.append(
                f"  {st.start_time.strftime('%H:%M')}-{st.end_time.strftime('%H:%M')}: "
                f"{st.task.name} ({pet})"
            )
    for _pet_name, plan in plans.items():
        for w in plan.warnings:
            lines.append(f"  [WARN] {w}")
    return "\n".join(lines)


def run_scenario(title: str, description: str, owner: Owner) -> None:
    """Run the real scheduler, detect conflicts, and suggest coverage windows (no API key needed)."""
    print(DIVIDER)
    print(f"  {title}")
    print(SUBDIV)
    print(f"  {description}")
    print(DIVIDER)

    scheduler = Scheduler(owner, owner.pets[0])
    plans = scheduler.generate_all_plans()

    print("\nSchedule (within owner's available hours):")
    print(format_schedule(plans))

    conflicts = detect_conflicts(plans, owner, owner.pets)
    if conflicts:
        print(f"\nConflicts / gaps detected ({len(conflicts)}):")
        for c in conflicts:
            print(f"  [{c.conflict_type.upper()}] {c.reason}")
    else:
        print("\n  No conflicts detected.")

    coverage = suggest_coverage_windows(plans, owner, owner.pets)
    if coverage:
        print(f"\nCoverage window suggestions ({len(coverage)}):")
        for cw in coverage:
            svc = cw.service_type.replace("_", " ").title()
            print(f"  -> {svc} for {cw.pet_name}: {cw.start}-{cw.end}")
            print(f"     {cw.reason}")
    else:
        print("\n  No additional coverage needed.")

    print()


def run_ai_scenario(title: str, description: str, owner: Owner) -> None:
    """
    Same pipeline as run_scenario, but also calls Gemini to synthesize the
    coverage windows into a plain-language recommendation. Requires GEMINI_API_KEY.
    """
    print(DIVIDER)
    print(f"  {title}")
    print(SUBDIV)
    print(f"  {description}")
    print(DIVIDER)

    scheduler = Scheduler(owner, owner.pets[0])
    plans = scheduler.generate_all_plans()

    print("\nSchedule (within owner's available hours):")
    print(format_schedule(plans))

    conflicts = detect_conflicts(plans, owner, owner.pets)
    coverage = suggest_coverage_windows(plans, owner, owner.pets)

    if conflicts:
        print(f"\nConflicts / gaps detected ({len(conflicts)}):")
        for c in conflicts:
            print(f"  [{c.conflict_type.upper()}] {c.reason}")
    else:
        print("\n  No conflicts detected.")

    if coverage:
        print(f"\nCoverage windows computed ({len(coverage)}):")
        for cw in coverage:
            svc = cw.service_type.replace("_", " ").title()
            print(f"  -> {svc} for {cw.pet_name}: {cw.start}-{cw.end}")
            print(f"     {cw.reason}")

    print()
    print("  Asking Gemini to synthesize a recommendation...")
    print(SUBDIV)
    try:
        from agent import ScheduleAgent
        summary = ScheduleAgent().summarize_coverage(
            plans, conflicts, coverage, owner, owner.pets
        )
        print()
        print(summary)
    except KeyError:
        print(
            "\n  [GEMINI_API_KEY not set]"
            "\n  Windows: set GEMINI_API_KEY=your-key"
            "\n  Mac/Linux: export GEMINI_API_KEY=your-key"
        )
    except Exception as e:
        print(f"\n  [Gemini error: {e}]")

    print()


# ---------------------------------------------------------------------------
# Scenario 1 — Commuter's dog
# ---------------------------------------------------------------------------

def scenario_1() -> Owner:
    """
    Morgan works 09:00-18:00 and is home only 07:00-09:00 and 18:00-19:30.
    Rex needs 3 walks/day, but the adult min-gap rule (3 h between sessions)
    means only 2 walks fit. The scheduler drops the 3rd walk and the two
    feedings end up 10+ hours apart, exceeding the 8-hour safe limit.
    Coverage: midday dog walker to cover the missing walk + pet sitter to
    add a midday feeding within the gap.
    """
    owner = Owner(name="Morgan")
    owner.add_window(time(7, 0), time(9, 0))
    owner.add_window(time(18, 0), time(19, 30))
    rex = Pet(name="Rex", pet_type="dog", age_group="adult", energy_level="high")
    rex.add_task(Task(TaskType.WALK,    duration_minutes=30, frequency=3))
    rex.add_task(Task(TaskType.FEEDING, duration_minutes=15, frequency=2))
    owner.add_pet(rex)
    return owner


# ---------------------------------------------------------------------------
# Scenario 2 — Tight-gap feeding
# ---------------------------------------------------------------------------

def scenario_2() -> Owner:
    """
    Jordan is only available 07:00-08:00 and 20:00-21:00.
    Both of Buddy's daily feedings are scheduled (one per window) but they
    sit 12+ hours apart — 4 hours beyond the 8-hour recommended maximum.
    No schedule adjustment can close this gap without a third window.
    Coverage: pet sitter midday (around 13:15-14:00) to add a midday feeding.
    """
    owner = Owner(name="Jordan")
    owner.add_window(time(7, 0), time(8, 0))
    owner.add_window(time(20, 0), time(21, 0))
    buddy = Pet(name="Buddy", pet_type="dog")
    buddy.add_task(Task(TaskType.FEEDING, duration_minutes=15, frequency=2))
    owner.add_pet(buddy)
    return owner


# ---------------------------------------------------------------------------
# Scenario 3 — Two-pet household
# ---------------------------------------------------------------------------

def scenario_3() -> Owner:
    """
    Taylor has 07:00-09:00 and 17:30-19:00. Buddy (dog) and Miso (cat)
    share those time slots. Busy slots from Buddy's tasks leave Miso's tasks
    crowded into the tail end of each window. All tasks are scheduled, but
    every recurring task — Buddy's feedings, Miso's feedings, Miso's litter
    box — ends up with a 10-hour gap between occurrences. Buddy's 3rd walk
    is also dropped entirely.
    Coverage: separate midday slots computed for each pet and task type.
    """
    owner = Owner(name="Taylor")
    owner.add_window(time(7, 0), time(9, 0))
    owner.add_window(time(17, 30), time(19, 0))
    buddy = Pet(name="Buddy", pet_type="dog")
    buddy.add_task(Task(TaskType.WALK,    duration_minutes=30, frequency=3))
    buddy.add_task(Task(TaskType.FEEDING, duration_minutes=15, frequency=2))
    miso = Pet(name="Miso", pet_type="cat")
    miso.add_task(Task(TaskType.FEEDING,    duration_minutes=15, frequency=2))
    miso.add_task(Task(TaskType.LITTER_BOX, duration_minutes=10, frequency=2))
    owner.add_pet(buddy)
    owner.add_pet(miso)
    return owner


# ---------------------------------------------------------------------------
# Scenario 4 — Puppy's high demands
# ---------------------------------------------------------------------------

def scenario_4() -> Owner:
    """
    Riley has 07:00-09:00 and 18:00-20:00. Luna is a young puppy that needs
    4 walks/day and 3 feedings. Puppies have a shorter 60-minute min-gap
    between walk sessions, so 3 walks fit (morning, 18:00, 19:20), but the
    4th is dropped. Only 2 of 3 feedings fit — the 3rd occurrence would need
    a slot past 20:00. The feeding gap also exceeds 10 hours.
    Coverage: dog walker for the missing midday walk + pet sitter for the
    dropped feeding and gap.
    """
    owner = Owner(name="Riley")
    owner.add_window(time(7, 0), time(9, 0))
    owner.add_window(time(18, 0), time(20, 0))
    luna = Pet(name="Luna", pet_type="dog", age_group="puppy")
    luna.add_task(Task(TaskType.WALK,    duration_minutes=20, frequency=4))
    luna.add_task(Task(TaskType.FEEDING, duration_minutes=15, frequency=3))
    owner.add_pet(luna)
    return owner


# ---------------------------------------------------------------------------
# Scenario registry + interactive menu
# ---------------------------------------------------------------------------

SCENARIOS = [
    (
        "Commuter's dog -- missed walk & feeding gap",
        "Morgan: 07:00-09:00 and 18:00-19:30. Rex needs 3 walks; only 2 fit.",
        scenario_1,
        run_scenario,
    ),
    (
        "Tight-gap feeding -- feedings 12 h apart",
        "Jordan: 07:00-08:00 and 20:00-21:00. Buddy's feedings exceed the 8 h limit.",
        scenario_2,
        run_scenario,
    ),
    (
        "Two-pet household -- shared slots, cascading gaps",
        "Taylor: same narrow windows. Dog + cat compete; both end up with 10 h gaps.",
        scenario_3,
        run_scenario,
    ),
    (
        "Puppy's high demands -- multiple dropped tasks",
        "Riley: 2 windows, puppy Luna needs 4 walks + 3 feedings; 4th walk + 3rd feeding dropped.",
        scenario_4,
        run_scenario,
    ),
    (
        "AI synthesis -- Gemini explains Taylor's coverage needs  [requires GEMINI_API_KEY]",
        "Two-pet scenario; Gemini synthesizes which coverage windows can be combined into one visit.",
        scenario_3,
        run_ai_scenario,
    ),
]


def show_menu() -> None:
    clear()
    print(DIVIDER)
    print("  PAWPAL+ -- SELECT A SCENARIO")
    print(DIVIDER)
    print()
    for i, (title, description, _setup, _runner) in enumerate(SCENARIOS, 1):
        print(f"  {i}. {title}")
        print(f"     {description}")
        print()
    print("  Q. Quit")
    print(SUBDIV)


def main() -> None:
    while True:
        show_menu()
        choice = input(f"  Select (1-{len(SCENARIOS)} or Q): ").strip().lower()
        if choice == "q":
            clear()
            break
        if choice.isdigit() and 1 <= int(choice) <= len(SCENARIOS):
            idx = int(choice) - 1
            title, description, setup_fn, runner_fn = SCENARIOS[idx]
            owner = setup_fn()
            clear()
            runner_fn(f"SCENARIO {idx + 1} -- {title}", description, owner)
            input("\n  Press Enter to return to menu...")


if __name__ == "__main__":
    main()
