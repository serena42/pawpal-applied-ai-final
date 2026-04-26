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

    # ------------------------------------------------------------------
    # Coverage summary — the primary AI feature in the current system
    # ------------------------------------------------------------------

    def summarize_coverage(self, plans: dict, conflicts: list,
                           coverage: list, owner, pets) -> str:
        """
        Ask Gemini to synthesize the coverage window suggestions into a
        concise, actionable plain-language message for the owner.
        """
        if not coverage and not conflicts:
            return "The schedule looks good — no coverage help needed today."
        prompt = self._build_summary_prompt(plans, conflicts, coverage, owner, pets)
        try:
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=prompt,
            )
            return response.text or "Unable to generate summary."
        except Exception:
            return "Unable to generate summary — check your API key."

    def _build_summary_prompt(self, plans: dict, conflicts: list,
                              coverage: list, owner, pets) -> str:
        windows_str = ", ".join(
            f"{w.start.strftime('%H:%M')}-{w.end.strftime('%H:%M')}"
            for w in owner.availability_windows
        )
        all_tasks = sorted(
            [(pet_name, st)
             for pet_name, plan in plans.items()
             for st in plan.scheduled],
            key=lambda x: _mins(x[1].start_time),
        )
        schedule_str = "\n".join(
            f"  {st.start_time.strftime('%H:%M')}-{st.end_time.strftime('%H:%M')}: "
            f"{st.task.name} ({pet_name})"
            for pet_name, st in all_tasks
        ) or "  (nothing scheduled)"

        warning_str = "\n".join(
            f"  [{pet_name}] {w}"
            for pet_name, plan in plans.items()
            for w in plan.warnings
        ) or "  None"

        conflict_str = "\n".join(
            f"  [{c.conflict_type}] {c.reason}"
            for c in conflicts
        ) or "  None"

        coverage_str = "\n".join(
            f"  {cw.start}-{cw.end}: {cw.service_type.replace('_', ' ')} "
            f"for {cw.pet_name} ({', '.join(cw.tasks) or 'general care'}) — {cw.reason}"
            for cw in coverage
        ) or "  None needed"

        profile_lines = []
        for pet in pets:
            age = getattr(pet, 'age_group', None)
            energy = getattr(pet, 'energy_level', None)
            ptype = getattr(pet, 'pet_type', 'pet')
            desc_parts = [ptype]
            if age:
                desc_parts.append(age)
            if energy:
                desc_parts.append(f"{energy} energy")
            task_desc = ", ".join(
                f"{t.name} x{t.frequency}/day ({t.duration_minutes} min)"
                for t in getattr(pet, 'tasks', [])
            )
            line = f"  {pet.name}: {', '.join(desc_parts)}"
            if task_desc:
                line += f" — needs: {task_desc}"
            profile_lines.append(line)
        pet_profiles_str = "\n".join(profile_lines) or "  (no profile data)"

        return (
            f"You are a knowledgeable pet care assistant helping {owner.name} plan their day.\n\n"
            f"Owner availability: {windows_str}\n\n"
            f"Pet profiles:\n{pet_profiles_str}\n\n"
            f"Today's schedule (what fit in the available windows):\n{schedule_str}\n\n"
            f"Scheduling warnings (tasks the system could not fully fit):\n{warning_str}\n\n"
            f"Detected conflicts:\n{conflict_str}\n\n"
            f"Coverage windows computed to close the gaps:\n{coverage_str}\n\n"
            f"Write a message to {owner.name} with two parts:\n\n"
            f"1. COVERAGE PLAN (2-3 sentences): State clearly what external help is needed, "
            f"what service type (dog walker vs pet sitter), and the specific time window. "
            f"Note if nearby windows can be combined into one visit.\n\n"
            f"2. PET CARE INSIGHTS (1-2 tips per pet with missed or gapped tasks): "
            f"Draw on the pet's age group, energy level, and the specific missed task to give "
            f"genuinely useful, actionable advice the owner or helper can act on. "
            f"Examples of the kind of insight to aim for: a puppy's missed walk is a prime "
            f"training opportunity — suggest leash manners or sit/stay practice; a high-energy "
            f"dog with a long feeding gap benefits from a puzzle feeder to prevent anxiety; "
            f"a senior pet's medication timing matters for absorption — suggest a small treat "
            f"paired with the pill; a cat alone all day may need an interactive toy left out. "
            f"Make the tips specific to this pet's profile, not generic.\n\n"
            f"Be warm but practical. Do not suggest the owner change their schedule. "
            f"Keep the total response under 200 words."
        )
