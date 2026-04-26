import os
from google import genai
from models import _mins


class ScheduleAgent:
    MODEL = "gemini-2.5-flash-lite"

    def __init__(self):
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

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
