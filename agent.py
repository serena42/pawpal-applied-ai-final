import os
import re
from google import genai
from models import _mins, _to_time
from conflict_detector import detect_conflicts


class ScheduleAgent:
    MODEL = "gemini-2.5-flash-lite"

    def __init__(self):
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.max_iterations = 5

    def fix_schedule(self, plans: dict, owner, pets):
        """
        Iteratively detect conflicts and ask Claude to propose fixes.

        Returns (fixed_plans, history) where history is a list of dicts
        with keys: iteration, conflicts_found, claude_suggestion.
        """
        history = []
        for iteration in range(self.max_iterations):
            conflicts = detect_conflicts(plans, owner, pets)
            if not conflicts:
                break
            suggestion = self._ask_ai(plans, conflicts, owner)
            history.append({
                "iteration": iteration,
                "conflicts_found": len(conflicts),
                "claude_suggestion": suggestion,
            })
            plans = self._apply_fix(plans, suggestion)
        return plans, history

    def _ask_ai(self, plans: dict, conflicts: list, owner) -> str:
        windows_str = ", ".join(
            f"{w.start.strftime('%H:%M')}-{w.end.strftime('%H:%M')}"
            for w in owner.availability_windows
        )
        prompt = (
            "You are a pet care schedule optimizer. Propose ONE specific change to fix a conflict.\n\n"
            f"Available time windows: {windows_str}\n\n"
            f"Current schedule:\n{self._format_schedule(plans)}\n\n"
            f"Conflicts to fix:\n{self._format_conflicts(conflicts)}\n\n"
            "To fix a gap conflict, move the LATER occurrence to an earlier available window.\n\n"
            "Reply with ONLY one line. Use EXACTLY this format:\n"
            "  Move [task name] from HH:MM to HH:MM\n"
            "Use the task name exactly as shown in the schedule (no pet name in parentheses).\n"
            "No explanation. Just the change."
        )
        response = self.client.models.generate_content(model=self.MODEL, contents=prompt)
        return response.text.strip()

    def _apply_fix(self, plans: dict, suggestion: str) -> dict:
        """Parse the AI suggestion and apply it to the plan."""
        # Strip any trailing parenthetical pet name the model may add, e.g. "(Luna)".
        suggestion = re.sub(r'\s*\([^)]*\)', '', suggestion)

        # "Move Feeding from 20:00 to 09:00" — preferred form (from-time disambiguates)
        move_from = re.search(
            r"move\s+(.+?)\s+from\s+(\d{1,2}):(\d{2})\s+to\s+(\d{1,2}):(\d{2})",
            suggestion, re.IGNORECASE,
        )
        if move_from:
            task_name = move_from.group(1).strip()
            from_mins = int(move_from.group(2)) * 60 + int(move_from.group(3))
            to_mins   = int(move_from.group(4)) * 60 + int(move_from.group(5))
            return self._move_task(plans, task_name, to_mins, from_mins=from_mins)

        # "Move Feeding to 09:00" — fallback without from-time
        move = re.search(
            r"move\s+(.+?)\s+to\s+(\d{1,2}):(\d{2})",
            suggestion, re.IGNORECASE,
        )
        if move:
            task_name = move.group(1).strip()
            to_mins   = int(move.group(2)) * 60 + int(move.group(3))
            return self._move_task(plans, task_name, to_mins)

        # "Swap Feeding and Litter box"
        swap = re.search(r"swap\s+(.+?)\s+and\s+(.+)", suggestion, re.IGNORECASE)
        if swap:
            return self._swap_tasks(plans, swap.group(1).strip(), swap.group(2).strip())

        return plans

    def _move_task(self, plans: dict, task_name: str, new_start_mins: int,
                   from_mins: int = None) -> dict:
        name_lower = task_name.lower()
        for plan in plans.values():
            for st in plan.scheduled:
                if name_lower not in st.task.name.lower():
                    continue
                # If from_mins given, only move the occurrence at that exact time.
                if from_mins is not None and _mins(st.start_time) != from_mins:
                    continue
                duration = st.task.duration_minutes
                st.start_time = _to_time(new_start_mins)
                st.end_time = _to_time(new_start_mins + duration)
                return plans
        return plans

    def _swap_tasks(self, plans: dict, name_a: str, name_b: str) -> dict:
        all_sts = [st for plan in plans.values() for st in plan.scheduled]
        st_a = next((s for s in all_sts if name_a.lower() in s.task.name.lower()), None)
        st_b = next((s for s in all_sts if name_b.lower() in s.task.name.lower()), None)
        if st_a and st_b:
            st_a.start_time, st_b.start_time = st_b.start_time, st_a.start_time
            st_a.end_time, st_b.end_time = st_b.end_time, st_a.end_time
        return plans

    def _format_schedule(self, plans: dict) -> str:
        rows = sorted(
            [(pet, st) for pet, plan in plans.items() for st in plan.scheduled],
            key=lambda x: _mins(x[1].start_time),
        )
        return "\n".join(
            f"  {st.start_time.strftime('%H:%M')}–{st.end_time.strftime('%H:%M')}: "
            f"{st.task.name} ({pet})"
            for pet, st in rows
        )

    def _format_conflicts(self, conflicts: list) -> str:
        return "\n".join(
            f"  [{c.conflict_type.upper()}] {c.reason}" for c in conflicts
        )
