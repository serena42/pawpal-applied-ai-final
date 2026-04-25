# PawPal+ — AI-Powered Pet Care Scheduler

**Applied AI Final Project** | CodePath | Spring 2026

---

## Original Project

**PawPal** (Modules 1–3) was a rule-based daily pet care planner built with Python and Streamlit. An owner describes their available hours and their pets' care tasks; the scheduler produces a time-blocked daily plan that respects task priority, dependency ordering (e.g., medication after feeding), and recurring-task spacing. It used no external AI — all scheduling decisions came from a deterministic greedy algorithm with composite urgency scoring.

---

## What PawPal+ Adds

PawPal+ extends the original with three substantial AI features:

1. **Agentic conflict-detection and repair loop** — after the scheduler runs, a `ScheduleAgent` detects conflicts (overlaps, dependency violations, gap violations, window violations) and calls the Google Gemini 2.5 Flash Lite API iteratively to propose and apply fixes, up to five rounds, until the schedule is clean.

2. **Coverage window suggestions** — when conflicts cannot be resolved within the owner's existing hours, the system calculates specific time windows where a dog walker or pet sitter would close the gap, and displays them in the UI.

3. **Breed-tuned task defaults** — a trie-based breed database adjusts task duration and frequency multipliers for age group and energy level (e.g., a senior high-energy dog has longer walk durations than a puppy at low energy).

---

## Architecture Overview

  ```mermaid
  flowchart TD
      A([User — Streamlit UI or CLI]) -->|owner availability\npet type + breed| B

      B[Breed DB\nBreedTrie prefix search] -->|age/energy multipliers\napplied to duration +
  frequency| C

      C[Scheduler\nmodels.py] -->|urgency scoring\ndependency sort\nslot assignment| D

      D[DailyPlan\nScheduledTask list + warnings]

      D --> E{Conflict Detector\nconflict_detector.py}

      E -->|7 conflict types:\noverlap · dependency · timeout\noutside_window ·
  gap\nmed_feeding_gap · post_feeding_gap| F{Conflicts\nfound?}

      F -->|No| G([Final Schedule\ndisplayed to user])

      F -->|Yes| H[ScheduleAgent\nagent.py]

      H -->|schedule + conflicts\nas structured prompt| I[Gemini 2.5 Flash Lite\nLLM API]

      I -->|JSON fix\naction · task · from_time · to_time| J[Apply Fix\n_apply_fix]

      J -->|re-detect| E

      H -->|max 5 iterations\nunresolved conflicts remain| K[Coverage
  Window\nSuggestions\ndog walker · pet sitter]

      G --> L([Human Review\nuser inspects plan\nin UI])
      K --> L

      L -->|save| M[(pawpal_save.json\nPersistence)]
      M -->|load| A

      subgraph Testing ["Automated Testing (pytest)"]
          T1[test_scheduler.py\n36 tests — Scheduler behavior]
          T2[test_agent.py\n103 tests — ConflictDetector\nAgent parsing · BreedTrie]
          T3[demo_agent.py\n3 scenarios — manual\nend-to-end verification]
      end

      C -.->|validates| T1
      E -.->|validates| T2
      H -.->|validates| T2
      G -.->|verifies| T3
  ```

**Key files:**

| File | Role |
|---|---|
| `models.py` | Data model + Scheduler algorithm |
| `conflict_detector.py` | Conflict detection + coverage suggestions |
| `agent.py` | Gemini-powered iterative repair loop |
| `breed_db.py` | Trie-based breed lookup + multipliers |
| `app.py` | Streamlit UI |
| `main.py` | CLI demo (no API key needed) |
| `demo_agent.py` | 3-scenario agent demo (requires API key) |
| `persistence.py` | JSON save / load |
| `test_scheduler.py` | 15 unit tests for Scheduler |
| `test_agent.py` | 122 unit tests for conflict detector + agent parsing + breed trie |

---

## Setup Instructions

**Requirements:** Python 3.11+, a Google Gemini API key (free tier works).

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd pawpal-applied-ai-final

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your Gemini API key (needed for agent features only)
export GEMINI_API_KEY="your-key-here"   # Windows: set GEMINI_API_KEY=your-key-here
```

**Run the CLI demo** (no API key required):
```bash
python main.py
```
Creates owner Jordan with two pets (Mochi the dog, Luna the cat), schedules their tasks, and saves/reloads the configuration.

**Run the Streamlit UI** (no API key required to generate schedules; key needed for "Fix conflicts with AI"):
```bash
streamlit run app.py
```

**Run the agentic demo** (requires `GEMINI_API_KEY`):
```bash
python demo_agent.py
```
Runs three pre-built conflict scenarios through the full detect → repair → verify loop.

**Run all tests:**
```bash
python -m pytest test_scheduler.py test_agent.py -v
```

---

## Sample Interactions

### Example 1 — Simple overlap, resolved in one iteration

**Setup:** Alex's dog Buddy has a 30-min morning walk (08:00–08:30) and a 15-min feeding accidentally placed at 08:20, overlapping by 10 minutes.

**Conflict detected:**
```
[OVERLAP] Morning Walk (Buddy, 08:00–08:30) overlaps Feeding (Buddy, 08:20–08:35)
  Hint: Move Feeding to 08:30 or later
```

**AI suggestion (Iteration 1):**
```
Move Feeding from 08:20 to 08:30
```

**Final schedule:**
```
08:00–08:30: Morning Walk (Buddy)
08:30–08:45: Feeding (Buddy)
All conflicts resolved in 1 iteration.
```

---

### Example 2 — Multi-pet cascade, resolved in two iterations

**Setup:** Jordan has Mochi (dog) and Luna (cat). Mochi has a walk/feeding overlap; Luna has a feeding/litter-box overlap.

**Conflicts detected (2):**
```
[OVERLAP] Morning Walk (Mochi, 08:00–08:30) overlaps Feeding (Mochi, 08:20–08:35)
[OVERLAP] Feeding (Luna, 10:00–10:15) overlaps Litter box (Luna, 10:10–10:20)
```

**Agent loop:**
```
Iteration 1: 2 conflict(s) found → Move Feeding from 08:20 to 08:30
Iteration 2: 1 conflict(s) found → Move Litter box from 10:10 to 10:15
All conflicts resolved in 2 iterations.
```

---

### Example 3 — Dependency violation (medication before feeding)

**Setup:** Sam's dog Max needs medication after eating. The schedule has Medication at 08:00, but Feeding isn't until 09:00 — violating the declared dependency.

**Conflict detected:**
```
[DEPENDENCY] Medication (Max) starts at 08:00 before dependency Feeding ends at 09:15
  Hint: Move Medication to after 09:15
```

**AI suggestion (Iteration 1):**
```
Move Medication from 08:00 to 09:15
```

**Final schedule:**
```
09:00–09:15: Feeding (Max)
09:15–09:20: Medication (Max)
All conflicts resolved in 1 iteration.
```

---

## Design Decisions and Trade-offs

**Gemini 2.5 Flash Lite over a larger model.**
The task is narrow and structured — the AI only needs to parse a schedule and output one line. Flash Lite is fast and cheap. A larger model would add latency and cost with no observable quality gain for this format-constrained output.

**Strict one-line output format enforced in the prompt.**
The agent prompt says: "Reply with ONLY one line. Use EXACTLY this format: Move [task name] from HH:MM to HH:MM." Unparseable responses fall back to returning the plan unchanged. This is a guardrail: the system never crashes on a bad AI response, and it never silently applies a misinterpreted fix.

**Rule-based scheduling, AI for repair only.**
The original scheduler uses a deterministic algorithm. Letting the AI handle initial scheduling would make the system unpredictable and untestable. The AI is confined to a well-defined repair role where every suggestion can be validated by re-running conflict detection.

**Seven conflict types, each with a `suggested_fix` hint sent to the AI.**
Rather than asking the AI to reason from scratch about how to fix a conflict, the prompt includes a specific hint (`"Move Feeding to 08:30 or later"`). This dramatically reduces hallucination risk — the AI is nudged toward the right class of fix without being given the full answer.

**Trie for breed lookup instead of semantic search.**
Owners type in a breed name. Trie prefix search is O(k) per lookup (k = string length), requires no model, and handles partial matches ("Golden" → "Golden Retriever"). A vector store would add infrastructure cost and complexity with no benefit for exact or prefix-match queries.

**Trade-offs accepted:**
- The AI fix parser uses regex, so suggestions in unexpected phrasing are silently dropped. A more robust parser (or structured JSON output from the model) would improve reliability but would add latency via a tool-use round-trip.
- Breed data is hardcoded. A real product would pull from a maintained database.
- No authentication. The app is single-user.

---

## Testing Summary

**137 tests across two suites, all passing.**

```
pytest test_scheduler.py test_agent.py -v
...
137 passed in X.XXs
```

**`test_scheduler.py` — 15 tests covering the scheduling core:**
- Availability window duration arithmetic
- Task defaults and partial overrides
- `mark_complete()` flag behavior
- Priority-sorted task list
- Urgency score frequency tie-breaking (high-frequency same-priority tasks scheduled first)
- Happy-path scheduling (all tasks fit, no warnings)
- Priority ordering in output plan
- Capacity enforcement (tasks dropped when time runs out)
- Warning generation when tasks are dropped
- Gap warning absent when feedings are close together
- Gap warning present when feedings are forced 11 hours apart
- Recurring task spacing (3 walks spread ≥ 90 min apart across a 10-hour day)
- Two-pet no-overlap (no time slot shared across pets)
- Dependency ordering (Medication always follows Feeding)

**`test_agent.py` — 122 tests covering the AI layer:**
- Clean schedule returns zero conflicts
- Overlap detection and non-detection (adjacent tasks are not overlaps)
- Gap threshold detection for feedings, medication, and walks
- Dependency violation detection (dependent task before dependency)
- Window violation detection (task before its earliest / after its latest)
- Post-feeding gap detection (vigorous activity too soon after eating)
- Med-feeding gap detection (medication too soon after feeding)
- AI fix parser: "Move X from HH:MM to HH:MM", "Move X to HH:MM", "Swap X and Y"
- Parser robustness: parenthetical pet names stripped, case-insensitive, from-time disambiguates duplicate task names
- Breed trie: prefix search, exact match, case folding, unknown breed returns None
- Breed attribute retrieval (energy level, age group, multiplier values)
- Multiplier constants: duration/frequency multipliers by age group and energy level
- Multiplier application: scheduler output reflects breed-derived adjustments
- Scheduler integration with breed tuner (end-to-end with real objects)

**What worked:** Rule-based conflict detection is highly testable — every conflict type has a precise definition and a dedicated test fixture. The AI parser tests proved essential: an early version of the regex didn't strip trailing parenthetical pet names (`"Move Feeding to 08:30 (Mochi)"`), which caused silent failures.

**What didn't work initially:** Testing the AI agent itself requires a live API key, so the agent's `fix_schedule()` method is not covered by automated tests. The three scenarios in `demo_agent.py` serve as manual end-to-end verification. A future improvement would be to mock the Gemini client and test the full loop with canned responses.

**What I learned:** Writing the positive and negative cases for gap warnings together (gap present / gap absent) was more valuable than either test alone. The positive case would pass even if the warning logic were broken; you need the negative case to know the threshold logic is actually being checked.

---

## Reflection and Ethics

### Limitations and biases

- **Breed data is hardcoded and incomplete.** The trie covers common breeds but will silently return `None` for mixed breeds, rare breeds, or misspellings. The system falls back to defaults, but it won't tell the user it couldn't find a match.
- **The AI fix parser is fragile.** If Gemini phrases a suggestion in a way the regex doesn't match — e.g., "Reschedule Feeding to 08:30" instead of "Move Feeding to 08:30" — the fix is silently skipped and the conflict persists. The user sees the conflict remain without knowing why.
- **No medical knowledge.** The post-feeding gap (30 min before vigorous activity) and medication timing rules are hardcoded heuristics. For animals with specific conditions, these rules could be wrong.
- **Single-user, no persistence of agent history.** The iterative repair history is shown in the UI but not saved. There is no way to audit why the AI made a particular change after the session ends.

### Could this be misused?

The risks are low — it's a pet scheduling app, not a medical decision system. The most realistic misuse would be a user ignoring conflict warnings and following an AI-suggested schedule that is medically inappropriate for their pet (e.g., exercising a dog with a heart condition). Mitigations: display disclaimers that the app is not a substitute for veterinary advice, and surface unresolved conflicts clearly rather than hiding them.

### What surprised me during testing

The AI reliably suggested moving the *dependent* task rather than the dependency in Scenario 3 (medication before feeding). This was not guaranteed — the prompt explains the rule, but I expected the model to occasionally suggest moving the feeding earlier instead. Across multiple runs, it consistently followed the constraint in the prompt. What was less reliable was handling of tasks with the same name across different pets. Without the "from HH:MM" disambiguation, the parser would sometimes move the wrong pet's task, which led to adding the from-time pattern as the preferred regex branch.

### AI collaboration

**Helpful suggestion — urgency scoring formula:**
When I described the problem (same-priority tasks scheduled in arbitrary order), I asked Claude to propose a scoring formula that kept priority dominant while breaking ties on frequency and duration. It proposed `(6 − priority) × 10 + frequency × 2 − duration × 0.1`, and correctly identified that the priority weight needed to be large enough that no combination of frequency and duration bonuses could cause a lower-priority task to outscore a higher-priority one. I verified this by computing edge-case scores manually before accepting it.

**Flawed suggestion — LLM for initial scheduling:**
Early in development, Claude suggested replacing the deterministic scheduler with an LLM that would "reason" about the optimal daily plan. I rejected this. Rule-based scheduling is deterministic, reproducible, and directly testable — all properties that matter for a correctness-critical feature. An LLM scheduler would be a black box that could produce different plans on identical inputs. The right division of labor is: deterministic algorithm for scheduling, AI for conflict repair.

**Flawed suggestion — moving the dependency instead of the dependent task:**
An early version of the prompt for Scenario 3 didn't include the rule "never move the dependency itself." Claude's first suggested fix was to move Feeding earlier so that Medication could stay at 08:00. This was wrong — Feeding's time was already intentional. Adding the explicit rule to the prompt fixed the behavior, but it highlighted that AI suggestions need domain-specific constraints baked into the prompt rather than relying on the model to infer them.

---

## Running the Tests (Quick Reference)

```bash
# All 137 tests
python -m pytest test_scheduler.py test_agent.py -v

# Scheduler only (15 tests, no API key needed)
python -m pytest test_scheduler.py -v

# Agent + conflict detector + breed (122 tests, no API key needed)
python -m pytest test_agent.py -v
```
