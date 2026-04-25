import json
import os
from google import genai
from google.genai import types
from models import _mins, _to_time
from conflict_detector import detect_conflicts, suggest_coverage_windows


def _parse_hhmm(s: str):
    """Parse 'HH:MM' to minutes since midnight, or None on failure."""
    if not s:
        return None
    parts = s.split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def _format_fix(fix: dict) -> str:
    """Human-readable summary of a fix dict for display in the UI."""
    action = fix.get("action", "none")
    if action == "move":
        task  = fix.get("task", "?")
        from_t = fix.get("from_time")
        to_t  = fix.get("to_time", "?")
        return f"Move {task} from {from_t} to {to_t}" if from_t else f"Move {task} to {to_t}"
    if action == "swap":
        return f"Swap {fix.get('task_a', '?')} and {fix.get('task_b', '?')}"
    return "No change"


class ScheduleAgent:
    MODEL = "gemini-2.5-flash-lite"

    def __init__(self):
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.max_iterations = 5

    def fix_schedule(self, plans: dict, owner, pets):
        """
        Iteratively detect conflicts and ask the AI to propose fixes.

        Returns (fixed_plans, history, coverage_windows) where:
        - history is a list of dicts: {iteration, conflicts_found, claude_suggestion}
        - coverage_windows is a list of CoverageWindow objects suggesting specific
          time slots for external services or owner availability expansion.
        """
        history = []
        for iteration in range(self.max_iterations):
            conflicts = detect_conflicts(plans, owner, pets)
            if not conflicts:
                break
            fix = self._ask_ai(plans, conflicts, owner)
            history.append({
                "iteration": iteration,
                "conflicts_found": len(conflicts),
                "claude_suggestion": _format_fix(fix),
            })
            plans = self._apply_fix(plans, fix)

        coverage = suggest_coverage_windows(plans, owner, pets)
        return plans, history, coverage

    def _ask_ai(self, plans: dict, conflicts: list, owner) -> dict:
        windows_str = ", ".join(
            f"{w.start.strftime('%H:%M')}-{w.end.strftime('%H:%M')}"
            for w in owner.availability_windows
        )
        prompt = (
            "You are a pet care schedule optimizer. Propose ONE specific change to fix a conflict.\n\n"
            f"Available time windows: {windows_str}\n\n"
            f"Current schedule:\n{self._format_schedule(plans)}\n\n"
            f"Conflicts to fix:\n{self._format_conflicts(conflicts)}\n\n"
            "Rules:\n"
            "- For OVERLAP conflicts: move the later-starting task to after the earlier task ends.\n"
            "- For DEPENDENCY conflicts: move the DEPENDENT task to after its dependency ends "
            "(never move the dependency itself).\n"
            "- For GAP conflicts: move the later occurrence to an earlier available window.\n"
            "- For POST_FEEDING_GAP conflicts: move the vigorous activity (walk/fetch/playtime) "
            "to at least 30 minutes after the feeding ends.\n"
            "- For MED_FEEDING_GAP conflicts: move the medication to at least 10 minutes after "
            "the feeding ends.\n"
            "- For WINDOW_VIOLATION conflicts: move the task to within its allowed time window.\n\n"
            "Respond with a JSON object — no other text.\n"
            'For a move: {"action":"move","task":"<name>","from_time":"HH:MM","to_time":"HH:MM"}\n'
            'For a swap: {"action":"swap","task_a":"<name>","task_b":"<name>"}\n'
            'If no fix is possible: {"action":"none"}\n'
            "Use task names exactly as shown in the schedule (no pet name in parentheses).\n"
            "from_time is required for move — it disambiguates tasks with the same name."
        )
        response = self.client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        try:
            return json.loads(response.text)
        except (json.JSONDecodeError, AttributeError):
            return {"action": "none"}

    def _apply_fix(self, plans: dict, fix: dict) -> dict:
        """Apply a fix dict returned by _ask_ai to the plan."""
        action = fix.get("action", "none")
        if action == "move":
            task_name = fix.get("task", "")
            to_mins   = _parse_hhmm(fix.get("to_time", ""))
            from_mins = _parse_hhmm(fix.get("from_time", ""))
            if not task_name or to_mins is None:
                return plans
            return self._move_task(plans, task_name, to_mins, from_mins=from_mins)
        if action == "swap":
            task_a = fix.get("task_a", "")
            task_b = fix.get("task_b", "")
            if task_a and task_b:
                return self._swap_tasks(plans, task_a, task_b)
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
            f"  [{c.conflict_type.upper()}] {c.reason} | Hint: {c.suggested_fix}"
            for c in conflicts
        )
