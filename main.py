"""
PawPal+ demo script.

Creates one Owner with two Pets, shows each pet's tasks sorted by priority,
then runs the Scheduler across both pets with a shared time pool so no two
tasks ever overlap.  Demonstrates JSON persistence by saving the owner
configuration and reloading it from disk.
"""

import sys
from datetime import time
from tabulate import tabulate
from models import Task, TaskType, Owner, Pet, Scheduler, TASK_EMOJI, PET_EMOJI
from persistence import save, load, owner_to_dict, dict_to_owner

# Ensure the terminal handles UTF-8 so emojis render correctly.
sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Owner setup
# ---------------------------------------------------------------------------

jordan = Owner("Jordan")
jordan.add_window(time(7, 0), time(9, 0))    # morning:  7am - 9am
jordan.add_window(time(12, 0), time(13, 0))  # lunch:   12pm - 1pm
jordan.add_window(time(17, 0), time(20, 0))  # evening:  5pm - 8pm

# ---------------------------------------------------------------------------
# Pet 1: Mochi the dog
# ---------------------------------------------------------------------------

mochi = Pet("Mochi", "dog")
feeding  = Task(TaskType.FEEDING, frequency=2)
walk     = Task(TaskType.WALK, frequency=3)
med      = Task(TaskType.MEDICATION, dependencies=[feeding])
fetch    = Task(TaskType.FETCH)
training = Task(TaskType.TRAINING)

mochi.add_task(feeding)
mochi.add_task(walk)
mochi.add_task(med)
mochi.add_task(fetch)
mochi.add_task(training)

# ---------------------------------------------------------------------------
# Pet 2: Luna the cat
# ---------------------------------------------------------------------------

luna = Pet("Luna", "cat")
cat_feeding = Task(TaskType.FEEDING, frequency=2)
litter      = Task(TaskType.LITTER_BOX, frequency=2)
laser       = Task(TaskType.LASER_POINTER)
playtime    = Task(TaskType.PLAYTIME)
teeth       = Task(TaskType.TEETH_BRUSHING, priority=3)

luna.add_task(cat_feeding)
luna.add_task(litter)
luna.add_task(laser)
luna.add_task(playtime)
luna.add_task(teeth)

# ---------------------------------------------------------------------------
# Register pets with owner
# ---------------------------------------------------------------------------

jordan.add_pet(mochi)
jordan.add_pet(luna)

print(f"\n👤  Owner: {jordan.name}")
print("🕐  Availability: 7–9 am  |  12–1 pm  |  5–8 pm\n")

# ---------------------------------------------------------------------------
# Show each pet's tasks sorted by urgency (demonstrates list_tasks())
# ---------------------------------------------------------------------------

for pet in jordan.pets:
    icon = PET_EMOJI.get(pet.pet_type, "🐾")
    print(f"{icon}  {pet.name}'s tasks (by urgency):")
    rows = [
        [
            f"  {'★' * task.priority}{'☆' * (3 - min(task.priority, 3))}",
            f"{TASK_EMOJI.get(task.task_type, '')} {task.name}",
            f"{task.frequency}×" if task.frequency > 1 else "1×",
            f"{task.duration_minutes} min",
        ]
        for task in pet.list_tasks()
    ]
    print(tabulate(rows, headers=["Priority", "Task", "Freq", "Duration"],
                   tablefmt="simple"))
    print()

# ---------------------------------------------------------------------------
# Generate unified schedule across both pets
# ---------------------------------------------------------------------------

scheduler = Scheduler(jordan, jordan.pets[0])
all_plans = scheduler.generate_all_plans()

# Warnings
any_warnings = False
for pet_name, plan in all_plans.items():
    for w in plan.warnings:
        print(f"  ⚠️  {pet_name}: {w}")
        any_warnings = True
if any_warnings:
    print()

# Unified time-ordered schedule
combined = [
    (entry, pet_name)
    for pet_name, plan in all_plans.items()
    for entry in plan.scheduled
]
combined.sort(key=lambda x: x[0].start_time)

rows = [
    [
        f"{e.start_time.strftime('%H:%M')}–{e.end_time.strftime('%H:%M')}",
        f"{TASK_EMOJI.get(e.task.task_type, '')} {e.task.name}",
        f"{PET_EMOJI.get(next(p.pet_type for p in jordan.pets if p.name == name), '')} {name}",
    ]
    for e, name in combined
]
print(tabulate(rows, headers=["Time", "Task", "Pet"], tablefmt="rounded_outline"))

# ---------------------------------------------------------------------------
# Mark tasks complete and show completion status
# ---------------------------------------------------------------------------

print()
for entry, _ in combined:
    entry.task.mark_complete()

for pet in jordan.pets:
    icon = PET_EMOJI.get(pet.pet_type, "🐾")
    completed = sum(1 for t in pet.tasks if t.completed)
    bar = "█" * completed + "░" * (len(pet.tasks) - completed)
    print(f"  {icon}  {pet.name}  [{bar}]  {completed}/{len(pet.tasks)} complete")

# ---------------------------------------------------------------------------
# Persistence: save, reload, verify
# ---------------------------------------------------------------------------

print()
save(owner_to_dict(jordan))
print("💾  Configuration saved to pawpal_save.json.")

reloaded = dict_to_owner(load())
PET_NAMES = ", ".join(
    f"{PET_EMOJI.get(p.pet_type, '')} {p.name}" for p in reloaded.pets
)
print(f"📂  Reloaded: {reloaded.name} — {PET_NAMES}")
