# PawPal+ Model Card

## System Overview

PawPal+ uses Google Gemini 2.5 Flash Lite as a conflict-repair agent inside a larger rule-based pet care scheduling system. The LLM is not responsible for producing schedules — it proposes a single structured fix (move or swap a task) when the deterministic scheduler produces a plan with conflicts. Every suggestion is validated by re-running the conflict detector before being accepted.

**Intended use:** Personal, single-user daily pet care planning. Not a substitute for veterinary advice.

---

## Testing Results

**139 tests, all passing.**

```
pytest test_scheduler.py test_agent.py -v
139 passed in ~1.5s
```

| Suite | Tests | What it covers |
|---|---|---|
| `test_scheduler.py` | 36 | Scheduler behavior — urgency scoring, dependency ordering, gap enforcement, breed multipliers, time window constraints |
| `test_agent.py` | 103 | Conflict detection (7 types), agent fix parsing, breed trie, multiplier constants, coverage window suggestions |

The agent's `fix_schedule()` loop is not covered by automated tests — it requires a live API key and is exercised via the Streamlit UI. `demo_agent.py` provides manual end-to-end verification of the scheduling pipeline and coverage-window engine across 4 realistic scenarios built from real scheduler output (no API key needed, no hand-crafted conflicts).

**What worked:** Rule-based conflict detection is precisely testable — each conflict type has a definition and dedicated fixtures for both the positive and negative case. Writing both cases together (gap warning present / gap warning absent) caught logic errors that the positive case alone would miss.

**What didn't work initially:** An early version of the fix parser used regex, which silently dropped suggestions phrased unexpectedly. Switching to JSON structured output (`response_mime_type="application/json"`) made parsing failures explicit and eliminated the ambiguity.

---

## Limitations and Biases

- **Breed data is hardcoded.** The trie covers 50 common breeds. Mixed breeds, rare breeds, and misspellings fall back to defaults silently — the user is not told the lookup failed.
- **Hardcoded medical heuristics.** The 30-minute post-feeding gap before vigorous activity and the 10-minute medication gap are reasonable defaults, but wrong for animals with specific conditions. The app has no veterinary knowledge.
- **No agent history persistence.** The AI's iteration-by-iteration reasoning is shown in the UI during the session but not saved. There is no audit trail after the page reloads.
- **Single-user, no auth.** Anyone with the URL can edit the schedule.

---

## Misuse Potential

Risk is low — this is a scheduling tool, not a medical system. The most realistic harm is a user following an AI-suggested schedule that is inappropriate for a pet with an undisclosed health condition (e.g., exercising a dog with a heart condition right after the 30-minute waiting period). Mitigation: surface unresolved conflicts clearly, never hide them, and add a disclaimer that the app does not replace veterinary guidance.

---

## What Surprised Me During Testing

The model consistently moved the *dependent* task (medication) rather than the dependency (feeding) in Scenario 3, even without explicit instruction on which to prefer. Adding the rule "never move the dependency itself" to the prompt was still necessary — without it, early runs occasionally moved the wrong task — but once the constraint was in place, compliance was reliable across repeated runs.

What was less reliable: tasks with the same name across different pets (e.g., both pets have a task called "Feeding"). Without a `from_time` field in the JSON response to disambiguate, the parser would move the wrong occurrence. This drove the decision to require `from_time` in all move actions.

---

## AI Collaboration

**Helpful — urgency scoring formula:**
I described the problem: same-priority tasks were being scheduled in arbitrary order, so a 1×/day medication could block a 3×/day walk. I asked Claude to propose a formula that kept priority dominant while breaking ties on frequency and duration. It proposed `(6 − priority) × 10 + frequency × 2 − duration × 0.1` and correctly flagged that the priority coefficient needed to be large enough that no frequency/duration combination could promote a lower-priority task above a higher-priority one. I verified this with manual edge-case calculations before accepting it.

**Flawed — LLM for initial scheduling:**
Early in development, Claude suggested replacing the deterministic scheduler with an LLM that would "reason" about the optimal daily plan. I rejected this. Rule-based scheduling is deterministic, reproducible, and directly testable — all properties that matter when correctness is verifiable. An LLM scheduler would produce different plans on identical inputs with no way to unit-test the behavior. The right division is: algorithm for scheduling, AI for repair.

**Flawed — moving the dependency instead of the dependent task:**
In an early prompt for the dependency-violation scenario, Claude suggested moving *Feeding* earlier so that *Medication* could stay at 08:00. That was backwards — Feeding's time was intentional. The fix was to add the explicit rule "never move the dependency itself" to the prompt. This highlighted a general principle: the model will not infer domain constraints that are not stated; they must be written into the prompt.

**Flawed — demo cases that couldn't occur:**
Claude Code repeatedly suggested demo scenarios (overlapping tasks, medication before feeding) that the deterministic scheduler would never produce — it enforces all those constraints itself before any conflict detection runs. The real use case for the coverage-window engine is when the owner's availability windows are too narrow to fit all occurrences, or when scheduled tasks end up too far apart to meet care minimums. Correcting this required stepping back from the AI repair framing and redesigning the demo around what the scheduler actually produces. The CLI demo now uses real `Scheduler.generate_all_plans()` output rather than hand-crafted conflicting plans.
