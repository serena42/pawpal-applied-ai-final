"""
Persistence layer for PawPal+.

Provides two interfaces:
  - Owner ↔ dict  (used by main.py and tests)
  - File I/O      (save/load JSON; shared by app and scripts)

JSON format:
{
  "owner_name": "Jordan",
  "windows": [{"start": "08:00", "end": "18:00"}, ...],
  "pets": [
    {
      "name": "Mochi",
      "type": "dog",
      "tasks": [
        {"task_type": "walk", "duration_minutes": 30,
         "frequency": 3, "priority": 1, "completed": false},
        ...
      ]
    },
    ...
  ]
}
"""

import json
from datetime import time
from pathlib import Path
from models import Task, TaskType, Owner, Pet

DEFAULT_SAVE_FILE = Path("pawpal_save.json")


# ---------------------------------------------------------------------------
# Owner <-> dict
# ---------------------------------------------------------------------------

def owner_to_dict(owner: Owner) -> dict:
    """Serialize an Owner (with pets and tasks) to a JSON-compatible dict."""
    return {
        "owner_name": owner.name,
        "windows": [
            {
                "start": w.start.strftime("%H:%M"),
                "end":   w.end.strftime("%H:%M"),
            }
            for w in owner.availability_windows
        ],
        "pets": [
            {
                "name": pet.name,
                "type": pet.pet_type,
                "tasks": [
                    {
                        "task_type":        task.task_type.value,
                        "duration_minutes": task.duration_minutes,
                        "frequency":        task.frequency,
                        "priority":         task.priority,
                        "completed":        task.completed,
                    }
                    for task in pet.tasks
                ],
            }
            for pet in owner.pets
        ],
    }


def dict_to_owner(data: dict) -> Owner:
    """Deserialize a dict (as produced by owner_to_dict) into an Owner object."""
    owner = Owner(data["owner_name"])

    for w in data["windows"]:
        h, m = map(int, w["start"].split(":"))
        h2, m2 = map(int, w["end"].split(":"))
        owner.add_window(time(h, m), time(h2, m2))

    for pet_data in data["pets"]:
        pet = Pet(pet_data["name"], pet_data["type"])
        for td in pet_data["tasks"]:
            task = Task(
                TaskType(td["task_type"]),
                duration_minutes=td["duration_minutes"],
                frequency=td["frequency"],
                priority=td["priority"],
            )
            if td.get("completed"):
                task.mark_complete()
            pet.add_task(task)
        owner.add_pet(pet)

    return owner


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def save(data: dict, filepath: Path = DEFAULT_SAVE_FILE) -> None:
    """Write a dict to a JSON file."""
    filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load(filepath: Path = DEFAULT_SAVE_FILE) -> dict:
    """Read a JSON file and return its contents as a dict."""
    return json.loads(filepath.read_text(encoding="utf-8"))


def save_exists(filepath: Path = DEFAULT_SAVE_FILE) -> bool:
    """Return True when the save file exists on disk."""
    return filepath.exists()
