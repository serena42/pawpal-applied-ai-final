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
| `test_scheduler.py` | 36 unit tests for Scheduler |
| `test_agent.py` | 103 unit tests for conflict detector + agent parsing + breed trie |

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

**JSON structured output enforced in the prompt.**
The agent requests `response_mime_type="application/json"` from Gemini and defines an exact schema (`action`, `task`, `from_time`, `to_time`). Invalid or missing responses fall back to returning the plan unchanged — the system never crashes on a bad AI response.

**Rule-based scheduling, AI for repair only.**
The original scheduler uses a deterministic algorithm. Letting the AI handle initial scheduling would make the system unpredictable and untestable. The AI is confined to a well-defined repair role where every suggestion can be validated by re-running conflict detection.

**Seven conflict types, each with a `suggested_fix` hint sent to the AI.**
Rather than asking the AI to reason from scratch about how to fix a conflict, the prompt includes a specific hint (`"Move Feeding to 08:30 or later"`). This dramatically reduces hallucination risk — the AI is nudged toward the right class of fix without being given the full answer.

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
```

The agent's live API loop is verified manually via `python demo_agent.py` (3 scenarios, no mocking).

---

## Reflection, Ethics, and AI Collaboration

See [model_card.md](model_card.md) — covers limitations, bias, misuse potential, testing results, and AI collaboration examples.
