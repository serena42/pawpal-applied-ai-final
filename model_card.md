# PawPal+ Model Card

## System Overview

PawPal+ uses Google Gemini 2.5 Flash Lite for two distinct purposes inside a larger rule-based scheduling system.

**Primary use — coverage synthesis.** After the deterministic scheduler runs and the rule-based conflict detector computes coverage windows (specific time slots for a dog walker or pet sitter), `ScheduleAgent.summarize_coverage()` calls Gemini to translate those windows into a 3–5 sentence plain-language message for the owner — explaining what couldn't fit, what kind of help is needed and when, and whether nearby windows could be combined into a single visit. The LLM output is free text; no structured schema is enforced.

**Secondary use — conflict repair (edge cases).** The Streamlit UI also offers "Fix conflicts with AI": if tasks are in conflicting positions, `ScheduleAgent.fix_schedule()` calls Gemini iteratively (up to five rounds) to propose a single structured fix (move or swap) per round, validated by re-running conflict detection. This path is rarely triggered in practice — the deterministic scheduler prevents most conflict types before they occur — but handles cases when a user manually adjusts a task to an invalid slot.

**Design principle:** The LLM is never responsible for producing or owning the schedule. All scheduling decisions come from the deterministic algorithm; Gemini's role is either synthesis (explaining rule-based output in plain language) or repair (proposing a single corrective move, validated by rules).

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
| `eval_coverage.py` | 19 checks | Scheduling pipeline + coverage engine — 6 predefined scenarios, PASS/FAIL output, all passing |

`fix_schedule()` and `summarize_coverage()` require a live API key and are exercised via the Streamlit UI and demo scenario 5 respectively. `demo_agent.py` provides manual end-to-end verification across 5 realistic scenarios built from real scheduler output (scenarios 1–4 need no API key; scenario 5 calls Gemini).

### What Worked

Rule-based conflict detection is precisely testable — each conflict type has a definition and dedicated fixtures for both the positive and negative case. Writing both cases together (gap warning present / gap warning absent) caught logic errors that the positive case alone would miss. The `eval_coverage.py` harness extended the same pattern to the coverage-window engine: each scenario is a claim about what the scheduler produces and what coverage the engine suggests, with a PASS/FAIL verdict.

### What Didn't Work Initially

An early version of the fix parser used regex, which silently dropped suggestions phrased unexpectedly. Switching to JSON structured output (`response_mime_type="application/json"`) made parsing failures explicit and eliminated the ambiguity. This enforcement applies only to `fix_schedule()` — `summarize_coverage()` uses free-text output, where structured format would defeat the purpose.

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

**Dependency ordering compliance was reliable once stated explicitly.**
The model consistently moved the *dependent* task (medication) rather than the dependency (feeding), even without explicit instruction on which to prefer. Adding the rule "never move the dependency itself" to the prompt was still necessary — without it, early runs occasionally moved the wrong task — but once the constraint was in place, compliance was reliable across repeated runs.

**Ambiguous task names required explicit disambiguation.**
Tasks with the same name across different pets (e.g., both pets have a task called "Feeding") caused the parser to move the wrong occurrence. Without a `from_time` field in the JSON response, there was no way to tell which instance was meant. This drove the decision to require `from_time` in all move actions.

---

## AI Collaboration

**Helpful — urgency scoring formula:**

I described the problem: same-priority tasks were being scheduled in arbitrary order, so a 1×/day medication could block a 3×/day walk. I asked Claude to propose a formula that kept priority dominant while breaking ties on frequency and duration. It proposed `(6 − priority) × 10 + frequency × 2 − duration × 0.1` and correctly flagged that the priority coefficient needed to be large enough that no frequency/duration combination could promote a lower-priority task above a higher-priority one. I verified this with manual edge-case calculations before accepting it.

---

**Flawed — LLM for initial scheduling:**

Early in development, Claude suggested replacing the deterministic scheduler with an LLM that would "reason" about the optimal daily plan. I rejected this. Rule-based scheduling is deterministic, reproducible, and directly testable — all properties that matter when correctness is verifiable. An LLM scheduler would produce different plans on identical inputs with no way to unit-test the behavior. The right division is: algorithm for scheduling, AI for repair.

---

**Flawed — moving the dependency instead of the dependent task:**

In an early prompt for the dependency-violation scenario, Claude suggested moving *Feeding* earlier so that *Medication* could stay at 08:00. That was backwards — Feeding's time was intentional. The fix was to add the explicit rule "never move the dependency itself" to the prompt. This highlighted a general principle: the model will not infer domain constraints that are not stated; they must be written into the prompt.

---

**Flawed — demo cases that couldn't occur:**

Claude Code repeatedly suggested demo scenarios (overlapping tasks, medication before feeding) that the deterministic scheduler would never produce — it enforces all those constraints itself before any conflict detection runs. The real use case for the coverage-window engine is when the owner's availability windows are too narrow to fit all occurrences, or when scheduled tasks end up too far apart to meet care minimums. Correcting this required stepping back from the AI repair framing and redesigning the demo around what the scheduler actually produces. The CLI demo now uses real `Scheduler.generate_all_plans()` output rather than hand-crafted conflicting plans.

---

**Evolved — primary AI role shifted from repair to synthesis:**

Once the demo was redesigned around real scheduler output, a deeper consequence became clear: the repair loop had almost nothing to do. The deterministic scheduler prevents most conflict types before they occur, so `fix_schedule()` rarely triggers in practice. The more valuable AI opportunity was different in kind — the rule-based coverage engine computes technically correct windows (specific times for a dog walker or pet sitter) but produces terse, mechanical output the owner still has to interpret. Gemini's language ability is a better fit for translating five overlapping coverage windows into a single actionable sentence ("one midday visit from 13:00 covers all four gaps") than for the structured fix-selection problem the repair loop was solving. This shifted the primary AI call from a format-constrained JSON output task to a natural-language synthesis task, and `summarize_coverage()` became the main AI feature rather than an afterthought.
