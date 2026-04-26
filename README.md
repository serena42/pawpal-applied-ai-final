# PawPal+ — AI-Powered Pet Care Scheduler

**Applied AI Final Project** | CodePath | Spring 2026

---

## Original Project

**PawPal** (Modules 1–3) was a rule-based daily pet care planner built with Python and Streamlit. An owner describes their available hours and their pets' care tasks; the scheduler produces a time-blocked daily plan that respects task priority, dependency ordering (e.g., medication after feeding), and recurring-task spacing. It used no external AI — all scheduling decisions came from a deterministic greedy algorithm with composite urgency scoring.

---

## What PawPal+ Adds

PawPal+ extends the original with three substantial AI features:

1. **Coverage window suggestions with AI synthesis** — after the scheduler runs, the conflict detector identifies tasks that couldn't fit or ended up spaced too far apart, and computes specific time slots where a dog walker or pet sitter would close each gap. `ScheduleAgent.summarize_coverage()` then calls Gemini 2.5 Flash Lite to translate those windows into a concise, actionable plain-language message for the owner — explaining what the problem is, what kind of help is needed and when, and whether nearby coverage windows could be combined into a single visit.

2. **Agentic repair loop (Streamlit UI edge case)** — the UI also offers "Fix conflicts with AI": if tasks end up in conflicting positions, `ScheduleAgent.fix_schedule()` calls Gemini iteratively (up to five rounds) to propose and apply a single structured fix (move or swap) per round, re-running conflict detection after each. In practice this path is rarely triggered — the deterministic scheduler prevents most conflict types before they occur — but it handles cases when a user manually adjusts a task to an invalid slot.

3. **Breed-tuned task defaults** — a trie-based breed database adjusts task duration and frequency multipliers for age group and energy level (e.g., a senior high-energy dog has longer walk durations than a puppy at low energy).

---

## Architecture Overview

  ```mermaid
  flowchart TD
      A([User — Streamlit UI or CLI]) -->|owner availability\npet type + breed| B

      B[Breed DB\nBreedTrie prefix search] -->|age/energy multipliers\napplied to duration +\nfrequency| C

      C[Scheduler\nmodels.py] -->|urgency scoring\ndependency sort\nslot assignment| D

      D[DailyPlan\nScheduledTask list + warnings] --> E

      E[Conflict Detector\nconflict_detector.py] -->|7 conflict types\n+ dropped-task warnings| F

      F[Coverage Windows\nsuggest_coverage_windows\ndog walker · pet sitter] --> G

      G([Schedule + Coverage\ndisplayed to user])

      G -->|Explain with AI\nbutton| H[ScheduleAgent\nsummarize_coverage]
      H -->|coverage windows +\nconflicts as prompt| I1[Gemini 2.5 Flash Lite\nLLM API]
      I1 -->|3-5 sentence\nowner summary| G

      G -->|Fix conflicts with AI\nbutton — edge cases| J[ScheduleAgent\nfix_schedule — up to 5 rounds]
      J -->|schedule + hints\nJSON prompt| I2[Gemini 2.5 Flash Lite\nLLM API]
      I2 -->|JSON fix\naction · task · from_time · to_time| K[Apply Fix\n_apply_fix]
      K -->|re-detect| E

      G -->|save| L[(pawpal_save.json\nPersistence)]
      L -->|load| A

      subgraph Testing ["Automated Testing"]
          T1[test_scheduler.py\n36 tests — Scheduler behavior]
          T2[test_agent.py\n103 tests — ConflictDetector\nAgent parsing · BreedTrie]
          T3[eval_coverage.py\n19 checks — pipeline\n+ coverage engine]
          T4[demo_agent.py\n5 scenarios — end-to-end\nscenario 5 calls Gemini]
      end

      C -.->|validates| T1
      E -.->|validates| T2
      H -.->|validates| T2
      F -.->|validates| T3
      G -.->|verifies| T4
  ```

**Key files:**

| File | Role |
|---|---|
| `models.py` | Data model + Scheduler algorithm |
| `conflict_detector.py` | Conflict detection + coverage suggestions |
| `agent.py` | Gemini-powered coverage synthesis (`summarize_coverage`) and iterative repair loop (`fix_schedule`) |
| `breed_db.py` | Trie-based breed lookup + multipliers |
| `app.py` | Streamlit UI |
| `main.py` | CLI demo (no API key needed) |
| `demo_agent.py` | 5-scenario scheduling pipeline demo; scenarios 1–4 need no API key, scenario 5 calls Gemini |
| `persistence.py` | JSON save / load |
| `test_scheduler.py` | 36 unit tests for Scheduler |
| `test_agent.py` | 103 unit tests for conflict detector + agent parsing + breed trie |
| `eval_coverage.py` | Evaluation script — 19 predefined checks across 6 scenarios, prints PASS/FAIL |

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

**Run the Streamlit UI** (no API key required to generate schedules; key needed for "Explain coverage needs with AI" and "Fix conflicts with AI"):
```bash
streamlit run app.py
```

**Run the scheduling pipeline demo** (scenarios 1–4 need no API key; scenario 5 requires `GEMINI_API_KEY`):
```bash
python demo_agent.py
```
Interactive menu — pick any of five realistic scenarios. Each one runs the deterministic scheduler within the owner's actual availability windows, detects what couldn't fit or ended up too far apart, and computes specific coverage windows (dog walker, pet sitter) that would close each gap. Scenario 5 passes those windows to Gemini and prints a plain-language recommendation. No hand-crafted conflicts: every plan is what the scheduler actually produces.

**Run all tests:**
```bash
python -m pytest test_scheduler.py test_agent.py -v
```

---

## Sample Interactions

The examples below show the three main interaction paths: the **scheduling pipeline demo** (CLI, no API key), the **AI coverage synthesis** (demo scenario 5 or Streamlit UI, requires `GEMINI_API_KEY`), and the **AI repair loop** (Streamlit UI, requires `GEMINI_API_KEY` — edge cases only, when tasks are manually placed in conflicting positions).

### Example 1 — Commuter's dog: scheduler drops 3rd walk, coverage computed (CLI demo)

**Setup:** Morgan is available 07:00–09:00 and 18:00–19:30. Rex needs 3 walks/day, but the adult 3-hour minimum between sessions means only 2 fit. The two feedings also end up 10 h 45 m apart, exceeding the 8-hour safe limit.

**Scheduler output:**
```
07:00-07:30: Walk (Rex)
07:30-07:45: Feeding (Rex)
18:00-18:30: Walk (Rex)
18:30-18:45: Feeding (Rex)
[WARN] 'Walk': only 2 of 3 occurrences scheduled - not enough availability windows.
[WARN] 'Feeding' gap of 10h 45m between occurrences 1 and 2
```

**Conflict detected:**
```
[GAP] Feeding for Rex: gap of 10h 45m between occurrences exceeds max 8h
```

**Coverage window suggestions:**
```
-> Pet Sitter for Rex: 12:45-13:30
   Feeding for Rex has a 10h 45m gap. A pet sitter visiting from 12:45 to 13:30 would close it.
-> Dog Walker for Rex: 13:05-13:55
   A midday walk for Rex isn't covered during your unavailability (09:00-18:00).
-> Pet Sitter for Rex: 09:15-11:15
   Some tasks couldn't fit in your available hours. Adding a pet sitter from 09:15 to 11:15 would create room for them.
```

---

### Example 2 — Two-pet household: AI synthesizes coverage advice (demo scenario 5 — requires GEMINI_API_KEY)

**Setup:** Taylor is available 07:00–09:00 and 17:30–19:00. Buddy (dog) needs 3 walks and 2 feedings; Miso (cat) needs 2 feedings and 2 litter-box cleanings. All tasks are scheduled but the 8.5-hour gap between Taylor's windows leaves every recurring task too far apart, and Buddy's 3rd walk is dropped entirely.

**Coverage windows computed (rule-based):**
```
-> Dog Walker for Buddy: 13:00-13:50
   A midday walk for Buddy isn't covered during your unavailability (09:00-17:30).
-> Pet Sitter for Buddy: 13:10-13:55
   Feeding for Buddy has a 10h 30m gap. A pet sitter visiting from 13:10 to 13:55 would close it.
-> Pet Sitter for Miso: 13:20-14:05
   Feeding for Miso has a 10h 30m gap. A pet sitter visiting from 13:20 to 14:05 would close it.
-> Pet Sitter for Miso: 13:30-14:15
   Litter box for Miso has a 10h 30m gap. A pet sitter visiting from 13:30 to 14:15 would close it.
```

**AI summary (Gemini — scenario 5):**
```
Taylor, all of Buddy and Miso's morning and evening care fits your current schedule,
but the gap between your windows leaves both pets unattended from 09:00 to 17:30.
Buddy is missing his third walk, and both pets' midday feedings — plus Miso's
second litter box cleaning — are overdue by the time you're home. The good news
is that all four coverage windows overlap: a single midday visit between 13:00 and
14:15 from someone who can walk a dog and handle basic cat care would cover
everything at once. Book a dog walker/pet sitter for that slot and your pets'
needs are fully met.
```

---

### Example 3 — Simple overlap, AI repair (Streamlit UI — requires GEMINI_API_KEY)

> These examples (3–5) show the repair loop, which handles edge cases when tasks are manually placed in conflicting positions in the UI. The deterministic scheduler prevents these conflicts automatically during normal scheduling.

**Setup:** Alex's dog Buddy has a 30-min morning walk (08:00–08:30) and a 15-min feeding accidentally placed at 08:20, overlapping by 10 minutes. (Simulates a user dragging a task to an overlapping slot in the app.)

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

### Example 4 — Multi-pet cascade, AI repair (Streamlit UI — requires GEMINI_API_KEY)

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

### Example 5 — Dependency violation, AI repair (Streamlit UI — requires GEMINI_API_KEY)

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
Flash Lite is fast and cheap. For coverage synthesis the task is open-ended but short (3–5 sentences), so a larger model adds latency with no observable quality gain. For the repair loop the task is narrow and format-constrained (one JSON object), where Flash Lite is clearly sufficient.

**Two distinct AI output modes.**
`summarize_coverage()` uses free-text output — the prompt asks for a plain-language message and does not constrain the format. `fix_schedule()` enforces `response_mime_type="application/json"` and defines an exact schema (`action`, `task`, `from_time`, `to_time`). Invalid or missing JSON responses fall back to returning the plan unchanged — the system never crashes on a bad AI response.

**Rule-based scheduling, AI for synthesis and repair.**
The original scheduler uses a deterministic algorithm. Letting the AI handle initial scheduling would make the system unpredictable and untestable. The AI has two well-scoped roles: narrating rule-based coverage windows in plain language (synthesis), and proposing task moves when the user manually creates a conflict (repair). Every repair suggestion is validated by re-running conflict detection.

**Seven conflict types, each with a `suggested_fix` hint sent to the AI.**
For the repair loop, the prompt includes a specific hint (`"Move Feeding to 08:30 or later"`) rather than asking the AI to reason from scratch. This reduces hallucination risk — the AI is nudged toward the right class of fix without being given the full answer.

**Trie for breed lookup instead of semantic search.**
Owners type in a breed name. Trie prefix search is O(k) per lookup (k = string length), requires no model, and handles partial matches ("Golden" → "Golden Retriever"). A vector store would add infrastructure cost and complexity with no benefit for exact or prefix-match queries.

**Trade-offs accepted:**
- Breed data is hardcoded. A real product would pull from a maintained database.
- No authentication. The app is single-user.

---

## Testing

**139 tests, all passing.**

```bash
python -m pytest test_scheduler.py test_agent.py -v   # all 139
python -m pytest test_scheduler.py -v                 # 36 — Scheduler behavior
python -m pytest test_agent.py -v                     # 103 — conflict detector, agent, breed trie
python eval_coverage.py                               # 19 predefined checks across 6 scenarios
```

`eval_coverage.py` runs 19 predefined PASS/FAIL checks across 6 scenarios — including a control case (wide window, everything fits, no coverage needed) — and prints a summary line. No API key required.

`ScheduleAgent.fix_schedule()` and `summarize_coverage()` require a live API key and are exercised via the Streamlit UI and demo scenario 5 respectively. `demo_agent.py` provides end-to-end verification of the scheduling pipeline and coverage-window engine across 5 realistic scenarios (no mocking; scenarios 1–4 need no API key).

---

## Reflection, Ethics, and AI Collaboration

See [model_card.md](model_card.md) — covers limitations, bias, misuse potential, testing results, and AI collaboration examples.
